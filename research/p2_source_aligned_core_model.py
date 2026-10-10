from __future__ import annotations

import itertools
import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, REPO

PANEL = REPO / "data" / "features" / "star_model_panel_2022_2026.csv"
TARGET = DERIVED / "star_target_2022_2026_unified.csv"

SUMMARY_OUTPUT = DERIVED / "p2_source_aligned_core_model_summary.json"
COEF_OUTPUT = DERIVED / "p2_source_aligned_core_model_coefficients.csv"
PRED_OUTPUT = DERIVED / "p2_source_aligned_core_model_predictions.csv"

# Every feature is oriented so larger = cheaper / higher-star.
MODELS = {
    "priceOnly": ["neg_log_price"],
    "officialEbrOnly": ["official_ebr"],
    "buffettEbr": ["neg_buffett", "official_ebr"],
    "priceEbr": ["neg_log_price", "official_ebr"],
    "priceBuffett": ["neg_log_price", "neg_buffett"],
    "priceBuffettEbr": ["neg_log_price", "neg_buffett", "official_ebr"],
    "priceBuffettEbrGrowth": [
        "neg_log_price",
        "neg_buffett",
        "official_ebr",
        "earnings_growth",
    ],
}


def weighted_lstsq(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    root = np.sqrt(w)
    return np.linalg.lstsq(x * root[:, None], y * root, rcond=None)[0]


def build_source_aligned_panel() -> pd.DataFrame:
    raw = pd.read_csv(PANEL, low_memory=False)
    raw["stockCode"] = (
        raw["stockCode"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    raw["date"] = pd.to_datetime(raw["date"]).dt.normalize()

    a = raw[raw["stockCode"].eq("1000002")].copy()
    csi = raw[raw["stockCode"].eq("000985")][
        ["date", "equity_bond_ratio_mcw"]
    ].rename(columns={"equity_bond_ratio_mcw": "official_ebr"})

    target = pd.read_csv(TARGET)
    target["date"] = pd.to_datetime(target["date"]).dt.normalize()
    target = target[["date", "target_mid", "status", "training_weight"]]

    out = a.merge(csi, on="date", how="left", validate="one_to_one")
    out = out.merge(target, on="date", how="inner", validate="one_to_one")

    out["target"] = pd.to_numeric(out["target_mid"], errors="coerce")
    out["weight"] = pd.to_numeric(out["training_weight"], errors="coerce").fillna(1.0)
    out["year"] = out["date"].dt.year
    out["log_price"] = np.log(pd.to_numeric(out["cp"], errors="coerce"))
    out["neg_log_price"] = -out["log_price"]
    out["neg_buffett"] = -pd.to_numeric(out["buffett_mc_to_gdp"], errors="coerce")
    out["official_ebr"] = pd.to_numeric(out["official_ebr"], errors="coerce")
    out["earnings_growth"] = pd.to_numeric(
        out["fin_q_ps_np_ttm_y2y"], errors="coerce"
    )

    return out[
        out["status"].eq("exact")
        & out["target"].notna()
        & out["date"].ge(pd.Timestamp("2022-05-31"))
    ].sort_values("date").reset_index(drop=True)


def fit_oriented(
    train: pd.DataFrame,
    features: list[str],
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
        raise ValueError(f"invalid scales for {features}")
    z = (x - means) / scales

    best = None
    for active_mask in itertools.product((False, True), repeat=len(features)):
        active = np.flatnonzero(active_mask)
        design = np.ones((len(use), 1 + len(active)), dtype=float)
        if len(active):
            design[:, 1:] = z[:, active]
        beta = weighted_lstsq(design, y, w)
        coef = np.zeros(len(features), dtype=float)
        if len(active):
            coef[active] = beta[1:]
        if np.any(coef < -1e-12):
            continue
        coef = np.maximum(coef, 0.0)
        pred = beta[0] + z @ coef
        loss = float(np.average((pred - y) ** 2, weights=w))
        if best is None or loss < best["loss"]:
            best = {
                "loss": loss,
                "intercept": float(beta[0]),
                "coef": coef,
                "means": means,
                "scales": scales,
                "active": [features[i] for i in active],
                "n": int(len(use)),
            }
    if best is None:
        raise RuntimeError("no feasible nonnegative fit")
    return best


def predict(frame: pd.DataFrame, features: list[str], fit: dict[str, object]) -> np.ndarray:
    x = frame[features].to_numpy(dtype=float)
    z = (x - np.asarray(fit["means"])) / np.asarray(fit["scales"])
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
        "continuous_mae": float(err.mean()) if len(err) else float("nan"),
        "rounded_mae": float(rerr.mean()) if len(rerr) else float("nan"),
        "rounded_exact_match": float((rerr <= 1e-8).mean()) if len(rerr) else float("nan"),
        "rounded_within_0_1": float((rerr <= 0.1000001).mean()) if len(rerr) else float("nan"),
    }


def common_test(frame: pd.DataFrame) -> pd.DataFrame:
    all_features = sorted({f for features in MODELS.values() for f in features})
    return frame.dropna(subset=all_features + ["target"]).copy()


def serialize_fit(
    fold: str,
    model_name: str,
    features: list[str],
    fit: dict[str, object],
) -> list[dict[str, object]]:
    rows = []
    for feature, coef, mean, scale in zip(
        features,
        np.asarray(fit["coef"]),
        np.asarray(fit["means"]),
        np.asarray(fit["scales"]),
    ):
        rows.append(
            {
                "fold": fold,
                "model": model_name,
                "feature": feature,
                "coefficient_standardized_oriented": float(coef),
                "training_mean": float(mean),
                "training_sd": float(scale),
                "active": feature in fit["active"],
            }
        )
    return rows


def main() -> None:
    panel = build_source_aligned_panel()

    fold_results = []
    coef_rows = []
    pred_rows = []

    for train_end, test_year in ((2022, 2023), (2023, 2024)):
        train = panel[panel["year"] <= train_end].copy()
        test = common_test(panel[panel["year"] == test_year].copy())
        row = {
            "trainEnd": train_end,
            "testYear": test_year,
            "commonTestN": int(len(test)),
            "models": {},
        }
        pred_frame = test[
            ["date", "target", "cp", "official_ebr", "buffett_mc_to_gdp", "earnings_growth"]
        ].copy()
        pred_frame["fold"] = f"{train_end}->{test_year}"

        for model_name, features in MODELS.items():
            fit = fit_oriented(train, features)
            pred = predict(test, features, fit)
            row["models"][model_name] = {
                **score(test, pred),
                "active": fit["active"],
            }
            pred_frame[f"pred_{model_name}"] = pred
            coef_rows.extend(
                serialize_fit(
                    f"{train_end}->{test_year}",
                    model_name,
                    features,
                    fit,
                )
            )

        fold_results.append(row)
        pred_rows.append(pred_frame)

    preholdout = {}
    for model_name in MODELS:
        preholdout[model_name] = {
            "meanContinuousMae": float(
                np.mean(
                    [
                        fold["models"][model_name]["continuous_mae"]
                        for fold in fold_results
                    ]
                )
            ),
            "meanRoundedMae": float(
                np.mean(
                    [
                        fold["models"][model_name]["rounded_mae"]
                        for fold in fold_results
                    ]
                )
            ),
            "meanRoundedExactMatch": float(
                np.mean(
                    [
                        fold["models"][model_name]["rounded_exact_match"]
                        for fold in fold_results
                    ]
                )
            ),
            "activeSets": [
                fold["models"][model_name]["active"] for fold in fold_results
            ],
        }

    # Descriptive only: this period has already been inspected.
    train_final = panel[panel["year"] <= 2024].copy()
    observed = common_test(panel[panel["year"] >= 2025].copy())
    observed_results = {}
    for model_name, features in MODELS.items():
        fit = fit_oriented(train_final, features)
        observed_results[model_name] = {
            **score(observed, predict(observed, features, fit)),
            "active": fit["active"],
        }
        coef_rows.extend(
            serialize_fit("2022-2024_final", model_name, features, fit)
        )

    summary = {
        "sourceAlignment": {
            "starPriceProxy": "A股全指 1000002 close",
            "buffett": "A股上市公司总市值/GDP -> 1000002 buffett_mc_to_gdp",
            "equityBondRatio": (
                "中证全指 000985 equity_bond_ratio_mcw; confirmed against 9 "
                "Bank Screw published values from 2024-10 to 2025-06"
            ),
            "pbPercentile": (
                "intentionally omitted: Bank Screw uses four style buckets "
                "(large-value, large-growth, small-value, small-growth), not one aggregate PB percentile"
            ),
        },
        "modelInterpretation": (
            "All predictors are oriented so larger means cheaper/higher-star and "
            "constrained to nonnegative coefficients. This tests whether source-aligned "
            "slow valuation inputs add stable information beyond the short-run price proxy."
        ),
        "fineTargetPolicy": "exact 0.1-star targets from 2022-05-31 onward",
        "expandingFolds": fold_results,
        "preHoldoutSummary": preholdout,
        "observed2025_2026Diagnostic": observed_results,
        "cleanConfirmationRule": (
            "Any architecture decision made from this analysis requires new confirmation "
            "strictly after 2026-10-09."
        ),
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(coef_rows).to_csv(COEF_OUTPUT, index=False, encoding="utf-8-sig")
    pd.concat(pred_rows, ignore_index=True).to_csv(
        PRED_OUTPUT, index=False, encoding="utf-8-sig"
    )
    SUMMARY_OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
