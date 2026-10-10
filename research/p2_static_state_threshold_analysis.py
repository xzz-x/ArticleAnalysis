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

PROSPECTIVE_TARGET = DERIVED.parent / "verified" / "star_target_prospective_2026_09_onward.csv"
PROSPECTIVE_PRICE = DERIVED.parent / "verified" / "csi_all_share_prospective_2026_08_31_2026_10_09.csv"

GRID_OUTPUT = DERIVED / "p2_static_state_threshold_grid.csv"
HOLDOUT_OUTPUT = DERIVED / "p2_static_state_threshold_holdout.csv"
PROSPECTIVE_OUTPUT = DERIVED / "p2_static_state_threshold_prospective.csv"
SUMMARY_OUTPUT = DERIVED / "p2_static_state_threshold_summary.json"


def score_exact(actual: np.ndarray, prediction: np.ndarray) -> dict[str, float | int]:
    actual = np.asarray(actual, dtype=float)
    prediction = np.asarray(prediction, dtype=float)
    mask = np.isfinite(actual) & np.isfinite(prediction)
    error = np.abs(prediction[mask] - actual[mask])
    return {
        "n": int(mask.sum()),
        "mae": float(error.mean()) if len(error) else float("nan"),
        "rmse": float(np.sqrt(np.mean(error**2))) if len(error) else float("nan"),
        "max_error": float(error.max()) if len(error) else float("nan"),
        "exact_match": float(np.isclose(prediction[mask], actual[mask], atol=1e-8).mean()) if len(error) else float("nan"),
        "within_0_1": float((error <= 0.1000001).mean()) if len(error) else float("nan"),
    }


def static_fit(train: pd.DataFrame) -> tuple[float, float]:
    fit = fit_linear(train, ["log_close"])
    return float(fit[0]), float(fit[1][0])


def latent(frame: pd.DataFrame, intercept: float, slope: float) -> np.ndarray:
    return intercept + slope * pd.to_numeric(frame["log_close"], errors="coerce").to_numpy(dtype=float)


def nearest_round(values: np.ndarray) -> np.ndarray:
    return np.round(np.asarray(values, dtype=float) / 0.1) * 0.1


def last_exact_state(train: pd.DataFrame) -> float:
    use = train[
        train["target_status"].eq("exact")
        & pd.to_numeric(train["target_target_mid"], errors="coerce").notna()
    ].sort_values("date")
    if use.empty:
        raise ValueError("no exact historical state")
    return float(use.iloc[-1]["target_target_mid"])


def one_step_static_state_rule(
    train: pd.DataFrame,
    test: pd.DataFrame,
    intercept: float,
    slope: float,
    threshold_up: float,
    threshold_down: float,
) -> np.ndarray:
    """Use static latent score + previous observed published state.

    Prediction for date t can use t price and only previously observed published
    stars. After t is predicted, the true t exact star may become the state for
    t+1. This is a one-step evaluation, not a free-running simulation.
    """
    state = last_exact_state(train)
    out: list[float] = []
    for row in test.sort_values("date").itertuples(index=False):
        log_close = float(row.log_close)
        value = intercept + slope * log_close if np.isfinite(log_close) else np.nan
        prediction = state
        if np.isfinite(value):
            delta = value - state
            if delta >= threshold_up or delta <= -threshold_down:
                prediction = float(np.round(value / 0.1) * 0.1)
        out.append(prediction)

        status = str(row.target_status)
        actual = float(row.target_target_mid) if pd.notna(row.target_target_mid) else np.nan
        if status == "exact" and np.isfinite(actual):
            state = actual
    return np.asarray(out, dtype=float)


