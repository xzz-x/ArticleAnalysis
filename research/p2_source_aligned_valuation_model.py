from __future__ import annotations

import itertools
import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, REPO

PANEL = REPO / "data" / "features" / "star_model_panel_2022_2026.csv"
TARGET = DERIVED / "star_target_2022_2026_unified.csv"

SUMMARY_OUTPUT = DERIVED / "p2_source_aligned_valuation_model_summary.json"
COEF_OUTPUT = DERIVED / "p2_source_aligned_valuation_model_coefficients.csv"

MODELS = {
    "priceOnly": ["neg_log_price"],
    "earningsYieldOnly": ["earnings_yield_mcw"],
    "bookYieldOnly": ["book_yield_mcw"],
    "pePb": ["earnings_yield_mcw", "book_yield_mcw"],
    "pePbBuffett": ["earnings_yield_mcw", "book_yield_mcw", "neg_buffett"],
    "ebrPbBuffett": ["official_ebr", "book_yield_mcw", "neg_buffett"],
    "allSourceAlignedValuation": [
        "earnings_yield_mcw",
        "book_yield_mcw",
        "official_ebr",
        "neg_buffett",
    ],
    "pricePlusValuation": [
        "neg_log_price",
        "earnings_yield_mcw",
        "book_yield_mcw",
        "official_ebr",
        "neg_buffett",
    ],
}


