from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[1]
PANEL_CSV = REPO / "data" / "features" / "star_model_panel_2022_2026.csv"
DERIVED = REPO / "data" / "derived"

FACTOR_OUTPUT = DERIVED / "price_residual_factor_screen.csv"
METRICS_OUTPUT = DERIVED / "price_residual_holdout_metrics.csv"
CHANGE_OUTPUT = DERIVED / "star_change_day_analysis.csv"
SUMMARY_OUTPUT = DERIVED / "price_residual_analysis_summary.json"

INDEX_CODE = "1000002"
CANDIDATES = {
    "buffett_mc_to_gdp": "slow_fundamental",
    "buffett_mc_om_to_gdp": "slow_fundamental",
    "equity_bond_ratio_avg": "valuation_rate",
    "pb_avg_pct_10y_local": "valuation",
    "fin_q_ps_np_ttm_y2y": "slow_fundamental",
    "fin_q_m_roe_ttm": "slow_fundamental",
    "ta_pct_252": "market_sentiment",
    "to_r_pct_252": "market_sentiment",
    "market_financing_balance_change_20": "market_sentiment",
    "market_financing_balance_change_60": "market_sentiment",
    "investor_nni_w": "market_sentiment",
    "investor_nni_m": "market_sentiment",
}
SLOW_CATEGORIES = {"slow_fundamental", "valuation", "valuation_rate"}


def weighted_lstsq(design: np.ndarray, y: np.ndarray, weights: np.ndarray) -> np.ndarray:
    root = np.sqrt(weights)
    return np.linalg.lstsq(design * root[:, None], y * root, rcond=None)[0]


def fit_linear(frame: pd.DataFrame, features: list[str]) -> tuple[float, np.ndarray]:
    use = frame.dropna(subset=features + ["target_target_mid", "target_training_weight"]).copy()
    use = use[use["target_training_weight"] > 0]
    x = use[features].to_numpy(dtype=float)
    y = use["target_target_mid"].to_numpy(dtype=float)
    w = use["target_training_weight"].to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(use)), x])
    beta = weighted_lstsq(design, y, w)
    return float(beta[0]), beta[1:]


def predict_linear(frame: pd.DataFrame, features: list[str], fit: tuple[float, np.ndarray]) -> np.ndarray:
    intercept, coefficients = fit
    x = frame[features].to_numpy(dtype=float)
    return intercept + x @ coefficients


