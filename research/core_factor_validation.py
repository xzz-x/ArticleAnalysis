from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[1]
PANEL_PATH = REPO / "data" / "features" / "star_model_panel_2022_2026.parquet"
DERIVED = REPO / "data" / "derived"

CANDIDATES_OUTPUT = DERIVED / "core_factor_validation_candidates.csv"
METRICS_OUTPUT = DERIVED / "core_factor_holdout_metrics.csv"
PREDICTIONS_OUTPUT = DERIVED / "core_factor_holdout_predictions.csv"
SUMMARY_OUTPUT = DERIVED / "core_factor_validation_summary.json"

INDEX_NAMES = {"1000002": "A股全指", "000985": "中证全指"}
WEIGHTINGS = ("mcw", "ew", "ewpvo", "avg", "median")
PB_WINDOWS = (5, 10, 20)
BUFFETT_COLUMNS = ("buffett_mc_to_gdp", "buffett_mc_om_to_gdp")


@dataclass
class FittedModel:
    feature_names: list[str]
    directions: list[int]
    means: np.ndarray
    scales: np.ndarray
    intercept: float
    transformed_coefficients: np.ndarray

    @property
    def original_coefficients(self) -> np.ndarray:
        return self.transformed_coefficients * np.asarray(self.directions) / self.scales

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        x = frame[self.feature_names].to_numpy(dtype=float)
        z = (x - self.means) / self.scales
        transformed = z * np.asarray(self.directions)
        return self.intercept + transformed @ self.transformed_coefficients


