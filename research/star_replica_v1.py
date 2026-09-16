from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
VERIFIED = REPO / "data" / "verified"
DERIVED = REPO / "data" / "derived"
DERIVED.mkdir(parents=True, exist_ok=True)

TARGET_FILES = [
    VERIFIED / "daily_star_2022.csv",
    VERIFIED / "daily_star_2023.csv",
    VERIFIED / "daily_star_2024.csv",
    VERIFIED / "daily_star_2025.csv",
]

TENCENT_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
SYMBOL = "sh000985"  # 中证全指


def load_targets() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in TARGET_FILES:
        df = pd.read_csv(path)
        df["date"] = pd.to_datetime(df["date"])
        if "status" not in df.columns:
            raise ValueError(f"missing status column: {path}")
        frames.append(df)

    target = pd.concat(frames, ignore_index=True).sort_values("date")
    target = target[target["status"] != "unresolved"].copy()

    # Normalize interval information. For exact/approx/derived rows without
    # explicit bounds, low/high both equal the point label.
    target["star_low"] = pd.to_numeric(target.get("star_low"), errors="coerce")
    target["star_high"] = pd.to_numeric(target.get("star_high"), errors="coerce")
    target["star"] = pd.to_numeric(target.get("star"), errors="coerce")
    target["star_low"] = target["star_low"].fillna(target["star"])
    target["star_high"] = target["star_high"].fillna(target["star"])
    target["target_mid"] = (target["star_low"] + target["star_high"]) / 2

    # Evidence-quality weights. Main conclusions should always be checked on
    # exact rows separately; these weights only affect baseline fitting.
    weights = {
        "exact": 1.0,
        "range": 0.55,
        "approx": 0.50,
        "derived": 0.25,
    }
    target["weight"] = target["status"].map(weights).fillna(0.0)
    target = target[target["weight"] > 0].copy()
    return target


def _fetch_year(year: int) -> pd.DataFrame:
    start = f"{year}-01-01"
    end = f"{year}-12-31"
    params = f"{SYMBOL},day,{start},{end},370,qfq"
    url = TENCENT_URL + "?" + urllib.parse.urlencode({"param": params})
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)

    node = payload.get("data", {}).get(SYMBOL, {})
    rows = node.get("qfqday") or node.get("day") or []
    if not rows:
        raise RuntimeError(f"no Tencent K-line rows for {year}: {url}")

    out = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume"])
    out["date"] = pd.to_datetime(out["date"])
    for col in ["open", "close", "high", "low", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def load_market() -> pd.DataFrame:
    cache = DERIVED / "csi_all_share_2022_2025.csv"
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["date"])
    else:
        df = pd.concat([_fetch_year(y) for y in range(2022, 2026)], ignore_index=True)
        df = df.drop_duplicates("date").sort_values("date")
        df.to_csv(cache, index=False)

    df = df.sort_values("date").copy()
    df["log_close"] = df["close"].map(math.log)
    df["ret_20"] = df["close"].pct_change(20)
    df["ret_60"] = df["close"].pct_change(60)
    df["ma_250"] = df["close"].rolling(250, min_periods=120).mean()
    df["close_to_ma250"] = df["close"] / df["ma_250"] - 1
    df["high_252"] = df["close"].rolling(252, min_periods=120).max()
    df["drawdown_252"] = df["close"] / df["high_252"] - 1
    df["rank_500"] = (
        df["close"]
        .rolling(500, min_periods=180)
        .apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1], raw=False)
    )
    return df


def weighted_linear_fit(x: pd.Series, y: pd.Series, w: pd.Series) -> tuple[float, float]:
    mask = x.notna() & y.notna() & w.notna() & (w > 0)
    xx = x[mask].astype(float)
    yy = y[mask].astype(float)
    ww = w[mask].astype(float)
    sw = ww.sum()
    mx = (ww * xx).sum() / sw
    my = (ww * yy).sum() / sw
    cov = (ww * (xx - mx) * (yy - my)).sum()
    var = (ww * (xx - mx) ** 2).sum()
    b = cov / var
    a = my - b * mx
    return a, b


