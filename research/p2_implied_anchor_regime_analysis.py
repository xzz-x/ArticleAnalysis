from __future__ import annotations

import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, fit_linear, prepare_panel

PROSPECTIVE_TARGET = DERIVED.parent / "verified" / "star_target_prospective_2026_09_onward.csv"
PROSPECTIVE_PRICE = DERIVED.parent / "verified" / "csi_all_share_prospective_2026_08_31_2026_10_09.csv"

SERIES_OUTPUT = DERIVED / "p2_implied_anchor_series.csv"
PERIOD_OUTPUT = DERIVED / "p2_implied_anchor_period_summary.csv"
SUMMARY_OUTPUT = DERIVED / "p2_implied_anchor_regime_summary.json"


def build_prospective() -> pd.DataFrame:
    price = pd.read_csv(PROSPECTIVE_PRICE)
    target = pd.read_csv(PROSPECTIVE_TARGET)
    price["date"] = pd.to_datetime(price["date"]).dt.normalize()
    target["date"] = pd.to_datetime(target["date"]).dt.normalize()
    out = price.merge(
        target[["date", "star", "status"]],
        on="date",
        how="inner",
        validate="one_to_one",
    ).sort_values("date")
    out["target_status"] = out["status"]
    out["target_target_mid"] = pd.to_numeric(out["star"], errors="coerce")
    out["log_close"] = np.log(pd.to_numeric(out["cp"], errors="coerce"))
    return out[["date", "cp", "log_close", "target_status", "target_target_mid"]].copy()


def exact_anchor_series(
    frame: pd.DataFrame,
    intercept: float,
    slope: float,
    source_period: str,
) -> pd.DataFrame:
    out = frame[
        frame["target_status"].eq("exact")
        & pd.to_numeric(frame["target_target_mid"], errors="coerce").notna()
        & pd.to_numeric(frame["log_close"], errors="coerce").notna()
    ][["date", "cp", "log_close", "target_target_mid"]].copy()
    out = out.sort_values("date").reset_index(drop=True)
    out["implied_anchor"] = (
        pd.to_numeric(out["target_target_mid"], errors="coerce")
        - slope * pd.to_numeric(out["log_close"], errors="coerce")
    )
    out["anchor_deviation"] = out["implied_anchor"] - intercept
    latent = intercept + slope * pd.to_numeric(out["log_close"], errors="coerce")
    out["static_latent"] = latent
    out["static_round"] = np.round(latent / 0.1) * 0.1
    out["static_round_error"] = (
        out["static_round"] - pd.to_numeric(out["target_target_mid"], errors="coerce")
    ).abs()
    out["source_period"] = source_period
    return out


def rolling_features(series: pd.DataFrame) -> pd.DataFrame:
    out = series.sort_values("date").copy()
    for window in (10, 20, 60):
        out[f"anchor_roll{window}_mean"] = out["implied_anchor"].rolling(window).mean()
        out[f"anchor_roll{window}_deviation"] = (
            out[f"anchor_roll{window}_mean"] - out["static_intercept"]
        )
    return out


def summarize_group(group: pd.DataFrame, label: str, value: str) -> dict[str, object]:
    x = pd.to_numeric(group["anchor_deviation"], errors="coerce").dropna().to_numpy(dtype=float)
    err = pd.to_numeric(group["static_round_error"], errors="coerce").dropna().to_numpy(dtype=float)
    dates = pd.to_datetime(group["date"])
    if len(x) == 0:
        return {}
    return {
        "period_type": label,
        "period": value,
        "start": dates.min().strftime("%Y-%m-%d"),
        "end": dates.max().strftime("%Y-%m-%d"),
        "n": int(len(x)),
        "mean_anchor_deviation": float(np.mean(x)),
        "median_anchor_deviation": float(np.median(x)),
        "sd_anchor_deviation": float(np.std(x, ddof=1)) if len(x) > 1 else 0.0,
        "q25_anchor_deviation": float(np.quantile(x, 0.25)),
        "q75_anchor_deviation": float(np.quantile(x, 0.75)),
        "static_round_mae": float(np.mean(err)),
        "static_round_exact_match": float(np.mean(err <= 1e-8)),
    }


