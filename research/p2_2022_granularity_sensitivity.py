from __future__ import annotations

import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, fit_linear, prepare_panel

PROSPECTIVE_TARGET = DERIVED.parent / "verified" / "star_target_prospective_2026_09_onward.csv"
PROSPECTIVE_PRICE = DERIVED.parent / "verified" / "csi_all_share_prospective_2026_08_31_2026_10_09.csv"

ROWS_OUTPUT = DERIVED / "p2_2022_granularity_sensitivity_rows.csv"
SUMMARY_OUTPUT = DERIVED / "p2_2022_granularity_sensitivity_summary.json"


def coarse_bucket_mask(panel: pd.DataFrame) -> pd.Series:
    date = pd.to_datetime(panel["date"])
    mid = pd.to_numeric(panel["target_target_mid"], errors="coerce")
    # Evidence audit: before 2022-05-31, articles commonly used coarse half-star
    # buckets ("4星级", "4.5星级", "5星级"). 2022-04-07 explicitly says
    # "4.5星级；如果细一些计算，目前算是4.8", proving the two granularities
    # were not equivalent. 2022-05-31 is the transition marker "走出5星级，
    # 现在算是4.9星级"; June onward uses 0.1-star values consistently.
    half_grid = np.isclose((mid * 2) % 1, 0.0, atol=1e-8)
    return (
        date.between(pd.Timestamp("2022-01-01"), pd.Timestamp("2022-05-30"))
        & panel["target_status"].eq("exact")
        & mid.notna()
        & half_grid
    )


def corrected_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = prepare_panel().copy()
    coarse = coarse_bucket_mask(panel)
    audit = panel.loc[
        coarse,
        [
            "date",
            "target_target_mid",
            "target_status",
            "target_training_weight",
            "target_evidence",
            "target_evidence_method",
            "target_source_priority",
        ],
    ].copy()
    audit["coarse_low"] = pd.to_numeric(audit["target_target_mid"], errors="coerce")
    audit["coarse_high"] = audit["coarse_low"] + 0.5
    audit["sensitivity_action"] = "exclude_from_point_fit_keep_as_half_star_bucket_evidence"

    # Do not invent a precise midpoint.  The sensitivity fit simply excludes
    # these coarse labels from point regression.
    panel.loc[coarse, "target_training_weight"] = 0.0
    panel.loc[coarse, "granularity_sensitivity_status"] = "coarse_half_star_bucket"
    panel.loc[~coarse, "granularity_sensitivity_status"] = "unchanged"
    return panel, audit


def fit_price(train: pd.DataFrame) -> tuple[float, float]:
    fit = fit_linear(train, ["log_close"])
    return float(fit[0]), float(fit[1][0])