def interval_error(prediction: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    return np.where(
        prediction < low,
        low - prediction,
        np.where(prediction > high, prediction - high, 0.0),
    )


def score(frame: pd.DataFrame, prediction: np.ndarray) -> dict[str, float | int]:
    pred = np.asarray(prediction, dtype=float)
    low = frame["target_star_low"].to_numpy(dtype=float)
    high = frame["target_star_high"].to_numpy(dtype=float)
    midpoint = frame["target_target_mid"].to_numpy(dtype=float)
    weights = frame["target_training_weight"].to_numpy(dtype=float)
    trainable = np.isfinite(pred) & np.isfinite(low) & np.isfinite(high) & (weights > 0)
    exact = (
        np.isfinite(pred)
        & frame["target_status"].eq("exact").to_numpy()
        & np.isfinite(midpoint)
    )
    errors = interval_error(pred[trainable], low[trainable], high[trainable])
    exact_errors = np.abs(pred[exact] - midpoint[exact])
    regime = (
        np.floor(np.clip(pred[exact], 1, 5.999999))
        == np.floor(midpoint[exact])
    )
    return {
        "n": int(len(frame)),
        "trainable_n": int(trainable.sum()),
        "exact_n": int(exact.sum()),
        "interval_mae": float(errors.mean()) if len(errors) else float("nan"),
        "weighted_interval_mae": (
            float(np.average(errors, weights=weights[trainable])) if len(errors) else float("nan")
        ),
        "exact_mae": float(exact_errors.mean()) if len(exact_errors) else float("nan"),
        "exact_rmse": (
            float(np.sqrt(np.mean(exact_errors**2))) if len(exact_errors) else float("nan")
        ),
        "exact_within_0_1": (
            float((exact_errors <= 0.1000001).mean()) if len(exact_errors) else float("nan")
        ),
        "exact_regime_accuracy": float(regime.mean()) if len(regime) else float("nan"),
    }


def prepare_panel() -> pd.DataFrame:
    panel = pd.read_csv(PANEL_CSV, low_memory=False)
    panel["stockCode"] = panel["stockCode"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    panel = panel[panel["stockCode"] == INDEX_CODE].copy()
    panel["date"] = pd.to_datetime(panel["date"])
    panel["year"] = panel["date"].dt.year
    panel["log_close"] = np.log(pd.to_numeric(panel["cp"], errors="coerce").where(lambda s: s > 0))
    numeric = [
        "target_target_mid",
        "target_training_weight",
        "target_star_low",
        "target_star_high",
        *[name for name in CANDIDATES if name in panel.columns],
    ]
    for column in numeric:
        panel[column] = pd.to_numeric(panel[column], errors="coerce")
    return panel.sort_values("date").reset_index(drop=True)


def evaluate_model(
    train: pd.DataFrame,
    test: pd.DataFrame,
    extra_feature: str | None,
) -> tuple[dict[str, float | int], tuple[float, np.ndarray], np.ndarray]:
    features = ["log_close"] + ([extra_feature] if extra_feature else [])
    fit = fit_linear(train, features)
    if fit[1][0] >= 0:
        raise ValueError(f"price coefficient must be negative, got {fit[1][0]}")
    prediction = predict_linear(test, features, fit)
    return score(test, prediction), fit, prediction


def expanding_cv(panel: pd.DataFrame) -> pd.DataFrame:
    folds = ((2022, 2023), (2023, 2024))
    available = [name for name in CANDIDATES if name in panel.columns]
    rows: list[dict[str, object]] = []

    for feature in [None, *available]:
        fold_scores: list[dict[str, float | int]] = []
        valid = True
        for train_end, test_year in folds:
            train = panel[panel["year"] <= train_end].copy()
            test = panel[panel["year"] == test_year].copy()
            required = ["log_close"] + ([feature] if feature else [])
            if train[required].dropna().shape[0] < 50 or test[required].dropna().shape[0] < 20:
                valid = False
                break
            metrics, _, _ = evaluate_model(train, test, feature)
            fold_scores.append(metrics)
        if not valid:
            continue
        rows.append(
            {
                "feature": feature or "__price_only__",
                "category": CANDIDATES.get(feature, "price"),
                "cv_exact_mae": float(np.mean([m["exact_mae"] for m in fold_scores])),
                "cv_interval_mae": float(np.mean([m["interval_mae"] for m in fold_scores])),
                "cv_exact_within_0_1": float(np.mean([m["exact_within_0_1"] for m in fold_scores])),
                "cv_regime_accuracy": float(np.mean([m["exact_regime_accuracy"] for m in fold_scores])),
            }
        )
    result = pd.DataFrame(rows).sort_values(["cv_exact_mae", "cv_interval_mae"]).reset_index(drop=True)
    baseline = float(result.loc[result["feature"] == "__price_only__", "cv_exact_mae"].iloc[0])
    result["cv_exact_mae_gain_vs_price"] = baseline - result["cv_exact_mae"]
    return result


def select_feature(screen: pd.DataFrame, categories: Iterable[str] | None = None) -> str | None:
    candidates = screen[screen["feature"] != "__price_only__"].copy()
    if categories is not None:
        candidates = candidates[candidates["category"].isin(set(categories))]
    if candidates.empty:
        return None
    best = candidates.sort_values(["cv_exact_mae", "cv_interval_mae"]).iloc[0]
    return str(best["feature"])


def holdout_evaluations(
    panel: pd.DataFrame,
    residual_feature: str | None,
    slow_feature: str | None,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame], dict[str, tuple[float, np.ndarray]]]:
    train = panel[panel["year"] <= 2024].copy()
    holdout = panel[panel["year"] >= 2025].copy()
    specs = {
        "price_only": None,
        "price_plus_best_residual": residual_feature,
        "price_plus_slow_anchor": slow_feature,
    }

    rows: list[dict[str, object]] = []
    prediction_frames: dict[str, pd.DataFrame] = {}
    fits: dict[str, tuple[float, np.ndarray]] = {}
    seen: set[tuple[str | None]] = set()

    for name, feature in specs.items():
        key = (feature,)
        if name != "price_only" and key in seen:
            continue
        seen.add(key)
        metrics, fit, prediction = evaluate_model(train, holdout, feature)
        fits[name] = fit
        rows.append(
            {
                "model": name,
                "extra_feature": feature or "",
                **metrics,
                "price_coefficient": float(fit[1][0]),
                "extra_coefficient": float(fit[1][1]) if feature else np.nan,
            }
        )
        frame = holdout[
            [
                "date",
                "target_target_mid",
                "target_status",
                "target_star_low",
                "target_star_high",
                "target_training_weight",
                "cp",
                "log_close",
            ]
        ].copy()
        frame["prediction"] = prediction
        frame["residual"] = frame["target_target_mid"] - prediction
        prediction_frames[name] = frame

    return pd.DataFrame(rows).sort_values("exact_mae"), prediction_frames, fits


def implied_anchor_by_year(panel: pd.DataFrame, price_fit: tuple[float, np.ndarray]) -> list[dict[str, object]]:
    exact = panel[panel["target_status"] == "exact"].copy()
    slope = float(price_fit[1][0])
    exact["implied_anchor"] = exact["target_target_mid"] - slope * exact["log_close"]
    rows: list[dict[str, object]] = []
    for year, group in exact.groupby("year"):
        rows.append(
            {
                "year": int(year),
                "n": int(len(group)),
                "mean": float(group["implied_anchor"].mean()),
                "std": float(group["implied_anchor"].std(ddof=0)),
                "min": float(group["implied_anchor"].min()),
                "max": float(group["implied_anchor"].max()),
            }
        )
    return rows


def change_day_analysis(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    exact = panel[panel["target_status"] == "exact"].copy().sort_values("date")
    exact["previous_date"] = exact["date"].shift(1)
    exact["gap_days"] = (exact["date"] - exact["previous_date"]).dt.days
    exact["star_change"] = exact["target_target_mid"].diff()
    exact["log_price_change"] = exact["log_close"].diff()
    pairs = exact[(exact["gap_days"] > 0) & (exact["gap_days"] <= 7)].dropna(
        subset=["star_change", "log_price_change"]
    ).copy()
    pairs["pair_year"] = pairs["date"].dt.year

    train = pairs[pairs["pair_year"] <= 2024].copy()
    holdout = pairs[pairs["pair_year"] >= 2025].copy()
    x = train["log_price_change"].to_numpy(dtype=float)
    y = train["star_change"].to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(train)), x])
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    holdout["predicted_star_change_from_price"] = (
        beta[0] + beta[1] * holdout["log_price_change"]
    )
    holdout["change_residual"] = (
        holdout["star_change"] - holdout["predicted_star_change_from_price"]
    )
    changed = holdout["star_change"].abs() >= 0.05
    directional = changed & (holdout["log_price_change"].abs() > 1e-12)
    expected_direction = (
        np.sign(holdout.loc[directional, "star_change"])
        == -np.sign(holdout.loc[directional, "log_price_change"])
    )

    summary = {
        "trainPairs": int(len(train)),
        "holdoutPairs": int(len(holdout)),
        "holdoutChangedStarDays": int(changed.sum()),
        "priceChangeIntercept": float(beta[0]),
        "starChangePerOnePercentIndexMove": float(beta[1] * 0.01),
        "holdoutChangeMae": float(
            np.abs(
                holdout["star_change"] - holdout["predicted_star_change_from_price"]
            ).mean()
        ),
        "changedDayDirectionConsistentWithPrice": (
            float(expected_direction.mean()) if len(expected_direction) else float("nan")
        ),
        "largestResidualChangeDates": (
            holdout.nlargest(10, "change_residual", keep="all")[
                ["date", "star_change", "log_price_change", "change_residual"]
            ]
            .assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d"))
            .to_dict(orient="records")
        ),
    }
    return holdout, summary