def pav_decreasing(x: pd.Series, y: pd.Series, w: pd.Series) -> tuple[list[float], list[float]]:
    """Weighted pool-adjacent-violators fit for a decreasing relation y=f(x)."""
    tmp = pd.DataFrame({"x": x, "y": y, "w": w}).dropna().sort_values("x")
    grouped = tmp.groupby("x", as_index=False).apply(
        lambda g: pd.Series({"y": (g.y * g.w).sum() / g.w.sum(), "w": g.w.sum()}),
        include_groups=False,
    ).reset_index(drop=True)
    xs = sorted(tmp["x"].unique().tolist())
    ys = grouped["y"].tolist()
    ws = grouped["w"].tolist()

    blocks: list[dict[str, float | int]] = []
    for i, (yy, ww) in enumerate(zip(ys, ws)):
        blocks.append({"start": i, "end": i, "w": ww, "y": yy})
        while len(blocks) >= 2 and float(blocks[-2]["y"]) < float(blocks[-1]["y"]):
            b2 = blocks.pop()
            b1 = blocks.pop()
            tw = float(b1["w"]) + float(b2["w"])
            ty = (float(b1["y"]) * float(b1["w"]) + float(b2["y"]) * float(b2["w"])) / tw
            blocks.append({"start": int(b1["start"]), "end": int(b2["end"]), "w": tw, "y": ty})

    fitted = [0.0] * len(xs)
    for block in blocks:
        for i in range(int(block["start"]), int(block["end"]) + 1):
            fitted[i] = float(block["y"])
    return xs, fitted


def interp_monotone(xs: list[float], ys: list[float], x: float) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    lo, hi = 0, len(xs) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    if xs[hi] == xs[lo]:
        return ys[lo]
    t = (x - xs[lo]) / (xs[hi] - xs[lo])
    return ys[lo] + t * (ys[hi] - ys[lo])


def interval_abs_error(pred: pd.Series, low: pd.Series, high: pd.Series) -> pd.Series:
    return pd.Series(
        [0.0 if lo <= p <= hi else min(abs(p - lo), abs(p - hi)) for p, lo, hi in zip(pred, low, high)],
        index=pred.index,
    )


def score(df: pd.DataFrame, pred_col: str) -> dict[str, float]:
    use = df[df[pred_col].notna()].copy()
    exact = use[use["status"] == "exact"].copy()
    return {
        "n": int(len(use)),
        "exact_n": int(len(exact)),
        "interval_mae": float(interval_abs_error(use[pred_col], use.star_low, use.star_high).mean()),
        "exact_mae": float((exact[pred_col] - exact.target_mid).abs().mean()) if len(exact) else float("nan"),
        "exact_within_0.1": float(((exact[pred_col] - exact.target_mid).abs() <= 0.1000001).mean()) if len(exact) else float("nan"),
    }


def main() -> None:
    target = load_targets()
    market = load_market()
    data = target.merge(market, on="date", how="inner", validate="one_to_one")

    train = data[data["date"].dt.year <= 2024].copy()
    test = data[data["date"].dt.year == 2025].copy()

    candidates = ["close", "log_close", "close_to_ma250", "drawdown_252", "rank_500"]
    metrics: list[dict[str, float | str]] = []

    for feature in candidates:
        tr = train.dropna(subset=[feature, "target_mid", "weight"]).copy()
        te = test.copy()
        if len(tr) < 100:
            continue

        a, b = weighted_linear_fit(tr[feature], tr.target_mid, tr.weight)
        pred_col = f"pred_linear_{feature}"
        data[pred_col] = a + b * data[feature]
        train[pred_col] = a + b * train[feature]
        test[pred_col] = a + b * test[feature]
        m = {"model": f"linear:{feature}", **score(test, pred_col)}
        m["slope"] = float(b)
        metrics.append(m)

        # Star should fall as market price/valuation rises. Only apply a decreasing
        # isotonic model when the candidate itself has that economic direction.
        if feature in {"close", "log_close", "close_to_ma250", "rank_500"}:
            xs, ys = pav_decreasing(tr[feature], tr.target_mid, tr.weight)
            ipred = f"pred_iso_{feature}"
            train[ipred] = train[feature].map(lambda v: interp_monotone(xs, ys, v) if pd.notna(v) else float("nan"))
            test[ipred] = test[feature].map(lambda v: interp_monotone(xs, ys, v) if pd.notna(v) else float("nan"))
            data[ipred] = data[feature].map(lambda v: interp_monotone(xs, ys, v) if pd.notna(v) else float("nan"))
            metrics.append({"model": f"isotonic:{feature}", **score(test, ipred)})

    metrics_df = pd.DataFrame(metrics).sort_values(["exact_mae", "interval_mae"])
    metrics_df.to_csv(DERIVED / "star_replica_v1_metrics.csv", index=False)

    keep = [
        "date", "star", "star_low", "star_high", "status", "target_mid", "weight",
        "close", "log_close", "close_to_ma250", "drawdown_252", "rank_500",
    ] + [c for c in data.columns if c.startswith("pred_")]
    data[keep].to_csv(DERIVED / "star_replica_v1_predictions.csv", index=False)

    print("\n2025 holdout metrics (trained on 2022-2024):")
    print(metrics_df.to_string(index=False))


if __name__ == "__main__":
    main()
