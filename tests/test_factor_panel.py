from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[1]
PANEL_PATH = REPO / "data" / "features" / "star_model_panel_2022_2026.parquet"
PANEL_CSV = REPO / "data" / "features" / "star_model_panel_2022_2026.csv"


def load_panel() -> pd.DataFrame:
    if PANEL_PATH.exists():
        return pd.read_parquet(PANEL_PATH)
    panel = pd.read_csv(PANEL_CSV, low_memory=False)
    panel["stockCode"] = (
        panel["stockCode"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    date_columns = [
        column
        for column in panel.columns
        if column == "date" or column.endswith("_date") or column.endswith("_end")
    ]
    for column in date_columns:
        panel[column] = pd.to_datetime(panel[column], errors="coerce")
    return panel


def test_model_panel_has_two_complete_index_views_per_target() -> None:
    panel = load_panel()

    assert len(panel) == 2258
    assert not panel.duplicated(["stockCode", "date"]).any()
    assert panel.groupby("stockCode").size().to_dict() == {"000985": 1129, "1000002": 1129}
    assert pd.Timestamp("2025-10-08") not in set(panel["date"])


def test_critical_factor_coverage_is_complete() -> None:
    panel = load_panel()
    critical = [
        "buffett_mc_to_gdp",
        "buffett_mc_om_to_gdp",
        "equity_bond_ratio_mcw",
        "pb_mcw_pct_10y_local",
        "fin_q_ps_np_ttm_y2y",
        "fin_q_m_roe_ttm",
        "market_financingBalance",
        "investor_ni",
    ]

    assert panel[critical].notna().all().all()


def test_point_in_time_source_dates_never_exceed_observation_date() -> None:
    panel = load_panel()
    sources = [
        "debt_source_date",
        "gdp_available_date",
        "investor_available_date",
        "margin_source_date",
        "financial_report_date",
    ]

    for source in sources:
        assert not (panel[source].notna() & (panel[source] > panel["date"])).any()


def test_core_factor_formulas_reconcile() -> None:
    panel = load_panel()
    expected_buffett = panel["mc"] / panel["gdp_q_gdp_ttm"]
    expected_equity_bond = (1 / panel["pe_ttm.mcw"]) / panel["debt_tcm_y10"]

    assert np.allclose(panel["buffett_mc_to_gdp"], expected_buffett, equal_nan=True)
    assert np.allclose(panel["equity_bond_ratio_mcw"], expected_equity_bond, equal_nan=True)


def test_local_pb_percentile_reconciles_to_lixinger_long_percentile() -> None:
    panel = load_panel()
    valid = panel[["pb_mcw_pct_20y_local", "pb.y20.mcw.cvpos"]].dropna()
    mean_absolute_difference = (valid.iloc[:, 0] - valid.iloc[:, 1]).abs().mean()

    assert mean_absolute_difference < 0.001
