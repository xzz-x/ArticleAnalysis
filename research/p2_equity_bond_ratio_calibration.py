from __future__ import annotations

import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, REPO

PANEL = REPO / "data" / "features" / "star_model_panel_2022_2026.csv"
ANCHORS = REPO / "data" / "verified" / "bank_screw_equity_bond_ratio_anchors_2024_2025.csv"

DETAIL_OUTPUT = DERIVED / "p2_equity_bond_ratio_calibration_detail.csv"
CANDIDATE_OUTPUT = DERIVED / "p2_equity_bond_ratio_calibration_candidates.csv"
SUMMARY_OUTPUT = DERIVED / "p2_equity_bond_ratio_calibration_summary.json"

INDEX_NAMES = {"1000002": "A股全指", "000985": "中证全指"}
WEIGHTINGS = ("mcw", "ew", "ewpvo", "avg", "median")


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    panel = pd.read_csv(PANEL, low_memory=False)
    panel["stockCode"] = (
        panel["stockCode"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()

    anchors = pd.read_csv(ANCHORS)
    anchors["date"] = pd.to_datetime(anchors["date"]).dt.normalize()
    anchors["official_equity_bond_ratio"] = pd.to_numeric(
        anchors["official_equity_bond_ratio"], errors="raise"
    )
    return panel, anchors


def candidate_detail(
    panel: pd.DataFrame,
    anchors: pd.DataFrame,
    code: str,
    weighting: str,
) -> pd.DataFrame:
    ratio_col = f"equity_bond_ratio_{weighting}"
    pe_col = f"pe_ttm.{weighting}"
    needed = ["date", "stockCode", "debt_tcm_y10", ratio_col, pe_col]
    missing = [c for c in needed if c not in panel.columns]
    if missing:
        raise RuntimeError(f"missing panel fields for {code}/{weighting}: {missing}")

    right = panel.loc[panel["stockCode"].eq(code), needed].copy()
    out = anchors.merge(right, on="date", how="left", validate="one_to_one")
    out["index_code"] = code
    out["index_name"] = INDEX_NAMES[code]
    out["weighting"] = weighting

    out["panel_ratio_raw"] = pd.to_numeric(out[ratio_col], errors="coerce")
    out["panel_ratio_x100"] = out["panel_ratio_raw"] * 100.0
    pe = pd.to_numeric(out[pe_col], errors="coerce")
    debt = pd.to_numeric(out["debt_tcm_y10"], errors="coerce")
    out["pe_ttm"] = pe
    out["bond_yield_panel_units"] = debt
    out["earnings_yield_decimal"] = 1.0 / pe
    out["ratio_recomputed_raw"] = out["earnings_yield_decimal"] / debt
    out["ratio_recomputed_pct_corrected"] = (
        out["earnings_yield_decimal"] * 100.0 / debt
    )

    official = out["official_equity_bond_ratio"]
    out["raw_error"] = out["panel_ratio_raw"] - official
    out["x100_error"] = out["panel_ratio_x100"] - official
    out["pct_corrected_error"] = out["ratio_recomputed_pct_corrected"] - official
    return out


def summarize(detail: pd.DataFrame) -> dict[str, object]:
    use = detail.dropna(
        subset=["official_equity_bond_ratio", "panel_ratio_raw", "panel_ratio_x100"]
    ).copy()
    official = use["official_equity_bond_ratio"].to_numpy(dtype=float)
    raw = use["panel_ratio_raw"].to_numpy(dtype=float)
    scaled = use["panel_ratio_x100"].to_numpy(dtype=float)

    def metrics(values: np.ndarray) -> dict[str, float]:
        err = values - official
        rel = np.abs(err) / official
        if len(values) > 1 and np.std(values) > 0 and np.std(official) > 0:
            corr = float(np.corrcoef(values, official)[0, 1])
        else:
            corr = float("nan")
        return {
            "mae": float(np.mean(np.abs(err))),
            "rmse": float(np.sqrt(np.mean(err**2))),
            "meanAbsolutePctError": float(np.mean(rel)),
            "bias": float(np.mean(err)),
            "correlation": corr,
        }

    return {
        "n": int(len(use)),
        "raw": metrics(raw),
        "x100": metrics(scaled),
        "meanPanelBondYieldUnits": float(
            pd.to_numeric(use["bond_yield_panel_units"], errors="coerce").mean()
        ),
        "meanPe": float(pd.to_numeric(use["pe_ttm"], errors="coerce").mean()),
    }


def main() -> None:
    panel, anchors = load()

    detail_frames = []
    candidate_rows = []
    summaries: dict[str, object] = {}
    for code in INDEX_NAMES:
        for weighting in WEIGHTINGS:
            detail = candidate_detail(panel, anchors, code, weighting)
            detail_frames.append(detail)
            metrics = summarize(detail)
            key = f"{code}:{weighting}"
            summaries[key] = metrics
            candidate_rows.append(
                {
                    "stockCode": code,
                    "index_name": INDEX_NAMES[code],
                    "weighting": weighting,
                    "n": metrics["n"],
                    "raw_mae": metrics["raw"]["mae"],
                    "raw_mape": metrics["raw"]["meanAbsolutePctError"],
                    "x100_mae": metrics["x100"]["mae"],
                    "x100_mape": metrics["x100"]["meanAbsolutePctError"],
                    "x100_bias": metrics["x100"]["bias"],
                    "x100_correlation": metrics["x100"]["correlation"],
                    "mean_bond_yield_panel_units": metrics["meanPanelBondYieldUnits"],
                    "mean_pe": metrics["meanPe"],
                }
            )

    detail_all = pd.concat(detail_frames, ignore_index=True)
    candidates = pd.DataFrame(candidate_rows)
    candidates = candidates.sort_values(["raw_mae", "raw_mape"], ignore_index=True)
    best_raw = candidates.iloc[0]
    best_x100 = candidates.sort_values(["x100_mae", "x100_mape"], ignore_index=True).iloc[0]

    best_detail = detail_all[
        detail_all["index_code"].eq(best_raw["stockCode"])
        & detail_all["weighting"].eq(best_raw["weighting"])
    ].copy()

    ratio_of_scales = (
        best_detail["official_equity_bond_ratio"]
        / best_detail["panel_ratio_raw"]
    ).replace([np.inf, -np.inf], np.nan).dropna()

    summary = {
        "sourceDefinition": (
            "Bank Screw states equity-bond attractiveness is CSI All Share earnings yield "
            "divided by China 10Y government-bond yield; method one (ratio) is used in the "
            "bull/bear signal board."
        ),
        "officialAnchorCount": int(len(anchors)),
        "officialDateRange": [
            anchors["date"].min().strftime("%Y-%m-%d"),
            anchors["date"].max().strftime("%Y-%m-%d"),
        ],
        "sourceAlignedBestRawMatch": {
            "stockCode": str(best_raw["stockCode"]),
            "indexName": str(best_raw["index_name"]),
            "weighting": str(best_raw["weighting"]),
            "mae": float(best_raw["raw_mae"]),
            "mape": float(best_raw["raw_mape"]),
            "correlation": float(
                summaries[f"{best_raw['stockCode']}:{best_raw['weighting']}"]["raw"]["correlation"]
            ),
            "verdict": (
                "confirmed_source_aligned_proxy"
                if str(best_raw["stockCode"]) == "000985"
                and str(best_raw["weighting"]) == "mcw"
                and float(best_raw["raw_mape"]) < 0.02
                else "closest_proxy_only"
            ),
        },
        "bestX100Diagnostic": {
            "stockCode": str(best_x100["stockCode"]),
            "indexName": str(best_x100["index_name"]),
            "weighting": str(best_x100["weighting"]),
            "mae": float(best_x100["x100_mae"]),
            "mape": float(best_x100["x100_mape"]),
        },
        "unitAudit": {
            "meanBondYieldPanelUnitsForBest": float(best_raw["mean_bond_yield_panel_units"]),
            "medianOfficialToRawRatio": float(ratio_of_scales.median()),
            "meanOfficialToRawRatio": float(ratio_of_scales.mean()),
            "expectedIfBondYieldStoredInPercentagePoints": 100.0,
            "verdict": (
                "panel_raw_units_already_match_official_ratio"
                if abs(float(ratio_of_scales.median()) - 1.0) < 0.05
                else (
                    "panel_equity_bond_ratio_has_percent_unit_scale_bug"
                    if abs(float(ratio_of_scales.median()) - 100.0) < 15.0
                    else "scale_or_proxy_mismatch"
                )
            ),
        },
        "allCandidates": summaries,
        "researchImplication": (
            "Use author-published numeric anchors to choose the valuation proxy. Do not "
            "select the equity-bond-ratio weighting by star-fit alone."
        ),
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    detail_all.to_csv(DETAIL_OUTPUT, index=False, encoding="utf-8-sig")
    candidates.to_csv(CANDIDATE_OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
