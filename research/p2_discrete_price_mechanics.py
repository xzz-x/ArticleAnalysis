from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import (
    DERIVED,
    fit_linear,
    interval_error,
    prepare_panel,
    predict_linear,
)

SUMMARY_OUTPUT = DERIVED / "p2_discrete_price_mechanics_summary.json"
GRID_OUTPUT = DERIVED / "p2_discrete_price_mechanics_grid.csv"
HOLDOUT_OUTPUT = DERIVED / "p2_discrete_price_mechanics_holdout.csv"


def _score(frame: pd.DataFrame, prediction: np.ndarray) -> dict[str, float | int]:
    pred = np.asarray(prediction, dtype=float)
    low = pd.to_numeric(frame["target_star_low"], errors="coerce").to_numpy(dtype=float)
    high = pd.to_numeric(frame["target_star_high"], errors="coerce").to_numpy(dtype=float)
    midpoint = pd.to_numeric(frame["target_target_mid"], errors="coerce").to_numpy(dtype=float)
    status = frame["target_status"].astype(str).to_numpy()

    trainable = np.isfinite(pred) & np.isfinite(low) & np.isfinite(high)
    exact = np.isfinite(pred) & (status == "exact") & np.isfinite(midpoint)

    interval_errors = interval_error(pred[trainable], low[trainable], high[trainable])
    exact_errors = np.abs(pred[exact] - midpoint[exact])
    return {
        "n": int(len(frame)),
        "exact_n": int(exact.sum()),
        "interval_mae": float(interval_errors.mean()) if len(interval_errors) else float("nan"),
        "exact_mae": float(exact_errors.mean()) if len(exact_errors) else float("nan"),
        "exact_within_0_1": float((exact_errors <= 0.1000001).mean()) if len(exact_errors) else float("nan"),
    }


def quantize(values: np.ndarray, step: float = 0.1, offset: float = 0.0) -> np.ndarray:
    return np.round((np.asarray(values, dtype=float) - offset) / step) * step + offset


def sticky_publish(latent: np.ndarray, initial: float, threshold: float) -> np.ndarray:
    out = np.empty(len(latent), dtype=float)
    state = float(initial)
    for i, value in enumerate(np.asarray(latent, dtype=float)):
        if not np.isfinite(value):
            out[i] = np.nan
            continue
        if abs(value - state) >= threshold:
            state = float(np.round(value / 0.1) * 0.1)
        out[i] = state
    return out


def hysteresis_publish(
    latent: np.ndarray,
    initial: float,
    threshold_up: float,
    threshold_down: float,
) -> np.ndarray:
    """Publish 0.1-star states with asymmetric update thresholds.

    Star rises when latent exceeds the current state by threshold_up.
    Star falls when latent is below the current state by threshold_down.
    """
    out = np.empty(len(latent), dtype=float)
    state = float(initial)
    for i, value in enumerate(np.asarray(latent, dtype=float)):
        if not np.isfinite(value):
            out[i] = np.nan
            continue
        delta = float(value - state)
        if delta >= threshold_up or delta <= -threshold_down:
            state = float(np.round(value / 0.1) * 0.1)
        out[i] = state
    return out


def last_observed_state(train: pd.DataFrame) -> float:
    use = train.sort_values("date").dropna(subset=["target_target_mid"])
    if use.empty:
        raise ValueError("training fold has no target state")
    return float(use.iloc[-1]["target_target_mid"])


def evaluate_fold(
    train: pd.DataFrame,
    test: pd.DataFrame,
    model: str,
    params: dict[str, float],
) -> dict[str, float | int]:
    fit = fit_linear(train, ["log_close"])
    latent = predict_linear(test, ["log_close"], fit)
    if model == "continuous":
        pred = latent
    elif model == "round_0_1":
        pred = quantize(latent, 0.1, params.get("offset", 0.0))
    elif model == "sticky":
        pred = sticky_publish(latent, last_observed_state(train), params["threshold"])
    elif model == "hysteresis":
        pred = hysteresis_publish(
            latent,
            last_observed_state(train),
            params["threshold_up"],
            params["threshold_down"],
        )
    else:
        raise ValueError(model)
    return _score(test, pred)