def weighted_lstsq(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    root = np.sqrt(w)
    return np.linalg.lstsq(x * root[:, None], y * root, rcond=None)[0]


def build_panel() -> pd.DataFrame:
    raw = pd.read_csv(PANEL, low_memory=False)
    raw["stockCode"] = raw["stockCode"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    raw["date"] = pd.to_datetime(raw["date"]).dt.normalize()

    a = raw[raw["stockCode"].eq("1000002")].copy()
    csi_cols = [
        "date",
        "pe_ttm.mcw",
        "pb.mcw",
        "equity_bond_ratio_mcw",
    ]
    missing = [c for c in csi_cols if c not in raw.columns]
    if missing:
        raise RuntimeError(f"missing CSI valuation fields: {missing}")
    csi = raw[raw["stockCode"].eq("000985")][csi_cols].rename(
        columns={
            "pe_ttm.mcw": "csi_pe_ttm_mcw",
            "pb.mcw": "csi_pb_mcw",
            "equity_bond_ratio_mcw": "official_ebr",
        }
    )

    target = pd.read_csv(TARGET)
    target["date"] = pd.to_datetime(target["date"]).dt.normalize()
    target = target[["date", "target_mid", "status", "training_weight"]]

    out = a.merge(csi, on="date", how="left", validate="one_to_one")
    out = out.merge(target, on="date", how="inner", validate="one_to_one")
    out["target"] = pd.to_numeric(out["target_mid"], errors="coerce")
    out["weight"] = pd.to_numeric(out["training_weight"], errors="coerce").fillna(1.0)
    out["year"] = out["date"].dt.year

    pe = pd.to_numeric(out["csi_pe_ttm_mcw"], errors="coerce")
    pb = pd.to_numeric(out["csi_pb_mcw"], errors="coerce")
    out["earnings_yield_mcw"] = 1.0 / pe.where(pe > 0)
    out["book_yield_mcw"] = 1.0 / pb.where(pb > 0)
    out["official_ebr"] = pd.to_numeric(out["official_ebr"], errors="coerce")
    out["neg_buffett"] = -pd.to_numeric(out["buffett_mc_to_gdp"], errors="coerce")
    out["neg_log_price"] = -np.log(pd.to_numeric(out["cp"], errors="coerce").where(lambda s: s > 0))

    return out[
        out["status"].eq("exact")
        & out["target"].notna()
        & out["date"].ge(pd.Timestamp("2022-05-31"))
    ].sort_values("date").reset_index(drop=True)


def fit_nonnegative(train: pd.DataFrame, features: list[str]) -> dict[str, object]:
    use = train.dropna(subset=features + ["target", "weight"]).copy()
    use = use[use["weight"] > 0]
    x = use[features].to_numpy(dtype=float)
    y = use["target"].to_numpy(dtype=float)
    w = use["weight"].to_numpy(dtype=float)
    means = np.average(x, axis=0, weights=w)
    scales = np.sqrt(np.average((x - means) ** 2, axis=0, weights=w))
    if np.any(scales <= 0) or np.any(~np.isfinite(scales)):
        raise ValueError(f"bad scale: {features}")
    z = (x - means) / scales

    best = None
    for bits in itertools.product((False, True), repeat=len(features)):
        active = np.flatnonzero(bits)
        design = np.ones((len(use), 1 + len(active)))
        if len(active):
            design[:, 1:] = z[:, active]
        beta = weighted_lstsq(design, y, w)
        coef = np.zeros(len(features))
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
            }
    if best is None:
        raise RuntimeError("no feasible fit")
    return best


def predict(frame: pd.DataFrame, features: list[str], fit: dict[str, object]) -> np.ndarray:
    x = frame[features].to_numpy(dtype=float)
    z = (x - np.asarray(fit["means"])) / np.asarray(fit["scales"])
    return float(fit["intercept"]) + z @ np.asarray(fit["coef"])


def score(frame: pd.DataFrame, pred: np.ndarray) -> dict[str, float | int]:
    actual = frame["target"].to_numpy(dtype=float)
    pred = np.asarray(pred, dtype=float)
    mask = np.isfinite(actual) & np.isfinite(pred)
    err = np.abs(pred[mask] - actual[mask])
    rounded = np.round(pred[mask] / 0.1) * 0.1
    rerr = np.abs(rounded - actual[mask])
    return {
        "n": int(mask.sum()),
        "continuousMae": float(err.mean()),
        "roundedMae": float(rerr.mean()),
        "roundedExactMatch": float((rerr <= 1e-8).mean()),
        "roundedWithin0_1": float((rerr <= 0.1000001).mean()),
    }


def common_test(frame: pd.DataFrame) -> pd.DataFrame:
    all_features = sorted({x for vals in MODELS.values() for x in vals})
    return frame.dropna(subset=all_features + ["target"]).copy()


def serialize(fold: str, model: str, features: list[str], fit: dict[str, object]) -> list[dict[str, object]]:
    rows = []
    for feature, coef, mean, scale in zip(
        features,
        np.asarray(fit["coef"]),
        np.asarray(fit["means"]),
        np.asarray(fit["scales"]),
    ):
        rows.append({
            "fold": fold,
            "model": model,
            "feature": feature,
            "coefficient": float(coef),
            "trainingMean": float(mean),
            "trainingSd": float(scale),
            "active": feature in fit["active"],
        })
    return rows


def main() -> None:
    panel = build_panel()
    folds = []
    coef_rows = []

    for train_end, test_year in ((2022, 2023), (2023, 2024)):
        train = panel[panel["year"] <= train_end]
        test = common_test(panel[panel["year"] == test_year])
        result = {"trainEnd": train_end, "testYear": test_year, "n": int(len(test)), "models": {}}
        for name, features in MODELS.items():
            fit = fit_nonnegative(train, features)
            result["models"][name] = {**score(test, predict(test, features, fit)), "active": fit["active"]}
            coef_rows.extend(serialize(f"{train_end}->{test_year}", name, features, fit))
        folds.append(result)

    summary_cv = {}
    for name in MODELS:
        summary_cv[name] = {
            "meanContinuousMae": float(np.mean([f["models"][name]["continuousMae"] for f in folds])),
            "meanRoundedMae": float(np.mean([f["models"][name]["roundedMae"] for f in folds])),
            "meanRoundedExactMatch": float(np.mean([f["models"][name]["roundedExactMatch"] for f in folds])),
            "activeSets": [f["models"][name]["active"] for f in folds],
        }

    train = panel[panel["year"] <= 2024]
    observed = common_test(panel[panel["year"] >= 2025])
    observed_result = {}
    for name, features in MODELS.items():
        fit = fit_nonnegative(train, features)
        observed_result[name] = {**score(observed, predict(observed, features, fit)), "active": fit["active"]}
        coef_rows.extend(serialize("2022-2024_final", name, features, fit))

    summary = {
        "sourceAlignment": {
            "PE": "中证全指 000985 pe_ttm.mcw; mcw supported by official equity-bond calibration",
            "PB": "中证全指 000985 pb.mcw; raw PB valuation, not the unresolved four-style percentile composite",
            "equityBondRatio": "中证全指 000985 equity_bond_ratio_mcw; 9 official anchors MAPE ~0.8%",
            "buffett": "A股上市公司总市值/GDP -> 1000002 buffett_mc_to_gdp",
            "price": "A股全指 1000002 close",
        },
        "targetPolicy": "fine exact stars from 2022-05-31 onward",
        "modelConstraint": "all oriented features are constrained nonnegative; larger oriented value = cheaper/higher star",
        "expandingFolds": folds,
        "preHoldoutSummary": summary_cv,
        "observed2025_2026Diagnostic": observed_result,
        "cleanConfirmationRule": "Any model promoted from this analysis requires future confirmation strictly after 2026-10-09.",
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(coef_rows).to_csv(COEF_OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
