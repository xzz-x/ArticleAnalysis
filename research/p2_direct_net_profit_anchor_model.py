from __future__ import annotations

import itertools
import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, prepare_panel

SUMMARY_OUTPUT = DERIVED / "p2_direct_net_profit_anchor_summary.json"
COEF_OUTPUT = DERIVED / "p2_direct_net_profit_anchor_coefficients.csv"

NP_COLUMN = "fin_q_ps_np_ttm"

MODELS = {
    "priceOnly": ["neg_log_price"],
    "netProfitOnly": ["log_net_profit"],
    "pricePlusNetProfit": ["neg_log_price", "log_net_profit"],
}


def weighted_lstsq(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    root = np.sqrt(w)
    return np.linalg.lstsq(x * root[:, None], y * root, rcond=None)[0]


def build_panel() -> pd.DataFrame:
    panel = prepare_panel().copy()
    if NP_COLUMN not in panel.columns:
        raise RuntimeError(
            f"{NP_COLUMN} is not present in the factor panel; "
            "absolute net-profit history must be rebuilt before this test."
        )

    panel["target"] = pd.to_numeric(panel["target_target_mid"], errors="coerce")
    panel["weight"] = pd.to_numeric(panel["target_training_weight"], errors="coerce").fillna(1.0)
    panel["year"] = pd.to_datetime(panel["date"]).dt.year

    price = pd.to_numeric(panel["cp"], errors="coerce").where(lambda s: s > 0)
    net_profit = pd.to_numeric(panel[NP_COLUMN], errors="coerce").where(lambda s: s > 0)

    panel["neg_log_price"] = -np.log(price)
    panel["log_net_profit"] = np.log(net_profit)

    return panel[
        panel["target_status"].eq("exact")
        & panel["target"].notna()
        & panel["date"].ge(pd.Timestamp("2022-05-31"))
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
    rerr = np.abs(rounded - actual)
    return {
        "n": int(mask.sum()),
        "continuousMae": float(err.mean()),
        "roundedMae": float(rerr.mean()),
        "roundedExactMatch": float((rerr <= 1e-8).mean()),
        "roundedWithin0_1": float((rerr <= 0.1000001).mean()),
    }


def common_test(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.dropna(subset=["neg_log_price", "log_net_profit", "target"]).copy()


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
            "standardizedCoefficient": float(coef),
            "rawCoefficient": float(coef / scale),
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

    pre = {}
    for name in MODELS:
        pre[name] = {
            "meanContinuousMae": float(np.mean([x["models"][name]["continuousMae"] for x in folds])),
            "meanRoundedMae": float(np.mean([x["models"][name]["roundedMae"] for x in folds])),
            "meanRoundedExactMatch": float(np.mean([x["models"][name]["roundedExactMatch"] for x in folds])),
            "activeSets": [x["models"][name]["active"] for x in folds],
        }

    train = panel[panel["year"] <= 2024].copy()
    observed = common_test(panel[panel["year"] >= 2025].copy())
    observed_result = {}
    for name, features in MODELS.items():
        fit = fit_nonnegative(train, features)
        observed_result[name] = {
            **score(observed, predict(observed, features, fit)),
            "active": fit["active"],
        }
        coef_rows.extend(serialize("2022-2024_final", name, features, fit))

    summary = {
        "purpose": (
            "Test the author's long-run earnings explanation using the directly downloaded "
            "point-in-time aggregate net-profit TTM level rather than price/PE reconstruction."
        ),
        "netProfitDefinition": (
            "LiXinger index hybrid financial q.ps.np.ttm, merged only from actual reportDate onward."
        ),
        "targetPolicy": "fine exact stars from 2022-05-31 onward",
        "coefficientOrientation": (
            "-log(price) and +log(net profit) are constrained nonnegative; larger oriented values "
            "mean cheaper/higher star."
        ),
        "expandingFolds": folds,
        "preHoldoutSummary": pre,
        "observed2025_2026Diagnostic": observed_result,
        "cleanConfirmationRule": (
            "This explanatory architecture was proposed after the first Sep-Oct 2026 prospective "
            "window; any clean prediction confirmation requires dates strictly after 2026-10-09."
        ),
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(coef_rows).to_csv(COEF_OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
