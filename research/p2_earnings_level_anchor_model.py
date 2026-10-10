from __future__ import annotations

import itertools
import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, REPO

PANEL = REPO / "data" / "features" / "star_model_panel_2022_2026.csv"
TARGET = DERIVED / "star_target_2022_2026_unified.csv"

SUMMARY_OUTPUT = DERIVED / "p2_earnings_level_anchor_model_summary.json"
COEF_OUTPUT = DERIVED / "p2_earnings_level_anchor_model_coefficients.csv"

MODELS = {
    "priceOnly": ["neg_log_price"],
    "earningsLevelOnly": ["log_earnings_level"],
    "logValuationOnly": ["log_earnings_yield"],
    "pricePlusEarningsLevel": ["neg_log_price", "log_earnings_level"],
}

def weighted_lstsq(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    root = np.sqrt(w)
    return np.linalg.lstsq(x * root[:, None], y * root, rcond=None)[0]


def build_panel() -> pd.DataFrame:
    raw = pd.read_csv(PANEL, low_memory=False)
    raw["stockCode"] = (
        raw["stockCode"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    raw["date"] = pd.to_datetime(raw["date"]).dt.normalize()

    a = raw[raw["stockCode"].eq("1000002")].copy()
    csi = raw.loc[
        raw["stockCode"].eq("000985"),
        ["date", "pe_ttm.mcw"],
    ].rename(columns={"pe_ttm.mcw": "csi_pe_ttm_mcw"})

    target = pd.read_csv(TARGET)
    target["date"] = pd.to_datetime(target["date"]).dt.normalize()
    target = target[["date", "target_mid", "status", "training_weight"]]

    out = a.merge(csi, on="date", how="left", validate="one_to_one")
    out = out.merge(target, on="date", how="inner", validate="one_to_one")
    out["target"] = pd.to_numeric(out["target_mid"], errors="coerce")
    out["weight"] = pd.to_numeric(out["training_weight"], errors="coerce").fillna(1.0)
    out["year"] = out["date"].dt.year

    price = pd.to_numeric(out["cp"], errors="coerce").where(lambda s: s > 0)
    pe = pd.to_numeric(out["csi_pe_ttm_mcw"], errors="coerce").where(lambda s: s > 0)

    # Economic decomposition:
    # index level ~= valuation multiple * aggregate earnings level.
    out["neg_log_price"] = -np.log(price)
    out["log_earnings_level"] = np.log(price / pe)
    out["log_earnings_yield"] = -np.log(pe)

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
    if np.any(~np.isfinite(scales)) or np.any(scales <= 0):
        raise ValueError(f"invalid scales for {features}: {scales}")
    z = (x - means) / scales

    best = None
    for bits in itertools.product((False, True), repeat=len(features)):
        active = np.flatnonzero(bits)
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
        candidate = {
            "loss": loss,
            "intercept": float(beta[0]),
            "coef": coef,
            "means": means,
            "scales": scales,
            "active": [features[i] for i in active],
            "n": int(len(use)),
        }
        if best is None or loss < best["loss"]:
            best = candidate
    if best is None:
        raise RuntimeError("no feasible nonnegative fit")
    return best


def predict(frame: pd.DataFrame, features: list[str], fit: dict[str, object]) -> np.ndarray:
    x = frame[features].to_numpy(dtype=float)
    z = (x - np.asarray(fit["means"])) / np.asarray(fit["scales"])
    return float(fit["intercept"]) + z @ np.asarray(fit["coef"])


def score(frame: pd.DataFrame, pred: np.ndarray) -> dict[str, float | int]:
    actual = frame["target"].to_numpy(dtype=float)
    pred = np.asarray(pred, dtype=float)
    mask = np.isfinite(actual) & np.isfinite(pred)
    actual = actual[mask]
    pred = pred[mask]
    err = np.abs(pred - actual)
    rounded = np.round(pred / 0.1) * 0.1
    rounded_err = np.abs(rounded - actual)
    return {
        "n": int(mask.sum()),
        "continuousMae": float(err.mean()),
        "roundedMae": float(rounded_err.mean()),
        "roundedExactMatch": float((rounded_err <= 1e-8).mean()),
        "roundedWithin0_1": float((rounded_err <= 0.1000001).mean()),
    }


def common_test(frame: pd.DataFrame) -> pd.DataFrame:
    needed = sorted({feature for features in MODELS.values() for feature in features})
    return frame.dropna(subset=needed + ["target"]).copy()


def serialize(fold: str, model: str, features: list[str], fit: dict[str, object]) -> list[dict[str, object]]:
    rows = []
    for feature, coef, mean, scale in zip(
        features,
        np.asarray(fit["coef"]),
        np.asarray(fit["means"]),
        np.asarray(fit["scales"]),
    ):
        # Convert standardized coefficient back to raw-variable coefficient.
        raw_coef = float(coef / scale)
        rows.append(
            {
                "fold": fold,
                "model": model,
                "feature": feature,
                "standardizedCoefficient": float(coef),
                "rawCoefficient": raw_coef,
                "trainingMean": float(mean),
                "trainingSd": float(scale),
                "active": feature in fit["active"],
            }
        )
    return rows


def main() -> None:
    panel = build_panel()
    folds = []
    coef_rows = []

    for train_end, test_year in ((2022, 2023), (2023, 2024)):
        train = panel[panel["year"] <= train_end].copy()
        test = common_test(panel[panel["year"] == test_year].copy())
        fold = {"trainEnd": train_end, "testYear": test_year, "n": int(len(test)), "models": {}}
        for name, features in MODELS.items():
            fit = fit_nonnegative(train, features)
            fold["models"][name] = {
                **score(test, predict(test, features, fit)),
                "active": fit["active"],
            }
            coef_rows.extend(serialize(f"{train_end}->{test_year}", name, features, fit))
        folds.append(fold)

    pre_summary = {}
    for name in MODELS:
        pre_summary[name] = {
            "meanContinuousMae": float(
                np.mean([fold["models"][name]["continuousMae"] for fold in folds])
            ),
            "meanRoundedMae": float(
                np.mean([fold["models"][name]["roundedMae"] for fold in folds])
            ),
            "meanRoundedExactMatch": float(
                np.mean([fold["models"][name]["roundedExactMatch"] for fold in folds])
            ),
            "activeSets": [fold["models"][name]["active"] for fold in folds],
        }

    train = panel[panel["year"] <= 2024].copy()
    observed = common_test(panel[panel["year"] >= 2025].copy())
    observed_result = {}
    final_fits = {}
    for name, features in MODELS.items():
        fit = fit_nonnegative(train, features)
        final_fits[name] = fit
        observed_result[name] = {
            **score(observed, predict(observed, features, fit)),
            "active": fit["active"],
        }
        coef_rows.extend(serialize("2022-2024_final", name, features, fit))

    combined_fit = final_fits["pricePlusEarningsLevel"]
    combined_rows = serialize(
        "2022-2024_final",
        "pricePlusEarningsLevel",
        MODELS["pricePlusEarningsLevel"],
        combined_fit,
    )
    raw = {row["feature"]: row["rawCoefficient"] for row in combined_rows}

    summary = {
        "economicHypothesis": (
            "Bank Screw states that the higher CSI All Share point level compatible with "
            "the same star state over long horizons comes from listed-company earnings growth. "
            "This model tests aggregate earnings LEVEL directly: earnings_level = index_price / PE."
        ),
        "targetPolicy": "fine exact 0.1-star targets from 2022-05-31 onward",
        "dataDefinition": {
            "price": "A股全指 1000002 close",
            "PE": "中证全指 000985 pe_ttm.mcw",
            "earningsLevel": "A股全指 close / 中证全指 pe_ttm.mcw",
            "logValuationOnly": "-log(PE), equivalent to log earnings yield",
        },
        "modelConstraint": (
            "All coefficients are sign-constrained nonnegative after orienting -log(price) "
            "and +log(earnings level) so larger means cheaper/higher star."
        ),
        "expandingFolds": folds,
        "preHoldoutSummary": pre_summary,
        "observed2025_2026Diagnostic": observed_result,
        "finalPricePlusEarningsRawCoefficients": raw,
        "pureValuationRestriction": (
            "If star were exactly a linear function of -log(PE), the raw coefficients on "
            "-log(price) and +log(earnings_level) would be equal. Their empirical difference "
            "is a diagnostic, not a parameter-tuning target."
        ),
        "cleanConfirmationRule": (
            "This architecture was proposed after the first 2026-09/10 prospective window "
            "was inspected. Any clean confirmation requires dates strictly after 2026-10-09."
        ),
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(coef_rows).to_csv(COEF_OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
