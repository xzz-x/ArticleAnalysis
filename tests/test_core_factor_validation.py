from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.core_factor_validation import fit_monotone_linear


REPO = Path(__file__).resolve().parents[1]
DERIVED = REPO / "data" / "derived"


def test_monotone_fit_enforces_requested_directions() -> None:
    rng = np.random.default_rng(7)
    frame = pd.DataFrame(
        {
            "down": np.arange(100, dtype=float),
            "up": rng.normal(size=100),
            "wrong_way": np.arange(100, dtype=float),
            "target_training_weight": np.ones(100),
        }
    )
    frame["target_target_mid"] = 5 - 0.02 * frame["down"] + 0.5 * frame["up"]

    model = fit_monotone_linear(frame, ["down", "up", "wrong_way"], [-1, 1, 1])

    coefficients = model.original_coefficients
    assert coefficients[0] <= 0
    assert coefficients[1] >= 0
    assert coefficients[2] >= 0


def test_validation_search_and_holdout_are_locked() -> None:
    candidates = pd.read_csv(DERIVED / "core_factor_validation_candidates.csv")
    predictions = pd.read_csv(DERIVED / "core_factor_holdout_predictions.csv", parse_dates=["date"])
    summary = json.loads(
        (DERIVED / "core_factor_validation_summary.json").read_text(encoding="utf-8")
    )

    assert len(candidates) == 2 * 5 * 2 * 3
    assert summary["candidateCount"] == len(candidates)
    assert predictions["date"].min() >= pd.Timestamp("2025-01-01")
    assert predictions["date"].max() == pd.Timestamp("2026-08-31")
    assert predictions.groupby("model").size().to_dict() == {
        "baseline_log_close": 402,
        "core_locked_cv": 402,
    }
    assert summary["coefficientDirectionsSatisfied"] == {
        "core_locked_cv": True,
        "baseline_log_close": True,
    }


def test_holdout_metrics_are_finite_and_core_signs_are_valid() -> None:
    metrics = pd.read_csv(DERIVED / "core_factor_holdout_metrics.csv")
    core = metrics.set_index("model").loc["core_locked_cv"]

    for column in [
        "interval_mae",
        "weighted_interval_mae",
        "exact_mae",
        "exact_rmse",
        "exact_within_0_1",
        "exact_regime_accuracy",
    ]:
        assert np.isfinite(metrics[column]).all()
    assert core["coef::buffett_mc_om_to_gdp"] <= 0
    assert core["coef::equity_bond_ratio_avg"] >= 0
    assert core["coef::pb_avg_pct_10y_local"] <= 0