def exact_arrays(frame: pd.DataFrame, prediction: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    actual = pd.to_numeric(frame["target_target_mid"], errors="coerce").to_numpy(dtype=float)
    exact = frame["target_status"].eq("exact").to_numpy() & np.isfinite(actual)
    return actual[exact], np.asarray(prediction, dtype=float)[exact]


def evaluate_fold(
    train: pd.DataFrame,
    test: pd.DataFrame,
    threshold_up: float,
    threshold_down: float,
) -> dict[str, float | int]:
    intercept, slope = static_fit(train)
    pred = one_step_static_state_rule(
        train, test, intercept, slope, threshold_up, threshold_down
    )
    actual, pred_exact = exact_arrays(test, pred)
    return score_exact(actual, pred_exact)


def preholdout_grid(panel: pd.DataFrame) -> pd.DataFrame:
    folds = ((2022, 2023), (2023, 2024))
    rows: list[dict[str, float]] = []
    thresholds = np.arange(0.02, 0.121, 0.005)

    for up in thresholds:
        for down in thresholds:
            fold_scores = []
            for train_end, test_year in folds:
                train = panel[panel["year"] <= train_end].copy()
                test = panel[panel["year"] == test_year].copy().sort_values("date")
                fold_scores.append(
                    evaluate_fold(
                        train,
                        test,
                        float(np.round(up, 3)),
                        float(np.round(down, 3)),
                    )
                )
            rows.append(
                {
                    "threshold_up": float(np.round(up, 3)),
                    "threshold_down": float(np.round(down, 3)),
                    "cv_mae": float(np.mean([x["mae"] for x in fold_scores])),
                    "cv_exact_match": float(np.mean([x["exact_match"] for x in fold_scores])),
                    "cv_within_0_1": float(np.mean([x["within_0_1"] for x in fold_scores])),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["cv_mae", "cv_exact_match"],
        ascending=[True, False],
        ignore_index=True,
    )


def nearest_round_cv(panel: pd.DataFrame) -> dict[str, float]:
    folds = ((2022, 2023), (2023, 2024))
    scores = []
    for train_end, test_year in folds:
        train = panel[panel["year"] <= train_end].copy()
        test = panel[panel["year"] == test_year].copy().sort_values("date")
        intercept, slope = static_fit(train)
        pred = nearest_round(latent(test, intercept, slope))
        actual, pred_exact = exact_arrays(test, pred)
        scores.append(score_exact(actual, pred_exact))
    return {
        "cv_mae": float(np.mean([x["mae"] for x in scores])),
        "cv_exact_match": float(np.mean([x["exact_match"] for x in scores])),
        "cv_within_0_1": float(np.mean([x["within_0_1"] for x in scores])),
    }


def build_prospective_frame() -> pd.DataFrame:
    price = pd.read_csv(PROSPECTIVE_PRICE)
    target = pd.read_csv(PROSPECTIVE_TARGET)
    price["date"] = pd.to_datetime(price["date"]).dt.normalize()
    target["date"] = pd.to_datetime(target["date"]).dt.normalize()
    future = price.merge(
        target[["date", "star", "status"]],
        on="date",
        how="inner",
        validate="one_to_one",
    ).sort_values("date")
    future["log_close"] = np.log(pd.to_numeric(future["cp"], errors="coerce"))
    future["target_status"] = future["status"]
    future["target_target_mid"] = pd.to_numeric(future["star"], errors="coerce")
    return future


def transition_gap_summary(
    frame: pd.DataFrame,
    intercept: float,
    slope: float,
    label: str,
) -> list[dict[str, object]]:
    exact = frame[
        frame["target_status"].eq("exact")
        & pd.to_numeric(frame["target_target_mid"], errors="coerce").notna()
    ].sort_values("date").copy()
    exact["latent"] = latent(exact, intercept, slope)
    exact["prev_star"] = exact["target_target_mid"].shift(1)
    exact["delta_star"] = exact["target_target_mid"] - exact["prev_star"]
    exact["gap_from_prev"] = exact["latent"] - exact["prev_star"]
    moves = exact[exact["delta_star"].abs().between(0.099999, 0.100001)].copy()

    rows = []
    for direction, group in moves.groupby(np.where(moves["delta_star"] > 0, "star_up", "star_down")):
        gaps = group["gap_from_prev"].to_numpy(dtype=float)
        trigger = gaps if direction == "star_up" else -gaps
        rows.append(
            {
                "period": label,
                "direction": str(direction),
                "n": int(len(trigger)),
                "median_trigger_gap": float(np.median(trigger)),
                "q25_trigger_gap": float(np.quantile(trigger, 0.25)),
                "q75_trigger_gap": float(np.quantile(trigger, 0.75)),
                "min_trigger_gap": float(np.min(trigger)),
                "max_trigger_gap": float(np.max(trigger)),
            }
        )
    return rows


def main() -> None:
    panel = prepare_panel()
    grid = preholdout_grid(panel)
    best = grid.iloc[0]
    round_cv = nearest_round_cv(panel)

    train = panel[panel["year"] <= 2024].copy()
    holdout = panel[panel["year"] >= 2025].copy().sort_values("date")
    intercept, slope = static_fit(train)

    holdout_state = one_step_static_state_rule(
        train,
        holdout,
        intercept,
        slope,
        float(best["threshold_up"]),
        float(best["threshold_down"]),
    )
    holdout_round = nearest_round(latent(holdout, intercept, slope))
    hold_actual, hold_state_exact = exact_arrays(holdout, holdout_state)
    _, hold_round_exact = exact_arrays(holdout, holdout_round)

    prospective = build_prospective_frame()
    # Seed the prospective one-step state rule with the historical panel through
    # 2026-08-31, but keep the static 2022-2024 price coefficients unchanged.
    historical_to_cutoff = panel[panel["date"] <= pd.Timestamp("2026-08-31")].copy()
    pro_state = one_step_static_state_rule(
        historical_to_cutoff,
        prospective,
        intercept,
        slope,
        float(best["threshold_up"]),
        float(best["threshold_down"]),
    )
    pro_round = nearest_round(latent(prospective, intercept, slope))
    pro_actual = prospective["target_target_mid"].to_numpy(dtype=float)

    holdout_out = holdout[[
        "date", "cp", "target_status", "target_target_mid", "log_close"
    ]].copy()
    holdout_out["static_latent"] = latent(holdout, intercept, slope)
    holdout_out["nearest_round"] = holdout_round
    holdout_out["state_threshold"] = holdout_state

    prospective_out = prospective[[
        "date", "cp", "target_status", "target_target_mid", "log_close"
    ]].copy()
    prospective_out["static_latent"] = latent(prospective, intercept, slope)
    prospective_out["nearest_round"] = pro_round
    prospective_out["state_threshold"] = pro_state
    prospective_out["round_error"] = np.abs(pro_round - pro_actual)
    prospective_out["state_error"] = np.abs(pro_state - pro_actual)

    summary = {
        "methodologyWarning": (
            "This static-state architecture was investigated after the first Sep-Oct "
            "prospective window had been inspected. Therefore Sep-Oct performance is "
            "exploratory only. Thresholds are selected exclusively on 2023-2024 "
            "expanding validation, and any clean confirmation must start after 2026-10-09."
        ),
        "staticFit": {
            "intercept": intercept,
            "slope": slope,
            "fitPeriod": "2022-01-01..2024-12-31",
        },
        "preHoldoutNearestRound": round_cv,
        "selectedStaticStateRule": {
            "thresholdUp": float(best["threshold_up"]),
            "thresholdDown": float(best["threshold_down"]),
            "cvMae": float(best["cv_mae"]),
            "cvExactMatch": float(best["cv_exact_match"]),
            "cvWithin0_1": float(best["cv_within_0_1"]),
        },
        "observed2025_2026": {
            "nearestRound": score_exact(hold_actual, hold_round_exact),
            "staticStateRule": score_exact(hold_actual, hold_state_exact),
        },
        "firstProspectiveWindowExploratory": {
            "nearestRound": score_exact(pro_actual, pro_round),
            "staticStateRule": score_exact(pro_actual, pro_state),
        },
        "transitionGapDiagnostics": (
            transition_gap_summary(
                panel[panel["year"] <= 2024].copy(), intercept, slope, "pre_holdout_2022_2024"
            )
            + transition_gap_summary(
                panel[panel["year"] >= 2025].copy(), intercept, slope, "observed_2025_2026"
            )
            + transition_gap_summary(
                prospective, intercept, slope, "first_prospective_2026_09_10"
            )
        ),
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    grid.to_csv(GRID_OUTPUT, index=False, encoding="utf-8-sig")
    holdout_out.to_csv(HOLDOUT_OUTPUT, index=False, encoding="utf-8-sig")
    prospective_out.to_csv(PROSPECTIVE_OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
