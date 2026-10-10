from __future__ import annotations

import itertools
import json
import math

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, prepare_panel

SUMMARY_OUTPUT = DERIVED / "p2_disclosed_factor_spec_search_summary.json"
CANDIDATES_OUTPUT = DERIVED / "p2_disclosed_factor_spec_search_candidates.csv"
COEFFICIENTS_OUTPUT = DERIVED / "p2_disclosed_factor_spec_search_coefficients.csv"

INDEX_NAMES = {"1000002": "A股全指", "000985": "中证全指"}
WEIGHTINGS = ("mcw", "ew", "ewpvo", "avg", "median")
PB_WINDOWS = (5, 10, 20)
BUFFETT_COLUMNS = ("buffett_mc_to_gdp", "buffett_mc_om_to_gdp")


def weighted_lstsq(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    root = np.sqrt(w)
    return np.linalg.lstsq(x * root[:, None], y * root, rcond=None)[0]


def fine_exact(frame: pd.DataFrame) -> pd.DataFrame:
    use = frame[
        frame["target_status"].eq("exact")
        & pd.to_numeric(frame["target_target_mid"], errors="coerce").notna()
        & (pd.to_datetime(frame["date"]) >= pd.Timestamp("2022-05-31"))
    ].copy()
    use["target"] = pd.to_numeric(use["target_target_mid"], errors="coerce")
    use["weight"] = pd.to_numeric(use["target_training_weight"], errors="coerce").fillna(1.0)
    use["year"] = pd.to_datetime(use["date"]).dt.year
    return use


def spec(weighting: str, buffett: str, pb_window: int) -> tuple[list[str], list[int]]:
    return (
        [
            buffett,
            f"equity_bond_ratio_{weighting}",
            f"pb_{weighting}_pct_{pb_window}y_local",
        ],
        [-1, +1, -1],
    )


def fit_monotone(
    train: pd.DataFrame,
    features: list[str],
    directions: list[int],
) -> dict[str, object]:
    use = train.dropna(subset=features + ["target", "weight"]).copy()
    use = use[use["weight"] > 0]
    x = use[features].to_numpy(dtype=float)
    y = use["target"].to_numpy(dtype=float)
    w = use["weight"].to_numpy(dtype=float)

    means = np.average(x, axis=0, weights=w)
    var = np.average((x - means) ** 2, axis=0, weights=w)
    scales = np.sqrt(var)
    if np.any(scales <= 0) or np.any(~np.isfinite(scales)):
        raise ValueError("invalid feature scale")
    z = ((x - means) / scales) * np.asarray(directions, dtype=float)

    best = None
    for active_mask in itertools.product((False, True), repeat=len(features)):
        active = np.flatnonzero(active_mask)
        design = np.ones((len(use), 1 + len(active)), dtype=float)
        if len(active):
            design[:, 1:] = z[:, active]
        beta = weighted_lstsq(design, y, w)
        coefficients = np.zeros(len(features), dtype=float)
        if len(active):
            coefficients[active] = beta[1:]
        if np.any(coefficients < -1e-12):
            continue
        pred = beta[0] + z @ coefficients
        loss = float(np.average((pred - y) ** 2, weights=w))
        if best is None or loss < best["loss"]:
            best = {
                "loss": loss,
                "intercept": float(beta[0]),
                "coef": np.maximum(coefficients, 0),
                "means": means,
                "scales": scales,
                "directions": np.asarray(directions, dtype=float),
                "active": [features[i] for i in active],
                "n": int(len(use)),
            }
    if best is None:
        raise RuntimeError("monotone fit failed")
    return best


def predict(frame: pd.DataFrame, features: list[str], fit: dict[str, object]) -> np.ndarray:
    x = frame[features].to_numpy(dtype=float)
    z = ((x - np.asarray(fit["means"])) / np.asarray(fit["scales"])) * np.asarray(fit["directions"])
    return float(fit["intercept"]) + z @ np.asarray(fit["coef"])


def score(frame: pd.DataFrame, prediction: np.ndarray) -> dict[str, float | int]:
    actual = frame["target"].to_numpy(dtype=float)
    pred = np.asarray(prediction, dtype=float)
    mask = np.isfinite(actual) & np.isfinite(pred)
    err = np.abs(pred[mask] - actual[mask])
    rounded = np.round(pred[mask] / 0.1) * 0.1
    rerr = np.abs(rounded - actual[mask])
    return {
        "n": int(mask.sum()),
        "continuous_mae": float(err.mean()) if len(err) else math.nan,
        "rounded_mae": float(rerr.mean()) if len(rerr) else math.nan,
        "rounded_exact_match": float((rerr <= 1e-8).mean()) if len(rerr) else math.nan,
        "within_0_1": float((rerr <= 0.1000001).mean()) if len(rerr) else math.nan,
    }


def fit_price(train: pd.DataFrame) -> tuple[float, float]:
    use = train.dropna(subset=["log_close", "target", "weight"]).copy()
    x = use["log_close"].to_numpy(dtype=float)
    y = use["target"].to_numpy(dtype=float)
    w = use["weight"].to_numpy(dtype=float)
    beta = weighted_lstsq(np.column_stack([np.ones(len(use)), x]), y, w)
    return float(beta[0]), float(beta[1])


def price_predict(frame: pd.DataFrame, fit: tuple[float, float]) -> np.ndarray:
    return fit[0] + fit[1] * frame["log_close"].to_numpy(dtype=float)


def evaluate_spec(
    panel: pd.DataFrame,
    code: str,
    weighting: str,
    buffett: str,
    pb_window: int,
) -> dict[str, object]:
    features, directions = spec(weighting, buffett, pb_window)
    index_panel = panel[panel["stockCode"] == code].copy()

    fold_rows = []
    active_sets = []
    ebr_means = []
    coefficients = []
    for train_end, test_year in ((2022, 2023), (2023, 2024)):
        train = index_panel[index_panel["year"] <= train_end].copy()
        test = index_panel[index_panel["year"] == test_year].dropna(subset=features + ["target"]).copy()
        model = fit_monotone(train, features, directions)
        metric = score(test, predict(test, features, model))
        fold_rows.append(metric)
        active_sets.append("|".join(model["active"]))
        ebr = f"equity_bond_ratio_{weighting}"
        ebr_means.append(float(pd.to_numeric(train[ebr], errors="coerce").mean()))
        coefficients.append(np.asarray(model["coef"], dtype=float))

    return {
        "stockCode": code,
        "index_name": INDEX_NAMES[code],
        "weighting": weighting,
        "buffett_column": buffett,
        "pb_window_years": pb_window,
        "cv_continuous_mae": float(np.mean([x["continuous_mae"] for x in fold_rows])),
        "cv_rounded_mae": float(np.mean([x["rounded_mae"] for x in fold_rows])),
        "cv_rounded_exact_match": float(np.mean([x["rounded_exact_match"] for x in fold_rows])),
        "cv_within_0_1": float(np.mean([x["within_0_1"] for x in fold_rows])),
        "fold1_active": active_sets[0],
        "fold2_active": active_sets[1],
        "fold1_ebr_training_mean": ebr_means[0],
        "fold2_ebr_training_mean": ebr_means[1],
        "fold1_buffett_coef": float(coefficients[0][0]),
        "fold1_ebr_coef": float(coefficients[0][1]),
        "fold1_pb_coef": float(coefficients[0][2]),
        "fold2_buffett_coef": float(coefficients[1][0]),
        "fold2_ebr_coef": float(coefficients[1][1]),
        "fold2_pb_coef": float(coefficients[1][2]),
    }


def main() -> None:
    raw = prepare_panel()
    # prepare_panel currently filters to A股全指, so reload the committed CSV
    # for the two-index specification search while reusing the same target columns.
    path = DERIVED.parent / "features" / "star_model_panel_2022_2026.csv"
    full = pd.read_csv(path, low_memory=False)
    full["stockCode"] = full["stockCode"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    full["date"] = pd.to_datetime(full["date"]).dt.normalize()
    full["year"] = full["date"].dt.year
    full["log_close"] = np.log(pd.to_numeric(full["cp"], errors="coerce").where(lambda s: s > 0))

    # Replace embedded Target with the freshly rebuilt canonical Target.
    target_path = DERIVED / "star_target_2022_2026_unified.csv"
    target = pd.read_csv(target_path)
    target["date"] = pd.to_datetime(target["date"]).dt.normalize()
    target = target.rename(columns={c: f"target_{c}" for c in target.columns if c != "date"})
    full = full.drop(columns=[c for c in full.columns if c.startswith("target_")])
    full = full.merge(target, on="date", how="inner", validate="many_to_one")
    panel = fine_exact(full)

    candidate_rows = []
    for code in INDEX_NAMES:
        for weighting in WEIGHTINGS:
            for buffett in BUFFETT_COLUMNS:
                for pb_window in PB_WINDOWS:
                    candidate_rows.append(
                        evaluate_spec(panel, code, weighting, buffett, pb_window)
                    )

    candidates = pd.DataFrame(candidate_rows).sort_values(
        ["cv_rounded_mae", "cv_continuous_mae"],
        ignore_index=True,
    )
    candidates.to_csv(CANDIDATES_OUTPUT, index=False, encoding="utf-8-sig")

    best = candidates.iloc[0]
    best_features, best_directions = spec(
        str(best["weighting"]),
        str(best["buffett_column"]),
        int(best["pb_window_years"]),
    )
    index_panel = panel[panel["stockCode"] == str(best["stockCode"])].copy()

    # Fair price baseline on identical fine target policy and test folds.
    price_folds = []
    for train_end, test_year in ((2022, 2023), (2023, 2024)):
        train = index_panel[index_panel["year"] <= train_end]
        test = index_panel[index_panel["year"] == test_year]
        pfit = fit_price(train)
        price_folds.append(score(test, price_predict(test, pfit)))

    best_train = index_panel[index_panel["year"] <= 2024].copy()
    best_fit = fit_monotone(best_train, best_features, best_directions)
    coef_rows = []
    for feature, direction, coef, mean, scale in zip(
        best_features,
        best_directions,
        np.asarray(best_fit["coef"]),
        np.asarray(best_fit["means"]),
        np.asarray(best_fit["scales"]),
    ):
        coef_rows.append(
            {
                "feature": feature,
                "direction": direction,
                "oriented_standardized_coefficient": float(coef),
                "training_mean": float(mean),
                "training_sd": float(scale),
                "active": feature in best_fit["active"],
            }
        )
    pd.DataFrame(coef_rows).to_csv(COEFFICIENTS_OUTPUT, index=False, encoding="utf-8-sig")

    holdout = index_panel[index_panel["year"] >= 2025].dropna(subset=best_features + ["target"]).copy()
    holdout_metric = score(holdout, predict(holdout, best_features, best_fit))

    summary = {
        "targetPolicy": "fine exact stars from 2022-05-31 onward",
        "candidateCount": int(len(candidates)),
        "selectedSpecification": {
            "stockCode": str(best["stockCode"]),
            "indexName": str(best["index_name"]),
            "weighting": str(best["weighting"]),
            "buffettColumn": str(best["buffett_column"]),
            "pbWindowYears": int(best["pb_window_years"]),
            "features": best_features,
            "cvRoundedMae": float(best["cv_rounded_mae"]),
            "cvContinuousMae": float(best["cv_continuous_mae"]),
            "fold1Active": str(best["fold1_active"]),
            "fold2Active": str(best["fold2_active"]),
            "fold1EbrMean": float(best["fold1_ebr_training_mean"]),
            "fold2EbrMean": float(best["fold2_ebr_training_mean"]),
        },
        "priceOnlySameTargetPolicy": {
            "meanContinuousMae": float(np.mean([x["continuous_mae"] for x in price_folds])),
            "meanRoundedMae": float(np.mean([x["rounded_mae"] for x in price_folds])),
            "meanRoundedExactMatch": float(np.mean([x["rounded_exact_match"] for x in price_folds])),
        },
        "observed2025_2026Diagnostic": holdout_metric,
        "selectedFinalActiveFeatures": best_fit["active"],
        "notes": [
            "All 60 combinations are selected only on 2023/2024 expanding pre-holdout validation.",
            "This search is specifically intended to test whether the previous disclosed-factor failure was caused by choosing the wrong valuation weighting/index/Buffett/PB window.",
            "2025-2026 is diagnostic only.",
        ],
    }
    SUMMARY_OUTPUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
