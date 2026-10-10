from __future__ import annotations

import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, REPO

PANEL = REPO / "data" / "features" / "star_model_panel_2022_2026.csv"
TARGET = DERIVED / "star_target_2022_2026_unified.csv"

MONTHLY_OUTPUT = DERIVED / "p2_earnings_timescale_monthly.csv"
SUMMARY_OUTPUT = DERIVED / "p2_earnings_timescale_summary.json"

FROZEN_K = 4.127707783337646


def load_panel() -> pd.DataFrame:
    raw = pd.read_csv(PANEL, low_memory=False)
    raw["stockCode"] = (
        raw["stockCode"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    raw["date"] = pd.to_datetime(raw["date"]).dt.normalize()

    a = raw.loc[raw["stockCode"].eq("1000002"), ["date", "cp"]].copy()
    csi = raw.loc[
        raw["stockCode"].eq("000985"),
        ["date", "pe_ttm.mcw"],
    ].rename(columns={"pe_ttm.mcw": "pe"})

    target = pd.read_csv(TARGET)
    target["date"] = pd.to_datetime(target["date"]).dt.normalize()
    target = target[["date", "target_mid", "status", "training_weight"]]

    out = a.merge(csi, on="date", how="left", validate="one_to_one")
    out = out.merge(target, on="date", how="inner", validate="one_to_one")
    out["star"] = pd.to_numeric(out["target_mid"], errors="coerce")
    out["weight"] = pd.to_numeric(out["training_weight"], errors="coerce").fillna(1.0)
    out["price"] = pd.to_numeric(out["cp"], errors="coerce")
    out["pe"] = pd.to_numeric(out["pe"], errors="coerce")
    out["log_price"] = np.log(out["price"].where(out["price"] > 0))
    out["log_earnings_level"] = np.log(
        (out["price"] / out["pe"]).where((out["price"] > 0) & (out["pe"] > 0))
    )
    out["year"] = out["date"].dt.year
    out["month"] = out["date"].dt.to_period("M").astype(str)

    return out[
        out["status"].eq("exact")
        & out["star"].notna()
        & out["log_price"].notna()
        & out["log_earnings_level"].notna()
        & out["date"].ge(pd.Timestamp("2022-05-31"))
    ].sort_values("date").reset_index(drop=True)


def within_month_slope(frame: pd.DataFrame) -> float:
    pieces = []
    for _, g in frame.groupby("month"):
        if len(g) < 2:
            continue
        w = g["weight"].to_numpy(dtype=float)
        x = g["log_price"].to_numpy(dtype=float)
        y = g["star"].to_numpy(dtype=float)
        xbar = float(np.average(x, weights=w))
        ybar = float(np.average(y, weights=w))
        pieces.append((x - xbar, y - ybar, w))
    dx = np.concatenate([p[0] for p in pieces])
    dy = np.concatenate([p[1] for p in pieces])
    w = np.concatenate([p[2] for p in pieces])
    return float(np.sum(w * dx * dy) / np.sum(w * dx * dx))


def monthly(frame: pd.DataFrame, k: float, label: str) -> pd.DataFrame:
    rows = []
    for month, g in frame.groupby("month"):
        w = g["weight"].to_numpy(dtype=float)
        star = g["star"].to_numpy(dtype=float)
        lp = g["log_price"].to_numpy(dtype=float)
        le = g["log_earnings_level"].to_numpy(dtype=float)
        anchor_daily = star + k * lp
        rows.append(
            {
                "month": month,
                "slope_label": label,
                "k": k,
                "year": int(pd.to_datetime(g["date"]).dt.year.iloc[0]),
                "n": int(len(g)),
                "anchor": float(np.average(anchor_daily, weights=w)),
                "log_earnings_level": float(np.average(le, weights=w)),
            }
        )
    out = pd.DataFrame(rows).sort_values("month").reset_index(drop=True)
    out["earnings_adjusted_anchor"] = out["anchor"] - k * out["log_earnings_level"]
    out["anchor_change"] = out["anchor"].diff()
    out["earnings_change"] = out["log_earnings_level"].diff()
    out["adjusted_anchor_change"] = out["earnings_adjusted_anchor"].diff()
    return out


def block(frame: pd.DataFrame) -> dict[str, object]:
    anchor = frame["anchor"].to_numpy(dtype=float)
    adjusted = frame["earnings_adjusted_anchor"].to_numpy(dtype=float)
    loge = frame["log_earnings_level"].to_numpy(dtype=float)

    anchor_sd = float(np.std(anchor, ddof=1)) if len(anchor) > 1 else float("nan")
    adjusted_sd = float(np.std(adjusted, ddof=1)) if len(adjusted) > 1 else float("nan")
    level_corr = (
        float(np.corrcoef(anchor, loge)[0, 1])
        if len(anchor) > 2 and np.std(anchor) > 0 and np.std(loge) > 0
        else float("nan")
    )

    changes = frame[["anchor_change", "earnings_change"]].dropna()
    change_corr = (
        float(changes["anchor_change"].corr(changes["earnings_change"]))
        if len(changes) > 2
        else float("nan")
    )
    return {
        "months": int(len(frame)),
        "anchorSd": anchor_sd,
        "earningsAdjustedAnchorSd": adjusted_sd,
        "sdReductionFraction": (
            float(1.0 - adjusted_sd / anchor_sd)
            if np.isfinite(anchor_sd) and anchor_sd > 0 and np.isfinite(adjusted_sd)
            else None
        ),
        "anchorVsLogEarningsCorrelation": level_corr,
        "monthlyChangeCorrelation": change_corr,
        "anchorRange": float(np.max(anchor) - np.min(anchor)) if len(anchor) else None,
        "adjustedAnchorRange": (
            float(np.max(adjusted) - np.min(adjusted)) if len(adjusted) else None
        ),
    }


def main() -> None:
    panel = load_panel()
    pre = panel[panel["year"] <= 2024].copy()
    observed = panel[panel["year"] >= 2025].copy()

    fe_slope = within_month_slope(pre)
    k_fe = abs(fe_slope)

    all_monthly = []
    summaries = {}
    for label, k in (("frozen_price_slope", FROZEN_K), ("within_month_preholdout_slope", k_fe)):
        m = monthly(panel, k, label)
        all_monthly.append(m)
        summaries[label] = {
            "k": float(k),
            "preHoldout2022_06_2024": block(m[m["year"] <= 2024]),
            "observed2025_toFreeze": block(
                m[(m["year"] >= 2025) & (m["month"] <= "2026-08")]
            ),
        }

    monthly_all = pd.concat(all_monthly, ignore_index=True)

    summary = {
        "hypothesis": (
            "If the slow star anchor moves mainly with aggregate earnings level, then "
            "anchor_t - k*log(earnings_level_t) should be more stable than anchor_t, "
            "where anchor_t = star_t + k*log(price_t)."
        ),
        "earningsLevelDefinition": "A股全指 close / 中证全指 000985 pe_ttm.mcw",
        "noFittedEarningsWeight": True,
        "withinMonthPreHoldoutSlope": float(fe_slope),
        "slopeVariants": summaries,
        "interpretationRule": (
            "A large positive SD reduction supports earnings level as a slow anchor driver. "
            "Zero/negative reduction means the PE-derived earnings level does not explain "
            "the observed anchor variation under that fixed price slope."
        ),
        "cleanConfirmationRule": (
            "This is a mechanism diagnostic proposed after the first Sep-Oct 2026 future "
            "window; it is not eligible for clean prospective confirmation before dates "
            "strictly after 2026-10-09."
        ),
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    monthly_all.to_csv(MONTHLY_OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