def period_summary(series: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    for year, group in series.groupby(series["date"].dt.year):
        rows.append(summarize_group(group, "year", str(int(year))))

    quarter = series["date"].dt.to_period("Q").astype(str)
    for key, group in series.groupby(quarter):
        rows.append(summarize_group(group, "quarter", str(key)))

    month = series["date"].dt.to_period("M").astype(str)
    recent = series[series["date"] >= pd.Timestamp("2025-01-01")].copy()
    recent_month = recent["date"].dt.to_period("M").astype(str)
    for key, group in recent.groupby(recent_month):
        rows.append(summarize_group(group, "month", str(key)))

    return pd.DataFrame([row for row in rows if row])


def linear_time_drift(group: pd.DataFrame) -> dict[str, float | int]:
    use = group.dropna(subset=["anchor_deviation"]).sort_values("date")
    if len(use) < 2:
        return {"n": int(len(use)), "slope_per_100_trading_observations": float("nan")}
    x = np.arange(len(use), dtype=float)
    y = use["anchor_deviation"].to_numpy(dtype=float)
    slope = np.polyfit(x, y, 1)[0]
    return {
        "n": int(len(use)),
        "slope_per_100_trading_observations": float(slope * 100.0),
    }


def main() -> None:
    panel = prepare_panel()
    train = panel[panel["year"] <= 2024].copy()
    fit = fit_linear(train, ["log_close"])
    intercept = float(fit[0])
    slope = float(fit[1][0])

    historical = exact_anchor_series(
        panel[panel["date"] <= pd.Timestamp("2026-08-31")].copy(),
        intercept,
        slope,
        "historical_through_freeze",
    )
    prospective = exact_anchor_series(
        build_prospective(),
        intercept,
        slope,
        "first_genuine_prospective",
    )

    combined = pd.concat([historical, prospective], ignore_index=True).sort_values("date")
    combined["static_intercept"] = intercept
    combined = rolling_features(combined)

    periods = period_summary(combined)

    pre = combined[combined["date"] <= pd.Timestamp("2024-12-31")]
    observed = combined[
        (combined["date"] >= pd.Timestamp("2025-01-01"))
        & (combined["date"] <= pd.Timestamp("2026-08-31"))
    ]
    future = combined[combined["date"] >= pd.Timestamp("2026-09-01")]

    def block(group: pd.DataFrame) -> dict[str, object]:
        dev = group["anchor_deviation"].to_numpy(dtype=float)
        round_err = group["static_round_error"].to_numpy(dtype=float)
        roll10 = group["anchor_roll10_deviation"].dropna().to_numpy(dtype=float)
        return {
            "n": int(len(group)),
            "meanAnchorDeviation": float(np.mean(dev)) if len(dev) else None,
            "medianAnchorDeviation": float(np.median(dev)) if len(dev) else None,
            "sdAnchorDeviation": float(np.std(dev, ddof=1)) if len(dev) > 1 else None,
            "meanAbsoluteAnchorDeviation": float(np.mean(np.abs(dev))) if len(dev) else None,
            "staticRoundMae": float(np.mean(round_err)) if len(round_err) else None,
            "staticRoundExactMatch": float(np.mean(round_err <= 1e-8)) if len(round_err) else None,
            "rolling10MeanDeviation": float(np.mean(roll10)) if len(roll10) else None,
            "rolling10MinDeviation": float(np.min(roll10)) if len(roll10) else None,
            "rolling10MaxDeviation": float(np.max(roll10)) if len(roll10) else None,
            "timeDrift": linear_time_drift(group),
        }

    # Identify large, persistent departures of the 10-observation implied anchor
    # from the static intercept. This is descriptive only; no threshold is tuned.
    valid_roll = combined.dropna(subset=["anchor_roll10_deviation"]).copy()
    largest_roll = valid_roll.reindex(
        valid_roll["anchor_roll10_deviation"].abs().sort_values(ascending=False).index
    ).head(20)

    summary = {
        "staticFit": {
            "intercept": intercept,
            "slope": slope,
            "fitPeriod": "2022-01-01..2024-12-31",
        },
        "interpretationRule": (
            "Under a pure static-rounding mechanism, implied-anchor variation is "
            "primarily quantization residual around the fixed intercept. Persistent "
            "rolling mean departures or period-level shifts support anchor drift; "
            "reversion toward zero supports a stable static anchor."
        ),
        "preHoldout2022_2024": block(pre),
        "observed2025_toFreeze": block(observed),
        "firstProspective2026_09_10": block(future),
        "largestAbsoluteRolling10Departures": [
            {
                "date": row.date.strftime("%Y-%m-%d"),
                "targetStar": float(row.target_target_mid),
                "anchorRoll10Deviation": float(row.anchor_roll10_deviation),
                "staticRoundError": float(row.static_round_error),
            }
            for row in largest_roll.itertuples(index=False)
        ],
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    combined.to_csv(SERIES_OUTPUT, index=False, encoding="utf-8-sig")
    periods.to_csv(PERIOD_OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
