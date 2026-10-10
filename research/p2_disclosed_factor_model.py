from __future__ import annotations

import itertools
import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, prepare_panel

SUMMARY_OUTPUT = DERIVED / "p2_disclosed_factor_model_summary.json"
PRED_OUTPUT = DERIVED / "p2_disclosed_factor_model_predictions.csv"
COEF_OUTPUT = DERIVED / "p2_disclosed_factor_model_coefficients.csv"

CORE_FACTORS = [
    "buffett_mc_to_gdp",
    "equity_bond_ratio_avg",
    "pb_avg_pct_10y_local",
]
CORE_GROWTH_FACTORS = [
    *CORE_FACTORS,
    "fin_q_ps_np_ttm_y2y",
]

# Transform every feature so a larger transformed value should, according to
# the author's disclosed valuation logic, mean "cheaper / higher star".
ORIENTATION = {
    "buffett_mc_to_gdp": -1.0,          # higher market-cap/GDP = more expensive
    "equity_bond_ratio_avg": +1.0,      # higher stock-vs-bond attractiveness = cheaper
    "pb_avg_pct_10y_local": -1.0,       # higher PB percentile = more expensive
    "fin_q_ps_np_ttm_y2y": +1.0,        # stronger earnings growth raises fair value
}


def fine_exact(frame: pd.DataFrame) -> pd.DataFrame:
    """Use only the period with ordinary 0.1-star publication precision."""
    use = frame[
        frame["target_status"].eq("exact")
        & pd.to_numeric(frame["target_target_mid"], errors="coerce").notna()
        & (pd.to_datetime(frame["date"]) >= pd.Timestamp("2022-05-31"))
    ].copy()
    use["target"] = pd.to_numeric(use["target_target_mid"], errors="coerce")
    use["weight"] = pd.to_numeric(
        use["target_training_weight"], errors="coerce"
    ).fillna(1.0)
    return use.sort_values("date")


def weighted_lstsq(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    root = np.sqrt(w)
    return np.linalg.lstsq(x * root[:, None], y * root, rcond=None)[0]


def scaler(train: pd.DataFrame, features: list[str]) -> tuple[np.ndarray, np.ndarray]:
    means = np.array(
        [pd.to_numeric(train[f], errors="coerce").mean() for f in features],
        dtype=float,
    )
    sds = np.array(
        [pd.to_numeric(train[f], errors="coerce").std(ddof=0) for f in features],
        dtype=float,
    )
    if np.any(~np.isfinite(means)) or np.any(~np.isfinite(sds)) or np.any(sds <= 0):
        raise ValueError(f"invalid scaler for {features}: means={means}, sds={sds}")
    return means, sds


def transformed_matrix(
    frame: pd.DataFrame,
    features: list[str],
    means: np.ndarray,
    sds: np.ndarray,
) -> np.ndarray:
    raw = np.column_stack(
        [pd.to_numeric(frame[f], errors="coerce").to_numpy(dtype=float) for f in features]
    )
    z = (raw - means) / sds
    signs = np.array([ORIENTATION[f] for f in features], dtype=float)
    return z * signs


def fit_nonnegative_oriented(
    train: pd.DataFrame,
    features: list[str],
) -> dict[str, object]:
    use = train.dropna(subset=features + ["target", "weight"]).copy()
    use = use[use["weight"] > 0]
    means, sds = scaler(use, features)
    x = transformed_matrix(use, features, means, sds)
    y = use["target"].to_numpy(dtype=float)
    w = use["weight"].to_numpy(dtype=float)

    best: dict[str, object] | None = None
    k = len(features)

    # Exact active-set enumeration is trivial for 3-4 disclosed variables and
    # avoids adding scipy. Every oriented coefficient is constrained >= 0.
    for mask_bits in itertools.product([False, True], repeat=k):
        active = np.array(mask_bits, dtype=bool)
        if active.any():
            design = np.column_stack([np.ones(len(use)), x[:, active]])
        else:
            design = np.ones((len(use), 1), dtype=float)
        beta = weighted_lstsq(design, y, w)
        active_coef = beta[1:] if active.any() else np.array([], dtype=float)
        if np.any(active_coef < -1e-10):
            continue

        pred = design @ beta
        loss = float(np.average((pred - y) ** 2, weights=w))
        coef = np.zeros(k, dtype=float)
        if active.any():
            coef[active] = np.maximum(active_coef, 0.0)

        candidate = {
            "loss": loss,
            "intercept": float(beta[0]),
            "coef": coef,
            "means": means,
            "sds": sds,
            "n": int(len(use)),
            "active": [features[i] for i in range(k) if active[i]],
        }
        if best is None or loss < float(best["loss"]):
            best = candidate

    if best is None:
        raise RuntimeError("no feasible nonnegative active set")
    return best


def predict_oriented(
    frame: pd.DataFrame,
    features: list[str],
    fit: dict[str, object],
) -> np.ndarray:
    x = transformed_matrix(
        frame,
        features,
        np.asarray(fit["means"], dtype=float),
        np.asarray(fit["sds"], dtype=float),
    )
    return float(fit["intercept"]) + x @ np.asarray(fit["coef"], dtype=float)


def fit_price(train: pd.DataFrame) -> tuple[float, float]:
    use = train.dropna(subset=["log_close", "target", "weight"]).copy()
    use = use[use["weight"] > 0]
    x = pd.to_numeric(use["log_close"], errors="coerce").to_numpy(dtype=float)
    y = use["target"].to_numpy(dtype=float)
    w = use["weight"].to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(use)), x])
    beta = weighted_lstsq(design, y, w)
    return float(beta[0]), float(beta[1])