def weighted_mean_and_scale(x: np.ndarray, weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    weight_sum = weights.sum()
    means = (x * weights[:, None]).sum(axis=0) / weight_sum
    variance = (((x - means) ** 2) * weights[:, None]).sum(axis=0) / weight_sum
    scales = np.sqrt(variance)
    if np.any(~np.isfinite(scales)) or np.any(scales <= 0):
        raise ValueError("features must have positive finite weighted variance")
    return means, scales


def weighted_lstsq(x: np.ndarray, y: np.ndarray, weights: np.ndarray) -> np.ndarray:
    root = np.sqrt(weights)
    return np.linalg.lstsq(x * root[:, None], y * root, rcond=None)[0]


def fit_monotone_linear(
    frame: pd.DataFrame,
    feature_names: list[str],
    directions: list[int],
    *,
    target: str = "target_target_mid",
    weight: str = "target_training_weight",
) -> FittedModel:
    use = frame.dropna(subset=feature_names + [target, weight]).copy()
    use = use[use[weight] > 0]
    if len(use) <= len(feature_names) + 2:
        raise ValueError("not enough observations to fit model")
    x = use[feature_names].to_numpy(dtype=float)
    y = use[target].to_numpy(dtype=float)
    weights = use[weight].to_numpy(dtype=float)
    means, scales = weighted_mean_and_scale(x, weights)
    transformed = ((x - means) / scales) * np.asarray(directions)

    # With only three core factors, exact active-set enumeration is simpler
    # and more reproducible than adding an optimization dependency.
    best_sse = math.inf
    best_intercept = float("nan")
    best_coefficients = np.zeros(len(feature_names), dtype=float)
    for active_mask in itertools.product((False, True), repeat=len(feature_names)):
        active = np.flatnonzero(active_mask)
        design = np.ones((len(use), 1 + len(active)))
        if len(active):
            design[:, 1:] = transformed[:, active]
        beta = weighted_lstsq(design, y, weights)
        coefficients = np.zeros(len(feature_names), dtype=float)
        if len(active):
            coefficients[active] = beta[1:]
        if np.any(coefficients < -1e-12):
            continue
        prediction = beta[0] + transformed @ coefficients
        sse = float(np.sum(weights * (y - prediction) ** 2))
        if sse < best_sse:
            best_sse = sse
            best_intercept = float(beta[0])
            best_coefficients = np.maximum(coefficients, 0)

    if not np.isfinite(best_sse):
        raise RuntimeError("monotone active-set fit failed")
    return FittedModel(feature_names, directions, means, scales, best_intercept, best_coefficients)


def interval_error(prediction: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    return np.where(
        prediction < low,
        low - prediction,
        np.where(prediction > high, prediction - high, 0.0),
    )


def score(frame: pd.DataFrame, prediction: np.ndarray) -> dict[str, float | int]:
    low = frame["target_star_low"].to_numpy(dtype=float)
    high = frame["target_star_high"].to_numpy(dtype=float)
    midpoint = frame["target_target_mid"].to_numpy(dtype=float)
    weights = frame["target_training_weight"].to_numpy(dtype=float)
    trainable = np.isfinite(low) & np.isfinite(high) & (weights > 0)
    errors = interval_error(prediction[trainable], low[trainable], high[trainable])
    exact = frame["target_status"].eq("exact").to_numpy() & np.isfinite(midpoint)
    exact_errors = np.abs(prediction[exact] - midpoint[exact])
    regime = np.floor(np.clip(prediction[exact], 1, 5.999999)) == np.floor(midpoint[exact])
    return {
        "n": int(len(frame)),
        "trainable_n": int(trainable.sum()),
        "exact_n": int(exact.sum()),
        "interval_mae": float(errors.mean()),
        "weighted_interval_mae": float(np.average(errors, weights=weights[trainable])),
        "interval_hit_rate": float((errors <= 1e-12).mean()),
        "exact_mae": float(exact_errors.mean()),
        "exact_rmse": float(np.sqrt(np.mean(exact_errors**2))),
        "exact_within_0_1": float((exact_errors <= 0.1000001).mean()),
        "exact_regime_accuracy": float(regime.mean()),
    }


def core_spec(weighting: str, buffett: str, pb_window: int) -> tuple[list[str], list[int]]:
    return (
        [buffett, f"equity_bond_ratio_{weighting}", f"pb_{weighting}_pct_{pb_window}y_local"],
        [-1, 1, -1],
    )


def pre_holdout_cv(panel: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []
    folds = ((2022, 2023), (2023, 2024))
    for code in INDEX_NAMES:
        index_panel = panel[panel["stockCode"] == code].copy()
        for weighting in WEIGHTINGS:
            for buffett in BUFFETT_COLUMNS:
                for pb_window in PB_WINDOWS:
                    features, directions = core_spec(weighting, buffett, pb_window)
                    fold_metrics: list[dict[str, float | int]] = []
                    for train_end, test_year in folds:
                        train = index_panel[index_panel["year"] <= train_end]
                        test = index_panel[index_panel["year"] == test_year]
                        model = fit_monotone_linear(train, features, directions)
                        fold_metrics.append(score(test, model.predict(test)))
                    rows.append(
                        {
                            "stockCode": code,
                            "index_name": INDEX_NAMES[code],
                            "weighting": weighting,
                            "buffett_column": buffett,
                            "pb_window_years": pb_window,
                            "cv_exact_mae": float(np.mean([m["exact_mae"] for m in fold_metrics])),
                            "cv_interval_mae": float(np.mean([m["interval_mae"] for m in fold_metrics])),
                            "cv_exact_within_0_1": float(np.mean([m["exact_within_0_1"] for m in fold_metrics])),
                            "cv_regime_accuracy": float(np.mean([m["exact_regime_accuracy"] for m in fold_metrics])),
                        }
                    )
    return pd.DataFrame(rows).sort_values(["cv_exact_mae", "cv_interval_mae"]).reset_index(drop=True)


def fit_and_evaluate(
    panel: pd.DataFrame,
    *,
    model_name: str,
    code: str,
    features: list[str],
    directions: list[int],
) -> tuple[dict[str, float | int | str], pd.DataFrame, FittedModel]:
    index_panel = panel[panel["stockCode"] == code].copy()
    train = index_panel[index_panel["year"] <= 2024].copy()
    holdout = index_panel[index_panel["year"] >= 2025].copy()
    model = fit_monotone_linear(train, features, directions)
    prediction = model.predict(holdout)
    metrics: dict[str, float | int | str] = {
        "model": model_name,
        "stockCode": code,
        "index_name": INDEX_NAMES[code],
        "train_start": int(train["year"].min()),
        "train_end": int(train["year"].max()),
        "holdout_start": int(holdout["year"].min()),
        "holdout_end": int(holdout["year"].max()),
        **score(holdout, prediction),
    }
    for feature, coefficient in zip(features, model.original_coefficients):
        metrics[f"coef::{feature}"] = float(coefficient)
    predictions = holdout[
        [
            "date",
            "stockCode",
            "index_name",
            "target_star",
            "target_star_low",
            "target_star_high",
            "target_target_mid",
            "target_status",
            "target_training_weight",
        ]
    ].copy()
    predictions["model"] = model_name
    predictions["prediction"] = prediction
    predictions["interval_error"] = interval_error(
        prediction,
        predictions["target_star_low"].to_numpy(dtype=float),
        predictions["target_star_high"].to_numpy(dtype=float),
    )
    return metrics, predictions, model


def year_scores(predictions: pd.DataFrame) -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []
    by_year = predictions.assign(year=predictions["date"].dt.year)
    for (model, year), group in by_year.groupby(["model", "year"]):
        row: dict[str, float | int | str] = {"model": model, "year": int(year)}
        row.update(score(group, group["prediction"].to_numpy(dtype=float)))
        rows.append(row)
    return rows


def main() -> None:
    panel = pd.read_parquet(PANEL_PATH)
    panel["date"] = pd.to_datetime(panel["date"])
    panel["year"] = panel["date"].dt.year
    panel["log_close"] = np.log(panel["cp"].where(panel["cp"] > 0))
    panel = panel[panel["target_training_weight"] > 0].copy()

    candidates = pre_holdout_cv(panel)
    candidates.to_csv(CANDIDATES_OUTPUT, index=False, encoding="utf-8-sig")
    selected = candidates.iloc[0]
    selected_features, selected_directions = core_spec(
        str(selected["weighting"]), str(selected["buffett_column"]), int(selected["pb_window_years"])
    )

    evaluations: list[dict[str, float | int | str]] = []
    prediction_frames: list[pd.DataFrame] = []
    fitted_models: dict[str, FittedModel] = {}

    core_metrics, core_predictions, core_model = fit_and_evaluate(
        panel,
        model_name="core_locked_cv",
        code=str(selected["stockCode"]),
        features=selected_features,
        directions=selected_directions,
    )
    evaluations.append(core_metrics)
    prediction_frames.append(core_predictions)
    fitted_models["core_locked_cv"] = core_model

    # Price-only baseline uses the same index selected by pre-holdout CV and a
    # decreasing log-price relationship.
    baseline_metrics, baseline_predictions, baseline_model = fit_and_evaluate(
        panel,
        model_name="baseline_log_close",
        code=str(selected["stockCode"]),
        features=["log_close"],
        directions=[-1],
    )
    evaluations.append(baseline_metrics)
    prediction_frames.append(baseline_predictions)
    fitted_models["baseline_log_close"] = baseline_model

    predictions = pd.concat(prediction_frames, ignore_index=True)
    metrics = pd.DataFrame(evaluations).sort_values("exact_mae").reset_index(drop=True)
    metrics.to_csv(METRICS_OUTPUT, index=False, encoding="utf-8-sig")
    predictions.to_csv(PREDICTIONS_OUTPUT, index=False, encoding="utf-8-sig")
    metrics_by_model = metrics.set_index("model")
    core_exact_mae = float(metrics_by_model.loc["core_locked_cv", "exact_mae"])
    baseline_exact_mae = float(metrics_by_model.loc["baseline_log_close", "exact_mae"])

    summary = {
        "selectionRule": "lowest mean exact MAE on 2023 and 2024 expanding-window validation",
        "selectedSpecification": {
            "stockCode": str(selected["stockCode"]),
            "indexName": str(selected["index_name"]),
            "weighting": str(selected["weighting"]),
            "buffettColumn": str(selected["buffett_column"]),
            "pbWindowYears": int(selected["pb_window_years"]),
            "features": selected_features,
            "directions": selected_directions,
            "preHoldoutCvExactMae": float(selected["cv_exact_mae"]),
        },
        "holdoutMetrics": json.loads(metrics.to_json(orient="records")),
        "holdoutMetricsByYear": year_scores(predictions),
        "holdoutComparison": {
            "verdict": (
                "core_model_beats_price_baseline"
                if core_exact_mae < baseline_exact_mae
                else "core_model_does_not_beat_price_baseline"
            ),
            "coreExactMae": core_exact_mae,
            "baselineExactMae": baseline_exact_mae,
            "coreToBaselineMaeRatio": core_exact_mae / baseline_exact_mae,
        },
        "coefficientDirectionsSatisfied": {
            name: bool(np.all(model.transformed_coefficients >= -1e-12))
            for name, model in fitted_models.items()
        },
        "candidateCount": int(len(candidates)),
        "trainPeriod": "2022-01-01..2024-12-31",
        "lockedHoldoutPeriod": "2025-01-01..2026-08-31",
        "notes": [
            "The threshold-only target has zero weight and is excluded before fitting and scoring.",
            "Range targets use interval loss; exact metrics use only exact labels.",
            "No 2025-2026 observation participates in model selection or fitting.",
        ],
    }
    SUMMARY_OUTPUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