def predictions(frame: pd.DataFrame, fit: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    intercept, slope = fit
    latent = intercept + slope * pd.to_numeric(frame["log_close"], errors="coerce").to_numpy(dtype=float)
    rounded = np.round(latent / 0.1) * 0.1
    return latent, rounded


def exact_score(frame: pd.DataFrame, pred: np.ndarray) -> dict[str, float | int]:
    actual = pd.to_numeric(frame["target_target_mid"], errors="coerce").to_numpy(dtype=float)
    exact = (
        frame["target_status"].eq("exact").to_numpy()
        & np.isfinite(actual)
        & (pd.to_numeric(frame["target_training_weight"], errors="coerce").to_numpy(dtype=float) > 0)
        & np.isfinite(pred)
    )
    error = np.abs(np.asarray(pred, dtype=float)[exact] - actual[exact])
    return {
        "n": int(exact.sum()),
        "mae": float(error.mean()) if len(error) else float("nan"),
        "rmse": float(np.sqrt(np.mean(error**2))) if len(error) else float("nan"),
        "exactMatch": float((error <= 1e-8).mean()) if len(error) else float("nan"),
        "within0_1": float((error <= 0.1000001).mean()) if len(error) else float("nan"),
    }


def expanding_cv(panel: pd.DataFrame) -> dict[str, object]:
    rows = []
    for train_end, test_year in ((2022, 2023), (2023, 2024)):
        train = panel[panel["year"] <= train_end].copy()
        test = panel[panel["year"] == test_year].copy()
        fit = fit_price(train)
        latent, rounded = predictions(test, fit)
        rows.append(
            {
                "trainEnd": train_end,
                "testYear": test_year,
                "intercept": fit[0],
                "slope": fit[1],
                "continuous": exact_score(test, latent),
                "nearestRound": exact_score(test, rounded),
            }
        )
    return {
        "folds": rows,
        "meanContinuousMae": float(np.mean([x["continuous"]["mae"] for x in rows])),
        "meanNearestRoundMae": float(np.mean([x["nearestRound"]["mae"] for x in rows])),
    }


def build_prospective() -> pd.DataFrame:
    price = pd.read_csv(PROSPECTIVE_PRICE)
    target = pd.read_csv(PROSPECTIVE_TARGET)
    price["date"] = pd.to_datetime(price["date"]).dt.normalize()
    target["date"] = pd.to_datetime(target["date"]).dt.normalize()
    out = price.merge(target[["date", "star", "status"]], on="date", how="inner", validate="one_to_one")
    out["log_close"] = np.log(pd.to_numeric(out["cp"], errors="coerce"))
    out["target_target_mid"] = pd.to_numeric(out["star"], errors="coerce")
    out["target_status"] = out["status"]
    out["target_training_weight"] = 1.0
    return out.sort_values("date")


def main() -> None:
    original = prepare_panel()
    corrected, audit = corrected_panel()

    original_train = original[original["year"] <= 2024].copy()
    corrected_train = corrected[corrected["year"] <= 2024].copy()
    original_fit = fit_price(original_train)
    corrected_fit = fit_price(corrected_train)

    original_cv = expanding_cv(original)
    corrected_cv = expanding_cv(corrected)

    holdout_original = original[original["year"] >= 2025].copy()
    holdout_corrected = corrected[corrected["year"] >= 2025].copy()
    _, original_hold_round = predictions(holdout_original, original_fit)
    corrected_hold_latent, corrected_hold_round = predictions(holdout_corrected, corrected_fit)

    prospective = build_prospective()
    corrected_future_latent, corrected_future_round = predictions(prospective, corrected_fit)

    audit["date"] = pd.to_datetime(audit["date"]).dt.strftime("%Y-%m-%d")
    audit.to_csv(ROWS_OUTPUT, index=False, encoding="utf-8-sig")

    summary = {
        "researchStatus": "sensitivity_only_no_canonical_target_mutation",
        "granularityEvidence": [
            "Before 2022-05-31, integer/half-star language often represented a coarse bucket.",
            "2022-04-07 explicitly states: still 4.5-star, but finer calculation is 4.8.",
            "2022-05-31 states: moved out of 5-star, now counts as 4.9; June onward consistently uses 0.1-star precision.",
        ],
        "coarseRowsExcludedFromPointFit": int(len(audit)),
        "coarseDateMin": audit["date"].min() if len(audit) else None,
        "coarseDateMax": audit["date"].max() if len(audit) else None,
        "originalStaticFit": {
            "intercept": original_fit[0],
            "slope": original_fit[1],
        },
        "granularityCorrectedStaticFit": {
            "intercept": corrected_fit[0],
            "slope": corrected_fit[1],
        },
        "originalPreHoldoutCv": original_cv,
        "granularityCorrectedPreHoldoutCv": corrected_cv,
        "observed2025_2026UsingCorrectedFit": {
            "continuous": exact_score(holdout_corrected, corrected_hold_latent),
            "nearestRound": exact_score(holdout_corrected, corrected_hold_round),
            "originalNearestRoundForReference": exact_score(holdout_original, original_hold_round),
        },
        "firstProspectiveWindowPostHocDiagnostic": {
            "continuous": exact_score(prospective, corrected_future_latent),
            "nearestRound": exact_score(prospective, corrected_future_round),
            "warning": "Future window was already inspected; this is diagnostic only and cannot confirm the corrected model.",
        },
    }

    SUMMARY_OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