def predict_price(frame: pd.DataFrame, fit: tuple[float, float]) -> np.ndarray:
    return fit[0] + fit[1] * pd.to_numeric(
        frame["log_close"], errors="coerce"
    ).to_numpy(dtype=float)


def score(actual: np.ndarray, prediction: np.ndarray) -> dict[str, float | int]:
    actual = np.asarray(actual, dtype=float)
    prediction = np.asarray(prediction, dtype=float)
    mask = np.isfinite(actual) & np.isfinite(prediction)
    error = np.abs(prediction[mask] - actual[mask])
    rounded = np.round(prediction[mask] / 0.1) * 0.1
    round_error = np.abs(rounded - actual[mask])
    return {
        "n": int(mask.sum()),
        "continuous_mae": float(error.mean()) if len(error) else float("nan"),
        "continuous_rmse": (
            float(np.sqrt(np.mean(error**2))) if len(error) else float("nan")
        ),
        "rounded_mae": float(round_error.mean()) if len(round_error) else float("nan"),
        "rounded_exact_match": (
            float((round_error <= 1e-8).mean()) if len(round_error) else float("nan")
        ),
        "rounded_within_0_1": (
            float((round_error <= 0.1000001).mean())
            if len(round_error)
            else float("nan")
        ),
    }


def common_test(
    frame: pd.DataFrame,
    features: list[str],
) -> pd.DataFrame:
    return frame.dropna(subset=features + ["log_close", "target"]).copy()


def serialize_fit(
    model: str,
    features: list[str],
    fit: dict[str, object],
    fold: str,
) -> list[dict[str, object]]:
    rows = []
    coef = np.asarray(fit["coef"], dtype=float)
    means = np.asarray(fit["means"], dtype=float)
    sds = np.asarray(fit["sds"], dtype=float)
    for i, feature in enumerate(features):
        rows.append(
            {
                "fold": fold,
                "model": model,
                "feature": feature,
                "orientation": ORIENTATION[feature],
                "standardized_oriented_coefficient": float(coef[i]),
                "raw_training_mean": float(means[i]),
                "raw_training_sd": float(sds[i]),
                "active": feature in fit["active"],
            }
        )
    return rows


def evaluate_fold(
    panel: pd.DataFrame,
    train_end: int,
    test_year: int,
) -> tuple[dict[str, object], list[dict[str, object]], pd.DataFrame]:
    train = panel[panel["year"] <= train_end].copy()
    test = panel[panel["year"] == test_year].copy()

    core_fit = fit_nonnegative_oriented(train, CORE_FACTORS)
    growth_fit = fit_nonnegative_oriented(train, CORE_GROWTH_FACTORS)
    price_fit = fit_price(train)

    test_common = common_test(test, CORE_GROWTH_FACTORS)
    actual = test_common["target"].to_numpy(dtype=float)

    core_pred = predict_oriented(test_common, CORE_FACTORS, core_fit)
    growth_pred = predict_oriented(test_common, CORE_GROWTH_FACTORS, growth_fit)
    price_pred = predict_price(test_common, price_fit)

    metrics = {
        "trainEnd": train_end,
        "testYear": test_year,
        "commonTestN": int(len(test_common)),
        "core3": score(actual, core_pred),
        "core3PlusGrowth": score(actual, growth_pred),
        "priceOnly": score(actual, price_pred),
        "core3Active": core_fit["active"],
        "core3PlusGrowthActive": growth_fit["active"],
        "priceFit": {"intercept": price_fit[0], "slope": price_fit[1]},
    }

    coefs = (
        serialize_fit("core3", CORE_FACTORS, core_fit, f"{train_end}->{test_year}")
        + serialize_fit(
            "core3PlusGrowth",
            CORE_GROWTH_FACTORS,
            growth_fit,
            f"{train_end}->{test_year}",
        )
    )

    preds = test_common[["date", "target", "cp", *CORE_GROWTH_FACTORS]].copy()
    preds["fold"] = f"{train_end}->{test_year}"
    preds["pred_core3"] = core_pred
    preds["pred_core3_growth"] = growth_pred
    preds["pred_price"] = price_pred
    return metrics, coefs, preds


