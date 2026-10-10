from __future__ import annotations

import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, prepare_panel

PROSPECTIVE_TARGET = DERIVED.parent / "verified" / "star_target_prospective_2026_09_onward.csv"
PROSPECTIVE_PRICE = DERIVED.parent / "verified" / "csi_all_share_prospective_2026_08_31_2026_10_09.csv"

INTERVAL_OUTPUT = DERIVED / "p2_granularity_interval_training_rows.csv"
SUMMARY_OUTPUT = DERIVED / "p2_granularity_interval_model_summary.json"


def is_early_coarse_bucket(frame: pd.DataFrame) -> np.ndarray:
    date = pd.to_datetime(frame["date"])
    mid = pd.to_numeric(frame["target_target_mid"], errors="coerce")
    half_grid = np.isclose(np.mod(mid * 2.0, 1.0), 0.0, atol=1e-8)
    return (
        date.between(pd.Timestamp("2022-01-01"), pd.Timestamp("2022-05-30"))
        & frame["target_status"].eq("exact")
        & mid.notna()
        & half_grid
    ).to_numpy()


def make_training_intervals(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    mid = pd.to_numeric(out["target_target_mid"], errors="coerce").to_numpy(dtype=float)
    low = pd.to_numeric(out["target_star_low"], errors="coerce").to_numpy(dtype=float)
    high = pd.to_numeric(out["target_star_high"], errors="coerce").to_numpy(dtype=float)
    status = out["target_status"].astype(str).to_numpy()
    weight = pd.to_numeric(out["target_training_weight"], errors="coerce").fillna(0).to_numpy(dtype=float)

    coarse = is_early_coarse_bucket(out)
    train_low = np.full(len(out), np.nan)
    train_high = np.full(len(out), np.nan)
    granularity = np.full(len(out), "unusable", dtype=object)

    # Published fine exact decimal is treated as a rounded 0.1-star observation:
    # latent score may lie within +/-0.05 of the displayed value.
    fine_exact = (status == "exact") & np.isfinite(mid) & ~coarse
    train_low[fine_exact] = mid[fine_exact] - 0.05
    train_high[fine_exact] = mid[fine_exact] + 0.05
    granularity[fine_exact] = "fine_0.1_rounded_interval"

    # Before 2022-05-31, half-star/integer phrases were coarse buckets.  The
    # 2022-04-07 article explicitly says "still 4.5-star; finer calculation 4.8",
    # so a displayed 4.5 constrains the latent score to the 4.5..5.0 bucket.
    train_low[coarse] = mid[coarse]
    train_high[coarse] = mid[coarse] + 0.5
    granularity[coarse] = "coarse_0.5_bucket"

    range_mask = (status == "range") & np.isfinite(low) & np.isfinite(high)
    train_low[range_mask] = low[range_mask]
    train_high[range_mask] = high[range_mask]
    granularity[range_mask] = "explicit_range"

    # "x.x星上下" is less precise than an exact decimal. Give it a +/-0.1 band.
    approx = (status == "approx") & np.isfinite(mid)
    train_low[approx] = mid[approx] - 0.1
    train_high[approx] = mid[approx] + 0.1
    granularity[approx] = "approx_plus_minus_0.1"

    unusable = ~np.isfinite(train_low) | ~np.isfinite(train_high) | (weight <= 0)
    train_low[unusable] = np.nan
    train_high[unusable] = np.nan

    out["granularity_train_low"] = train_low
    out["granularity_train_high"] = train_high
    out["granularity_class"] = granularity
    out["granularity_weight"] = weight
    return out


def best_intercept_for_slope(
    x: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
    weights: np.ndarray,
    slope: float,
) -> float:
    lo_a = low - slope * x
    hi_a = high - slope * x
    left = float(np.min(lo_a) - 1.0)
    right = float(np.max(hi_a) + 1.0)

    # Weighted squared distance to intervals is convex in intercept.
    for _ in range(80):
        a = (left + right) / 2.0
        grad = np.sum(
            weights
            * np.where(
                a < lo_a,
                a - lo_a,
                np.where(a > hi_a, a - hi_a, 0.0),
            )
        )
        if grad < 0:
            left = a
        else:
            right = a
    return (left + right) / 2.0


def interval_objective(
    x: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
    weights: np.ndarray,
    intercept: float,
    slope: float,
) -> float:
    pred = intercept + slope * x
    distance = np.where(
        pred < low,
        low - pred,
        np.where(pred > high, pred - high, 0.0),
    )
    return float(np.average(distance**2, weights=weights))


def fit_interval_regression(frame: pd.DataFrame) -> tuple[float, float, float]:
    enriched = make_training_intervals(frame)
    use = enriched[
        enriched["granularity_train_low"].notna()
        & enriched["granularity_train_high"].notna()
        & pd.to_numeric(enriched["log_close"], errors="coerce").notna()
        & (pd.to_numeric(enriched["granularity_weight"], errors="coerce") > 0)
    ].copy()

    x = pd.to_numeric(use["log_close"], errors="coerce").to_numpy(dtype=float)
    low = pd.to_numeric(use["granularity_train_low"], errors="coerce").to_numpy(dtype=float)
    high = pd.to_numeric(use["granularity_train_high"], errors="coerce").to_numpy(dtype=float)
    weights = pd.to_numeric(use["granularity_weight"], errors="coerce").to_numpy(dtype=float)

    def profile(slope: float) -> tuple[float, float]:
        intercept = best_intercept_for_slope(x, low, high, weights, slope)
        loss = interval_objective(x, low, high, weights, intercept, slope)
        return loss, intercept

    # The profiled objective is convex. Golden-section search avoids adding a
    # scipy dependency and is deterministic in CI.
    left, right = -8.0, -1.0
    phi = (1.0 + np.sqrt(5.0)) / 2.0
    c = right - (right - left) / phi
    d = left + (right - left) / phi
    fc = profile(c)[0]
    fd = profile(d)[0]
    for _ in range(100):
        if fc <= fd:
            right, d, fd = d, c, fc
            c = right - (right - left) / phi
            fc = profile(c)[0]
        else:
            left, c, fc = c, d, fd
            d = left + (right - left) / phi
            fd = profile(d)[0]

    slope = (left + right) / 2.0
    loss, intercept = profile(slope)
    return float(intercept), float(slope), float(loss)


def predict(frame: pd.DataFrame, fit: tuple[float, float, float]) -> tuple[np.ndarray, np.ndarray]:
    intercept, slope, _ = fit
    x = pd.to_numeric(frame["log_close"], errors="coerce").to_numpy(dtype=float)
    latent = intercept + slope * x
    rounded = np.round(latent / 0.1) * 0.1
    return latent, rounded


def exact_score(frame: pd.DataFrame, pred: np.ndarray) -> dict[str, float | int]:
    actual = pd.to_numeric(frame["target_target_mid"], errors="coerce").to_numpy(dtype=float)
    exact = frame["target_status"].eq("exact").to_numpy() & np.isfinite(actual) & np.isfinite(pred)
    error = np.abs(np.asarray(pred, dtype=float)[exact] - actual[exact])
    return {
        "n": int(exact.sum()),
        "mae": float(error.mean()) if len(error) else float("nan"),
        "rmse": float(np.sqrt(np.mean(error**2))) if len(error) else float("nan"),
        "exactMatch": float((error <= 1e-8).mean()) if len(error) else float("nan"),
        "within0_1": float((error <= 0.1000001).mean()) if len(error) else float("nan"),
    }


def expanding_cv(panel: pd.DataFrame) -> dict[str, object]:
    folds = []
    for train_end, test_year in ((2022, 2023), (2023, 2024)):
        train = panel[panel["year"] <= train_end].copy()
        test = panel[panel["year"] == test_year].copy()
        fit = fit_interval_regression(train)
        latent, rounded = predict(test, fit)
        folds.append(
            {
                "trainEnd": train_end,
                "testYear": test_year,
                "fit": {"intercept": fit[0], "slope": fit[1], "intervalLoss": fit[2]},
                "continuous": exact_score(test, latent),
                "nearestRound": exact_score(test, rounded),
            }
        )
    return {
        "folds": folds,
        "meanContinuousMae": float(np.mean([x["continuous"]["mae"] for x in folds])),
        "meanNearestRoundMae": float(np.mean([x["nearestRound"]["mae"] for x in folds])),
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
    return out.sort_values("date")


def main() -> None:
    panel = prepare_panel()
    train = panel[panel["year"] <= 2024].copy()
    fit = fit_interval_regression(train)
    cv = expanding_cv(panel)

    enriched = make_training_intervals(train)
    audit = enriched[
        enriched["granularity_train_low"].notna()
    ][[
        "date",
        "target_target_mid",
        "target_status",
        "granularity_class",
        "granularity_train_low",
        "granularity_train_high",
        "granularity_weight",
        "target_evidence",
        "target_source_priority",
    ]].copy()
    audit.to_csv(INTERVAL_OUTPUT, index=False, encoding="utf-8-sig")

    holdout = panel[panel["year"] >= 2025].copy()
    hold_latent, hold_round = predict(holdout, fit)

    prospective = build_prospective()
    future_latent, future_round = predict(prospective, fit)

    granularity_counts = (
        audit["granularity_class"].value_counts(dropna=False).astype(int).to_dict()
    )

    summary = {
        "researchStatus": "interval_censored_sensitivity_no_canonical_target_mutation",
        "semanticBasis": {
            "coarseRule": "2022-01-01..2022-05-30 half-star/integer exact phrases are treated as [star, star+0.5] buckets",
            "fineRule": "fine 0.1-star exact publications constrain latent score to displayed star +/-0.05",
            "rangeRule": "explicit ranges remain their stated interval",
            "approxRule": "x.x-star approximately/up-down is treated as +/-0.1",
            "keyEvidence": "2022-04-07: still 4.5-star; if calculated more finely, currently 4.8",
        },
        "trainingGranularityCounts": granularity_counts,
        "finalFit2022_2024": {
            "intercept": fit[0],
            "slope": fit[1],
            "intervalSquaredLoss": fit[2],
        },
        "preHoldoutExpandingCv": cv,
        "observed2025_2026": {
            "continuous": exact_score(holdout, hold_latent),
            "nearestRound": exact_score(holdout, hold_round),
        },
        "firstProspectiveWindowPostHocDiagnostic": {
            "continuous": exact_score(prospective, future_latent),
            "nearestRound": exact_score(prospective, future_round),
            "warning": "Sep-Oct future targets were already inspected before this interval-censored model was proposed; diagnostic only.",
        },
    }

    SUMMARY_OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
