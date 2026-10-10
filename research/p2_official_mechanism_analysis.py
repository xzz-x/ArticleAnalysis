from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import (
    DERIVED,
    fit_linear,
    prepare_panel,
)

SLOPE = -4.127707783337646

OFFICIAL_FACTOR_MAP = {
    "buffett_mc_to_gdp": "buffett_indicator",
    "buffett_mc_om_to_gdp": "buffett_indicator_alt",
    "equity_bond_ratio_avg": "equity_bond_ratio",
    "pb_avg_pct_10y_local": "pb_percentile",
    "fin_q_ps_np_ttm_y2y": "earnings_growth",
    "ta_pct_252": "trading_amount_percentile",
    "to_r_pct_252": "turnover_percentile",
    "market_financing_balance_change_20": "margin_financing_20d",
    "market_financing_balance_change_60": "margin_financing_60d",
    "investor_nni_w": "investor_sentiment_weekly",
    "investor_nni_m": "investor_sentiment_monthly",
}

DETAIL_OUTPUT = DERIVED / "p2_anchor_official_factor_correlations.csv"
YEAR_OUTPUT = DERIVED / "p2_anchor_yearly_summary.csv"
SUMMARY_OUTPUT = DERIVED / "p2_anchor_official_factor_summary.json"


def corr_row(frame: pd.DataFrame, column: str) -> dict[str, object] | None:
    use = frame[["implied_anchor", "static_residual", column]].dropna()
    if len(use) < 20:
        return None
    return {
        "column": column,
        "official_role": OFFICIAL_FACTOR_MAP[column],
        "n": int(len(use)),
        "anchor_pearson": float(use["implied_anchor"].corr(use[column], method="pearson")),
        "anchor_spearman": float(use["implied_anchor"].corr(use[column], method="spearman")),
        "residual_pearson": float(use["static_residual"].corr(use[column], method="pearson")),
        "residual_spearman": float(use["static_residual"].corr(use[column], method="spearman")),
    }


def standardized_ols_r2(frame: pd.DataFrame, columns: list[str]) -> dict[str, object] | None:
    use = frame[["implied_anchor", *columns]].dropna().copy()
    if len(use) < max(40, 8 * len(columns)):
        return None

    x = use[columns].astype(float)
    std = x.std(ddof=0).replace(0, np.nan)
    x = (x - x.mean()) / std
    valid_cols = [col for col in columns if x[col].notna().all()]
    if not valid_cols:
        return None

    y = use["implied_anchor"].to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(use)), x[valid_cols].to_numpy(dtype=float)])
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    pred = design @ beta
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {
        "n": int(len(use)),
        "columns": valid_cols,
        "r2": float(r2),
        "standardized_coefficients": {
            col: float(value)
            for col, value in zip(valid_cols, beta[1:])
        },
    }


def official_same_star_examples() -> list[dict[str, object]]:
    # Public Bank Screw course examples. These are approximate historical
    # illustrations, not exact daily targets and must never enter training.
    examples = [
        (2013, 2700.0, 5.0),
        (2018, 3400.0, 5.0),
        (2024, 4800.0, 5.0),
    ]
    rows = []
    for year, price, star in examples:
        implied_anchor = star - SLOPE * np.log(price)
        rows.append(
            {
                "year": year,
                "approx_csi_all_share_level": price,
                "illustrative_star": star,
                "implied_anchor_under_frozen_slope": float(implied_anchor),
                "training_evidence": False,
            }
        )
    return rows


def main() -> None:
    panel = prepare_panel()
    development = panel[
        (panel["year"] <= 2024)
        & panel["target_status"].eq("exact")
        & pd.to_numeric(panel["target_target_mid"], errors="coerce").notna()
        & pd.to_numeric(panel["log_close"], errors="coerce").notna()
    ].copy()

    # Fit only the development-period static intercept. Keep the already-frozen
    # price slope conceptually separate from the explanatory factor analysis.
    static_fit = fit_linear(development, ["log_close"])
    intercept = float(static_fit[0])
    slope = float(static_fit[1][0])
    if abs(slope - SLOPE) > 1e-10:
        raise RuntimeError(f"development slope changed: {slope} vs frozen {SLOPE}")

    development["implied_anchor"] = (
        pd.to_numeric(development["target_target_mid"], errors="coerce")
        - SLOPE * pd.to_numeric(development["log_close"], errors="coerce")
    )
    development["static_prediction"] = intercept + SLOPE * development["log_close"]
    development["static_residual"] = (
        development["target_target_mid"] - development["static_prediction"]
    )

    rows = []
    available = [col for col in OFFICIAL_FACTOR_MAP if col in development.columns]
    for column in available:
        row = corr_row(development, column)
        if row is not None:
            rows.append(row)
    correlations = pd.DataFrame(rows).sort_values(
        "anchor_spearman", key=lambda s: s.abs(), ascending=False
    )

    yearly = (
        development.assign(year=development["date"].dt.year)
        .groupby("year")
        .agg(
            n=("implied_anchor", "size"),
            median_implied_anchor=("implied_anchor", "median"),
            mean_implied_anchor=("implied_anchor", "mean"),
            median_static_residual=("static_residual", "median"),
            mean_static_residual=("static_residual", "mean"),
        )
        .reset_index()
    )

    official_quant = [
        col for col in (
            "buffett_mc_to_gdp",
            "equity_bond_ratio_avg",
            "pb_avg_pct_10y_local",
        )
        if col in development.columns
    ]
    official_extended = [
        col for col in (
            *official_quant,
            "fin_q_ps_np_ttm_y2y",
            "ta_pct_252",
            "to_r_pct_252",
            "market_financing_balance_change_20",
            "market_financing_balance_change_60",
            "investor_nni_w",
            "investor_nni_m",
        )
        if col in development.columns
    ]

    examples = official_same_star_examples()
    example_shift = (
        examples[-1]["implied_anchor_under_frozen_slope"]
        - examples[0]["implied_anchor_under_frozen_slope"]
    )

    summary = {
        "purpose": (
            "Mechanism explanation only. Uses 2022-2024 exact targets and does not "
            "retune any prospective prediction model."
        ),
        "developmentRows": int(len(development)),
        "staticIntercept": intercept,
        "frozenSlope": SLOPE,
        "officialFactorColumnsAvailable": available,
        "officialQuantitativeModel": standardized_ols_r2(development, official_quant)
            if official_quant else None,
        "officialExtendedModel": standardized_ols_r2(development, official_extended)
            if official_extended else None,
        "officialSameStarExamples": examples,
        "illustrativeAnchorShift2013To2024": float(example_shift),
        "sameStarInterpretation": (
            "Bank Screw's public examples place roughly the same 5-star state near "
            "CSI All Share 2700 in 2013, 3400 in 2018, and 4800 in 2024. Under a "
            "fixed log-price slope this implies a materially changing intercept, so "
            "a single static intercept cannot be a universal 2012-2026 production rule."
        ),
        "warning": (
            "The 2013/2018/2024 point levels are approximate public illustrations, "
            "not exact daily labels. They are mechanism evidence only and are never "
            "used for fitting or scoring."
        ),
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    correlations.to_csv(DETAIL_OUTPUT, index=False, encoding="utf-8-sig")
    yearly.to_csv(YEAR_OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