def coverage(panel: pd.DataFrame) -> list[dict[str, object]]:
    rows = []
    for year, group in panel.groupby("year"):
        row: dict[str, object] = {"year": int(year), "fineExactN": int(len(group))}
        for f in CORE_GROWTH_FACTORS:
            row[f"{f}_available"] = int(
                pd.to_numeric(group[f], errors="coerce").notna().sum()
            )
        row["core3_complete"] = int(group[CORE_FACTORS].notna().all(axis=1).sum())
        row["core3_growth_complete"] = int(
            group[CORE_GROWTH_FACTORS].notna().all(axis=1).sum()
        )
        rows.append(row)
    return rows


def main() -> None:
    base = prepare_panel()
    missing = [f for f in CORE_GROWTH_FACTORS if f not in base.columns]
    if missing:
        raise RuntimeError(f"committed panel is missing disclosed factors: {missing}")

    panel = fine_exact(base)
    panel["year"] = pd.to_datetime(panel["date"]).dt.year

    fold_results = []
    coef_rows: list[dict[str, object]] = []
    pred_frames = []
    for train_end, test_year in ((2022, 2023), (2023, 2024)):
        metrics, coefs, preds = evaluate_fold(panel, train_end, test_year)
        fold_results.append(metrics)
        coef_rows.extend(coefs)
        pred_frames.append(preds)

    # Diagnostic only: architecture is being proposed after these periods have
    # already been inspected. No model selection may use these scores.
    train_pre = panel[panel["year"] <= 2024].copy()
    diagnostic = panel[panel["year"] >= 2025].copy()
    core_fit = fit_nonnegative_oriented(train_pre, CORE_FACTORS)
    growth_fit = fit_nonnegative_oriented(train_pre, CORE_GROWTH_FACTORS)
    price_fit = fit_price(train_pre)
    diag_common = common_test(diagnostic, CORE_GROWTH_FACTORS)
    diag_actual = diag_common["target"].to_numpy(dtype=float)

    diagnostic_metrics = {
        "commonTestN": int(len(diag_common)),
        "core3": score(
            diag_actual,
            predict_oriented(diag_common, CORE_FACTORS, core_fit),
        ),
        "core3PlusGrowth": score(
            diag_actual,
            predict_oriented(diag_common, CORE_GROWTH_FACTORS, growth_fit),
        ),
        "priceOnly": score(diag_actual, predict_price(diag_common, price_fit)),
        "warning": (
            "2025-2026 has already been inspected during model development; "
            "these scores are descriptive only."
        ),
    }

    coef_rows.extend(
        serialize_fit("core3", CORE_FACTORS, core_fit, "2022-2024_final")
    )
    coef_rows.extend(
        serialize_fit(
            "core3PlusGrowth",
            CORE_GROWTH_FACTORS,
            growth_fit,
            "2022-2024_final",
        )
    )

    cv_summary = {}
    for model in ("core3", "core3PlusGrowth", "priceOnly"):
        cv_summary[model] = {
            "meanContinuousMae": float(
                np.mean([fold[model]["continuous_mae"] for fold in fold_results])
            ),
            "meanRoundedMae": float(
                np.mean([fold[model]["rounded_mae"] for fold in fold_results])
            ),
            "meanRoundedExactMatch": float(
                np.mean(
                    [fold[model]["rounded_exact_match"] for fold in fold_results]
                )
            ),
        }

    summary = {
        "sourceBasis": {
            "officialArticle": "2026-04-14 第444期直播回放：螺丝钉星级指标怎么用",
            "quantitativeCoreDisclosed": [
                "巴菲特指标：上市公司总市值/GDP",
                "股债性价比：中证全指盈利收益率 vs 10年期国债收益率",
                "市净率百分位",
            ],
            "alsoMentions": [
                "盈利增长",
                "融资余额",
                "成交量及百分位",
                "新股发行数和破发率",
                "老基金规模",
                "新基金规模",
                "新增开户数",
                "限购基金占比",
                "市场消息",
            ],
        },
        "method": (
            "Factor-only, economically sign-constrained linear model. Each factor is "
            "standardized using training data, oriented so larger means cheaper/higher-star, "
            "then fitted with nonnegative coefficients. No price is included in the disclosed "
            "factor models. Price-only is evaluated on the identical complete-case test dates."
        ),
        "targetPolicy": (
            "Use fine exact stars from 2022-05-31 onward, avoiding early-2022 coarse half-star buckets."
        ),
        "coverage": coverage(panel),
        "expandingPreHoldoutFolds": fold_results,
        "preHoldoutSummary": cv_summary,
        "observed2025_2026Diagnostic": diagnostic_metrics,
        "cleanConfirmationRule": (
            "Because the disclosed-factor architecture was proposed after inspecting the "
            "first 2026-09/10 prospective window, any clean confirmation must use future dates "
            "strictly after 2026-10-09 with all model choices frozen beforehand."
        ),
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    pd.concat(pred_frames, ignore_index=True).to_csv(
        PRED_OUTPUT, index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(coef_rows).to_csv(COEF_OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
