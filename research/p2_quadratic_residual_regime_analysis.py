from __future__ import annotations

import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED

PRED = DERIVED / "p2_nonlinear_price_curve_predictions.csv"
MONTHLY_OUTPUT = DERIVED / "p2_quadratic_residual_monthly.csv"
SUMMARY_OUTPUT = DERIVED / "p2_quadratic_residual_regime_summary.json"

PERIOD = "observed_2025_to_freeze"


def block(frame: pd.DataFrame) -> dict[str, float | int]:
    r = pd.to_numeric(frame["residual"], errors="coerce").dropna().to_numpy(dtype=float)
    return {
        "n": int(len(r)),
        "meanResidual": float(np.mean(r)),
        "medianResidual": float(np.median(r)),
        "sdResidual": float(np.std(r, ddof=1)),
        "meanAbsoluteResidual": float(np.mean(np.abs(r))),
        "maxAbsoluteResidual": float(np.max(np.abs(r))),
    }


def main() -> None:
    pred = pd.read_csv(PRED)
    pred["date"] = pd.to_datetime(pred["date"]).dt.normalize()
    pred = pred[pred["period"].eq(PERIOD) & pred["degree"].isin([1, 2])].copy()
    pred["residual"] = pd.to_numeric(pred["target"], errors="coerce") - pd.to_numeric(
        pred["prediction"], errors="coerce"
    )
    pred["month"] = pred["date"].dt.to_period("M").astype(str)

    monthly = (
        pred.groupby(["degree", "month"])
        .agg(
            n=("residual", "size"),
            meanResidual=("residual", "mean"),
            medianResidual=("residual", "median"),
            sdResidual=("residual", "std"),
            meanAbsoluteResidual=("residual", lambda s: s.abs().mean()),
        )
        .reset_index()
    )

    linear = pred[pred["degree"].eq(1)]
    quadratic = pred[pred["degree"].eq(2)]
    linear_stats = block(linear)
    quadratic_stats = block(quadratic)

    linear_month_sd = float(
        monthly.loc[monthly["degree"].eq(1), "meanResidual"].std(ddof=1)
    )
    quad_month_sd = float(
        monthly.loc[monthly["degree"].eq(2), "meanResidual"].std(ddof=1)
    )

    # How much of the apparent medium-horizon bias disappears simply by allowing curvature?
    mean_abs_reduction = 1.0 - (
        quadratic_stats["meanAbsoluteResidual"] / linear_stats["meanAbsoluteResidual"]
    )
    sd_reduction = 1.0 - quadratic_stats["sdResidual"] / linear_stats["sdResidual"]
    monthly_mean_sd_reduction = 1.0 - quad_month_sd / linear_month_sd

    # Residual dependence on star level after the curvature correction.
    star_rows = []
    for degree, group in pred.groupby("degree"):
        for star, current in group.groupby("target"):
            if len(current) < 4:
                continue
            star_rows.append({
                "degree": int(degree),
                "star": float(star),
                "n": int(len(current)),
                "meanResidual": float(current["residual"].mean()),
            })
    star_summary = pd.DataFrame(star_rows)
    star_bias = {}
    for degree in (1, 2):
        current = star_summary[star_summary["degree"].eq(degree)]
        if current.empty:
            continue
        star_bias[f"degree{degree}"] = {
            "maxAbsoluteStarMeanResidual": float(current["meanResidual"].abs().max()),
            "starMeanResidualRange": float(
                current["meanResidual"].max() - current["meanResidual"].min()
            ),
        }

    summary = {
        "purpose": (
            "Quantify how much of the apparent 2025-2026 anchor drift disappears when "
            "the log-price-to-star mapping is allowed to be quadratic rather than linear."
        ),
        "period": "2025-01-01 through 2026-08-31, descriptive only",
        "linear": linear_stats,
        "quadratic": quadratic_stats,
        "monthlyMeanResidualSd": {
            "linear": linear_month_sd,
            "quadratic": quad_month_sd,
        },
        "reductionFromCurvature": {
            "meanAbsoluteResidualFraction": float(mean_abs_reduction),
            "residualSdFraction": float(sd_reduction),
            "monthlyMeanResidualSdFraction": float(monthly_mean_sd_reduction),
        },
        "residualByStar": star_bias,
        "interpretation": (
            "Large reductions mean part of the previously inferred dynamic anchor/regime "
            "behavior was functional-form misspecification. Any remaining residual shift may "
            "still reflect publication thresholds, true anchor changes, omitted disclosed "
            "factors, or proxy mismatch."
        ),
        "predictionPolicy": (
            "This diagnostic does not alter any existing frozen model. The quadratic challenger "
            "has a separate frozen specification and requires future dates strictly after "
            "2026-10-09 for clean confirmation."
        ),
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(MONTHLY_OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
