from __future__ import annotations

import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, REPO

PANEL = REPO / "data" / "features" / "star_model_panel_2022_2026.csv"
TARGET = DERIVED / "star_target_2022_2026_unified.csv"

SUMMARY_OUTPUT = DERIVED / "p2_official_20pct_star_rule_summary.json"
DETAIL_OUTPUT = DERIVED / "p2_official_20pct_star_rule_detail.csv"

LOG_1P2 = float(np.log(1.2))


def build_panel() -> pd.DataFrame:
    raw = pd.read_csv(PANEL, low_memory=False)
    raw["stockCode"] = (
        raw["stockCode"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    raw["date"] = pd.to_datetime(raw["date"]).dt.normalize()

    a = raw.loc[
        raw["stockCode"].eq("1000002"),
        ["date", "cp", "buffett_mc_to_gdp"],
    ].copy()

    csi = raw.loc[
        raw["stockCode"].eq("000985"),
        ["date", "pe_ttm.mcw", "pb.mcw"],
    ].rename(
        columns={
            "pe_ttm.mcw": "csi_pe",
            "pb.mcw": "csi_pb",
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

    for col in ("cp", "csi_pe", "csi_pb", "buffett_mc_to_gdp"):
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out["price_20pct_score"] = -np.log(out["cp"].where(out["cp"] > 0)) / LOG_1P2
    out["pe_20pct_score"] = -np.log(out["csi_pe"].where(out["csi_pe"] > 0)) / LOG_1P2
    out["pb_20pct_score"] = -np.log(out["csi_pb"].where(out["csi_pb"] > 0)) / LOG_1P2
    out["buffett_20pct_score"] = (
        -np.log(out["buffett_mc_to_gdp"].where(out["buffett_mc_to_gdp"] > 0))
        / LOG_1P2
    )

    return out[
        out["status"].eq("exact")
        & out["target"].notna()
        & out["date"].ge(pd.Timestamp("2022-05-31"))
    ].sort_values("date").reset_index(drop=True)


PROXIES = {
    "priceAsShortRunValuationProxy": "price_20pct_score",
    "csiPe": "pe_20pct_score",
    "csiPb": "pb_20pct_score",
    "buffett": "buffett_20pct_score",
}


def fit_intercept(train: pd.DataFrame, column: str) -> dict[str, float | int]:
    use = train.dropna(subset=[column, "target", "weight"]).copy()
    use = use[use["weight"] > 0]
    w = use["weight"].to_numpy(dtype=float)
    base = use[column].to_numpy(dtype=float)
    y = use["target"].to_numpy(dtype=float)
    intercept = float(np.average(y - base, weights=w))
    return {"intercept": intercept, "n": int(len(use))}


def predict(frame: pd.DataFrame, column: str, fit: dict[str, float | int]) -> np.ndarray:
    return float(fit["intercept"]) + frame[column].to_numpy(dtype=float)


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
        "maxRoundedError": float(rerr.max()),
    }


def implied_one_star_multiplier(frame: pd.DataFrame, raw_col: str) -> dict[str, float | int]:
    use = frame.dropna(subset=[raw_col, "target", "weight"]).copy()
    use = use[(use[raw_col] > 0) & (use["weight"] > 0)]
    x = -np.log(use[raw_col].to_numpy(dtype=float))
    y = use["target"].to_numpy(dtype=float)
    w = use["weight"].to_numpy(dtype=float)

    xbar = float(np.average(x, weights=w))
    ybar = float(np.average(y, weights=w))
    slope = float(np.sum(w * (x - xbar) * (y - ybar)) / np.sum(w * (x - xbar) ** 2))
    multiplier = float(np.exp(1.0 / slope)) if slope > 0 else float("nan")
    return {
        "n": int(len(use)),
        "freeSlopeStarPerNegLogValuation": slope,
        "impliedValuationMultiplierPerOneStar": multiplier,
        "impliedPercentMovePerOneStar": float((multiplier - 1.0) * 100.0)
        if np.isfinite(multiplier)
        else float("nan"),
    }


RAW_COLS = {
    "priceAsShortRunValuationProxy": "cp",
    "csiPe": "csi_pe",
    "csiPb": "csi_pb",
    "buffett": "buffett_mc_to_gdp",
}


def main() -> None:
    panel = build_panel()
    folds = []
    detail_rows = []

    for train_end, test_year in ((2022, 2023), (2023, 2024)):
        train = panel[panel["year"] <= train_end].copy()
        test = panel[panel["year"] == test_year].copy()
        fold = {"trainEnd": train_end, "testYear": test_year, "models": {}}

        for name, column in PROXIES.items():
            fit = fit_intercept(train, column)
            result = score(test.dropna(subset=[column]), predict(test.dropna(subset=[column]), column, fit))
            free = implied_one_star_multiplier(train, RAW_COLS[name])
            fold["models"][name] = {
                **result,
                "fixedRuleIntercept": fit["intercept"],
                "freeSlopeDiagnostic": free,
            }
            detail_rows.append({
                "fold": f"{train_end}->{test_year}",
                "proxy": name,
                "fixedRuleIntercept": fit["intercept"],
                **free,
                **result,
            })
        folds.append(fold)

    pre_summary = {}
    for name in PROXIES:
        pre_summary[name] = {
            "meanRoundedMae": float(
                np.mean([fold["models"][name]["roundedMae"] for fold in folds])
            ),
            "meanContinuousMae": float(
                np.mean([fold["models"][name]["continuousMae"] for fold in folds])
            ),
            "meanRoundedExactMatch": float(
                np.mean([fold["models"][name]["roundedExactMatch"] for fold in folds])
            ),
        }

    summary = {
        "officialStatement": (
            "Bank Screw wrote in 2023 that moving from just-out-of-5-star to just-out-of-4-star "
            "corresponds to roughly a 20% valuation increase, i.e. about 20% valuation movement "
            "per one star."
        ),
        "fixedRule": (
            "star = intercept - log(valuation_proxy)/log(1.2); only the intercept is fitted."
        ),
        "interpretation": (
            "If the 20%-per-star statement is the literal daily production rule for a proxy, "
            "the fixed-slope model should reproduce the modern 0.1-star series. Poor performance "
            "means the statement is better treated as a cycle-level approximation or the proxy "
            "does not match the internal composite valuation measure."
        ),
        "expandingFolds": folds,
        "preHoldoutSummary": pre_summary,
        "cleanPredictionRule": (
            "This is a mechanism test proposed after the first Sep-Oct 2026 future window. "
            "It is not eligible for clean prospective confirmation before dates strictly after 2026-10-09."
        ),
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(detail_rows).to_csv(DETAIL_OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