def preholdout_grid(panel: pd.DataFrame) -> pd.DataFrame:
    folds = ((2022, 2023), (2023, 2024))
    specs: list[tuple[str, dict[str, float]]] = [
        ("continuous", {}),
        ("round_0_1", {"offset": 0.0}),
    ]
    for offset in np.arange(-0.04, 0.041, 0.01):
        specs.append(("round_0_1", {"offset": float(np.round(offset, 2))}))
    for threshold in np.arange(0.03, 0.121, 0.01):
        specs.append(("sticky", {"threshold": float(np.round(threshold, 2))}))
    for up in np.arange(0.03, 0.121, 0.01):
        for down in np.arange(0.03, 0.121, 0.01):
            specs.append(
                (
                    "hysteresis",
                    {
                        "threshold_up": float(np.round(up, 2)),
                        "threshold_down": float(np.round(down, 2)),
                    },
                )
            )

    rows: list[dict[str, object]] = []
    seen: set[tuple[str, tuple[tuple[str, float], ...]]] = set()
    for model, params in specs:
        key = (model, tuple(sorted(params.items())))
        if key in seen:
            continue
        seen.add(key)
        fold_scores = []
        for train_end, test_year in folds:
            train = panel[panel["year"] <= train_end].copy()
            test = panel[panel["year"] == test_year].copy()
            fold_scores.append(evaluate_fold(train, test, model, params))
        rows.append(
            {
                "model": model,
                **params,
                "cv_exact_mae": float(np.mean([x["exact_mae"] for x in fold_scores])),
                "cv_interval_mae": float(np.mean([x["interval_mae"] for x in fold_scores])),
                "cv_exact_within_0_1": float(np.mean([x["exact_within_0_1"] for x in fold_scores])),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["cv_exact_mae", "cv_interval_mae"], ignore_index=True
    )


def pick_best(grid: pd.DataFrame, model: str) -> dict[str, float]:
    row = grid[grid["model"] == model].sort_values(
        ["cv_exact_mae", "cv_interval_mae"]
    ).iloc[0]
    params: dict[str, float] = {}
    for name in ("offset", "threshold", "threshold_up", "threshold_down"):
        if name in row.index and pd.notna(row[name]):
            params[name] = float(row[name])
    return params


def holdout_eval(panel: pd.DataFrame, grid: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = panel[panel["year"] <= 2024].copy()
    holdout = panel[panel["year"] >= 2025].copy().sort_values("date")
    fit = fit_linear(train, ["log_close"])
    latent = predict_linear(holdout, ["log_close"], fit)

    selected = {
        "continuous": {},
        "round_0_1": pick_best(grid, "round_0_1"),
        "sticky": pick_best(grid, "sticky"),
        "hysteresis": pick_best(grid, "hysteresis"),
    }
    predictions: dict[str, np.ndarray] = {}
    predictions["continuous"] = latent
    predictions["round_0_1"] = quantize(
        latent, 0.1, selected["round_0_1"].get("offset", 0.0)
    )
    predictions["sticky"] = sticky_publish(
        latent, last_observed_state(train), selected["sticky"]["threshold"]
    )
    predictions["hysteresis"] = hysteresis_publish(
        latent,
        last_observed_state(train),
        selected["hysteresis"]["threshold_up"],
        selected["hysteresis"]["threshold_down"],
    )

    metric_rows = []
    out = holdout[
        [
            "date",
            "target_status",
            "target_star_low",
            "target_star_high",
            "target_target_mid",
            "cp",
            "log_close",
        ]
    ].copy()
    out["latent_star"] = latent
    for model, pred in predictions.items():
        out[f"pred_{model}"] = pred
        metric_rows.append(
            {
                "model": model,
                **selected[model],
                **_score(holdout, pred),
            }
        )
    return pd.DataFrame(metric_rows).sort_values("exact_mae"), out


def transition_threshold_summary(panel: pd.DataFrame) -> list[dict[str, object]]:
    exact = panel[panel["target_status"] == "exact"].copy().sort_values("date")
    exact["prev_star"] = exact["target_target_mid"].shift(1)
    exact["prev_date"] = exact["date"].shift(1)
    exact["delta_star"] = exact["target_target_mid"] - exact["prev_star"]
    exact["delta_log_price"] = exact["log_close"] - exact["log_close"].shift(1)
    moves = exact[
        exact["delta_star"].abs().between(0.099999, 0.100001)
        & exact["delta_log_price"].notna()
    ].copy()
    rows = []
    for (prev_star, new_star), group in moves.groupby(
        ["prev_star", "target_target_mid"]
    ):
        rows.append(
            {
                "from_star": float(prev_star),
                "to_star": float(new_star),
                "n": int(len(group)),
                "median_price_move_pct": float(
                    100 * np.median(np.expm1(group["delta_log_price"]))
                ),
                "mean_price_move_pct": float(
                    100 * np.mean(np.expm1(group["delta_log_price"]))
                ),
            }
        )
    return sorted(rows, key=lambda x: (x["from_star"], x["to_star"]))


def main() -> None:
    panel = prepare_panel()
    grid = preholdout_grid(panel)
    metrics, holdout = holdout_eval(panel, grid)

    train = panel[panel["year"] <= 2024].copy()
    price_fit = fit_linear(train, ["log_close"])
    slope = float(price_fit[1][0])
    implied_pct_per_0_1 = float(100 * np.expm1(0.1 / abs(slope)))

    summary = {
        "selectionPolicy": (
            "All quantization/sticky/hysteresis parameters are selected only on "
            "2023-2024 expanding validation. 2025-2026 is a locked holdout."
        ),
        "priceCoefficient": slope,
        "impliedIndexMovePctPer0_1Star": implied_pct_per_0_1,
        "bestPreHoldoutByModel": {
            model: json.loads(
                grid[grid["model"] == model].head(1).to_json(orient="records")
            )[0]
            for model in ("continuous", "round_0_1", "sticky", "hysteresis")
        },
        "holdoutMetrics": json.loads(metrics.to_json(orient="records")),
        "transitionThresholds": transition_threshold_summary(panel),
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    grid.to_csv(GRID_OUTPUT, index=False, encoding="utf-8-sig")
    holdout.to_csv(HOLDOUT_OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