def main() -> None:
    panel = prepare_panel()
    screen = expanding_cv(panel)
    residual_feature = select_feature(screen)
    slow_feature = select_feature(screen, SLOW_CATEGORIES)

    metrics, predictions, fits = holdout_evaluations(
        panel,
        residual_feature=residual_feature,
        slow_feature=slow_feature,
    )
    price_fit = fits["price_only"]
    changes, change_summary = change_day_analysis(panel)

    DERIVED.mkdir(parents=True, exist_ok=True)
    screen.to_csv(FACTOR_OUTPUT, index=False, encoding="utf-8-sig")
    metrics.to_csv(METRICS_OUTPUT, index=False, encoding="utf-8-sig")
    changes.to_csv(CHANGE_OUTPUT, index=False, encoding="utf-8-sig")

    metrics_by_model = metrics.set_index("model")
    price_mae = float(metrics_by_model.loc["price_only", "exact_mae"])
    residual_mae = (
        float(metrics_by_model.loc["price_plus_best_residual", "exact_mae"])
        if "price_plus_best_residual" in metrics_by_model.index
        else None
    )
    slow_mae = (
        float(metrics_by_model.loc["price_plus_slow_anchor", "exact_mae"])
        if "price_plus_slow_anchor" in metrics_by_model.index
        else None
    )
    summary = {
        "index": INDEX_CODE,
        "trainPeriod": "2022-01-01..2024-12-31",
        "holdoutPeriod": "2025-01-01..2026-08-31",
        "priceBaseline": {
            "intercept": float(price_fit[0]),
            "logPriceCoefficient": float(price_fit[1][0]),
            "holdoutExactMae": price_mae,
        },
        "selectedResidualFeature": residual_feature,
        "selectedSlowAnchorFeature": slow_feature,
        "residualHoldoutExactMae": residual_mae,
        "slowAnchorHoldoutExactMae": slow_mae,
        "residualImprovementVsPrice": (
            price_mae - residual_mae if residual_mae is not None else None
        ),
        "slowAnchorImprovementVsPrice": (
            price_mae - slow_mae if slow_mae is not None else None
        ),
        "impliedPriceAnchorByYear": implied_anchor_by_year(panel, price_fit),
        "starChangeAnalysis": change_summary,
        "interpretationRule": (
            "A residual/slow factor is considered useful only if it was selected on "
            "2023-2024 expanding validation and still lowers exact MAE on the locked 2025-2026 holdout."
        ),
    }
    SUMMARY_OUTPUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
