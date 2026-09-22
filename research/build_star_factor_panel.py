from __future__ import annotations

import bisect
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


REPO = Path(__file__).resolve().parents[1]
LIXINGER = REPO / "data" / "derived" / "lixinger"
FEATURES = REPO / "data" / "features"

TARGET_PATH = REPO / "data" / "derived" / "star_target_2022_2026_unified.csv"
DAILY_PARQUET = FEATURES / "star_factor_daily.parquet"
MODEL_PARQUET = FEATURES / "star_model_panel_2022_2026.parquet"
MODEL_CSV = FEATURES / "star_model_panel_2022_2026.csv"
AUDIT_PATH = FEATURES / "star_factor_panel_audit.json"

INDEX_NAMES = {"1000002": "A股全指", "000985": "中证全指"}
WEIGHTINGS = ("mcw", "ew", "ewpvo", "avg", "median")
PERCENTILE_WINDOWS = (1, 3, 5, 10, 20)


def parse_date(series: pd.Series) -> pd.Series:
    return (
        pd.to_datetime(series, errors="coerce", utc=True)
        .dt.tz_convert("Asia/Shanghai")
        .dt.tz_localize(None)
        .dt.normalize()
    )


def load_fundamental() -> pd.DataFrame:
    paths = sorted((LIXINGER / "index_fundamental").glob("*.parquet"))
    if len(paths) != 2:
        raise RuntimeError(f"expected two index fundamental files, found: {paths}")
    frames = [pd.read_parquet(path) for path in paths]
    df = pd.concat(frames, ignore_index=True, sort=False)
    df["date"] = parse_date(df["date"])
    df["stockCode"] = df["stockCode"].astype(str).str.zfill(6)
    df["index_name"] = df["stockCode"].map(INDEX_NAMES)
    if df["index_name"].isna().any():
        raise ValueError(f"unexpected index codes: {sorted(df.loc[df.index_name.isna(), 'stockCode'].unique())}")
    if df.duplicated(["stockCode", "date"]).any():
        raise ValueError("duplicate index/date rows in fundamentals")
    return df.sort_values(["stockCode", "date"]).reset_index(drop=True)


def merge_asof_global(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    right_on: str,
) -> pd.DataFrame:
    return pd.merge_asof(
        left.sort_values("date"),
        right.sort_values(right_on),
        left_on="date",
        right_on=right_on,
        direction="backward",
        allow_exact_matches=True,
    ).sort_values(["stockCode", "date"]).reset_index(drop=True)


def add_debt(panel: pd.DataFrame) -> pd.DataFrame:
    debt = pd.read_parquet(LIXINGER / "national_debt" / "national_debt.parquet")
    debt["debt_source_date"] = parse_date(debt.pop("date"))
    debt = debt.drop(columns=["areaCode"], errors="ignore")
    debt = debt.rename(columns={column: f"debt_{column}" for column in debt.columns if column != "debt_source_date"})
    result = merge_asof_global(panel, debt, right_on="debt_source_date")
    result["debt_age_days"] = (result["date"] - result["debt_source_date"]).dt.days
    return result


def add_gdp(panel: pd.DataFrame) -> pd.DataFrame:
    gdp = pd.read_parquet(LIXINGER / "gdp" / "gdp.parquet")
    gdp["gdp_period_end"] = parse_date(gdp.pop("date"))
    # LiXinger supplies the economic period but not the publication timestamp.
    # Forty-five days is a conservative release lag for every quarter.
    gdp["gdp_available_date"] = gdp["gdp_period_end"] + pd.Timedelta(days=45)
    gdp = gdp.drop(columns=["areaCode"], errors="ignore")
    gdp = gdp.rename(
        columns={
            column: f"gdp_{column.replace('.', '_')}"
            for column in gdp.columns
            if column not in {"gdp_period_end", "gdp_available_date"}
        }
    )
    result = merge_asof_global(panel, gdp, right_on="gdp_available_date")
    result["gdp_age_days"] = (result["date"] - result["gdp_available_date"]).dt.days
    return result


def add_investors(panel: pd.DataFrame) -> pd.DataFrame:
    investors = pd.read_parquet(LIXINGER / "investor" / "investor.parquet")
    investors["investor_period_end"] = parse_date(investors.pop("date"))
    weekly = investors.get("nni_w", pd.Series(index=investors.index, dtype=float)).notna()
    investors["investor_release_lag_days"] = np.where(weekly, 7, 20)
    investors["investor_available_date"] = investors["investor_period_end"] + pd.to_timedelta(
        investors["investor_release_lag_days"], unit="D"
    )
    investors = investors.drop(columns=["areaCode"], errors="ignore")
    investors = investors.rename(
        columns={
            column: f"investor_{column}"
            for column in investors.columns
            if column not in {"investor_period_end", "investor_available_date", "investor_release_lag_days"}
        }
    )
    result = merge_asof_global(panel, investors, right_on="investor_available_date")
    result["investor_age_days"] = (result["date"] - result["investor_available_date"]).dt.days
    return result


def add_margin(panel: pd.DataFrame) -> pd.DataFrame:
    margin = pd.read_parquet(LIXINGER / "margin" / "margin.parquet")
    margin["margin_source_date"] = parse_date(margin.pop("date"))
    margin = margin.rename(
        columns={column: f"market_{column}" for column in margin.columns if column != "margin_source_date"}
    )
    result = merge_asof_global(panel, margin, right_on="margin_source_date")
    result["margin_age_days"] = (result["date"] - result["margin_source_date"]).dt.days
    return result


def add_financials(panel: pd.DataFrame) -> pd.DataFrame:
    financials = pd.read_parquet(LIXINGER / "index_financials" / "index_financials.parquet")
    financials["stockCode"] = financials["stockCode"].astype(str).str.zfill(6)
    financials["financial_period_end"] = parse_date(financials.pop("date"))
    financials["financial_report_date"] = parse_date(financials["reportDate"])
    financials["financial_standard_date"] = parse_date(financials["standardDate"])
    financials = financials.drop(columns=["reportDate", "standardDate"], errors="ignore")
    financials = financials.rename(
        columns={
            column: f"fin_{column.replace('.', '_')}"
            for column in financials.columns
            if column
            not in {
                "stockCode",
                "financial_period_end",
                "financial_report_date",
                "financial_standard_date",
                "reportType",
                "currency",
            }
        }
    ).rename(columns={"reportType": "financial_report_type", "currency": "financial_currency"})

    # When annual and Q1 information share a report date, the later fiscal
    # period is the current point-in-time snapshot for TTM metrics.
    financials = financials.sort_values(["stockCode", "financial_report_date", "financial_period_end"])
    financials = financials.drop_duplicates(["stockCode", "financial_report_date"], keep="last")

    frames: list[pd.DataFrame] = []
    for code, left in panel.groupby("stockCode", sort=True):
        right = financials[financials["stockCode"] == code].drop(columns=["stockCode"])
        merged = pd.merge_asof(
            left.sort_values("date"),
            right.sort_values("financial_report_date"),
            left_on="date",
            right_on="financial_report_date",
            direction="backward",
            allow_exact_matches=True,
        )
        frames.append(merged)
    result = pd.concat(frames, ignore_index=True, sort=False).sort_values(["stockCode", "date"])
    result["financial_age_days"] = (result["date"] - result["financial_report_date"]).dt.days
    return result.reset_index(drop=True)


def rolling_percentile(values: Iterable[float], dates: Iterable[pd.Timestamp], years: int) -> np.ndarray:
    vals = np.asarray(list(values), dtype=float)
    date_index = pd.DatetimeIndex(list(dates))
    result = np.full(len(vals), np.nan)
    ordered: list[float] = []
    left = 0
    for i, value in enumerate(vals):
        cutoff = date_index[i] - pd.DateOffset(years=years)
        while left < i and date_index[left] < cutoff:
            old = vals[left]
            if np.isfinite(old):
                position = bisect.bisect_left(ordered, old)
                if position == len(ordered) or ordered[position] != old:
                    raise AssertionError("rolling percentile window lost synchronization")
                ordered.pop(position)
            left += 1
        if np.isfinite(value):
            bisect.insort(ordered, value)
            lo = bisect.bisect_left(ordered, value)
            hi = bisect.bisect_right(ordered, value)
            result[i] = (lo + 0.5 * (hi - lo)) / len(ordered)
    return result


def add_local_valuation_percentiles(panel: pd.DataFrame) -> pd.DataFrame:
    result = panel.copy()
    for code, index in result.groupby("stockCode", sort=False).groups.items():
        rows = result.loc[index].sort_values("date")
        for metric in ("pe_ttm", "pb"):
            for weighting in WEIGHTINGS:
                source = f"{metric}.{weighting}"
                if source not in rows:
                    continue
                for years in PERCENTILE_WINDOWS:
                    column = f"{metric}_{weighting}_pct_{years}y_local"
                    result.loc[rows.index, column] = rolling_percentile(rows[source], rows["date"], years)
    return result


def percentile_last(values: np.ndarray) -> float:
    clean = values[np.isfinite(values)]
    if len(clean) == 0 or not np.isfinite(values[-1]):
        return np.nan
    value = values[-1]
    less = np.sum(clean < value)
    equal = np.sum(clean == value)
    return float((less + 0.5 * equal) / len(clean))


def add_derived_features(panel: pd.DataFrame) -> pd.DataFrame:
    result = panel.copy()
    gdp = result["gdp_q_gdp_ttm"].where(result["gdp_q_gdp_ttm"] > 0)
    result["buffett_mc_to_gdp"] = result["mc"] / gdp
    result["buffett_mc_om_to_gdp"] = result["mc_om"] / gdp

    bond = result["debt_tcm_y10"].where(result["debt_tcm_y10"] > 0)
    for weighting in WEIGHTINGS:
        pe = result[f"pe_ttm.{weighting}"].where(result[f"pe_ttm.{weighting}"] > 0)
        earnings_yield = 1 / pe
        result[f"earnings_yield_{weighting}"] = earnings_yield
        result[f"equity_bond_ratio_{weighting}"] = earnings_yield / bond
        result[f"equity_bond_spread_{weighting}"] = earnings_yield - bond

    frames: list[pd.DataFrame] = []
    for _, group in result.groupby("stockCode", sort=False):
        group = group.sort_values("date").copy()
        for window in (20, 60, 120, 240):
            group[f"ta_ma_{window}"] = group["ta"].rolling(window, min_periods=max(5, window // 2)).mean()
        group["ta_median_240"] = group["ta"].rolling(240, min_periods=120).median()
        group["ta_to_median_240"] = group["ta"] / group["ta_median_240"]
        group["ta_pct_252"] = group["ta"].rolling(252, min_periods=120).apply(percentile_last, raw=True)
        group["to_r_pct_252"] = group["to_r"].rolling(252, min_periods=120).apply(percentile_last, raw=True)
        group["index_financing_balance_to_mc_om"] = group["fb"] / group["mc_om"]
        for window in (20, 60, 120):
            group[f"index_financing_balance_change_{window}"] = group["fb"].pct_change(window, fill_method=None)
        group["index_financing_net_purchase_sum_5"] = group["fnpa"].rolling(5, min_periods=3).sum()
        group["index_financing_net_purchase_sum_20"] = group["fnpa"].rolling(20, min_periods=10).sum()
        group["market_financing_balance_to_mc_om"] = group["market_financingBalance"] / group["mc_om"]
        for window in (20, 60, 120):
            group[f"market_financing_balance_change_{window}"] = group["market_financingBalance"].pct_change(
                window, fill_method=None
            )
        frames.append(group)
    return pd.concat(frames, ignore_index=True, sort=False).sort_values(["stockCode", "date"]).reset_index(drop=True)


def add_target(panel: pd.DataFrame) -> pd.DataFrame:
    target = pd.read_csv(TARGET_PATH)
    target["date"] = parse_date(target["date"])
    target = target.rename(
        columns={
            column: f"target_{column}"
            for column in target.columns
            if column != "date"
        }
    )
    return panel.merge(target, on="date", how="left", validate="many_to_one")


def date_string_columns(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    date_columns = [
        column
        for column in result.columns
        if column == "date" or column.endswith("_date") or column.endswith("_end")
    ]
    for column in date_columns:
        result[column] = parse_date(result[column]).dt.strftime("%Y-%m-%d")
    return result


def coverage_by_code(model: pd.DataFrame) -> dict[str, dict[str, int]]:
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
    result: dict[str, dict[str, int]] = {}
    for code, group in model.groupby("stockCode"):
        result[code] = {column: int(group[column].notna().sum()) for column in critical}
    return result


def assert_no_future_data(panel: pd.DataFrame) -> dict[str, int]:
    checks = {
        "debt": ("debt_source_date", "date"),
        "gdp": ("gdp_available_date", "date"),
        "investor": ("investor_available_date", "date"),
        "margin": ("margin_source_date", "date"),
        "financial": ("financial_report_date", "date"),
    }
    violations: dict[str, int] = {}
    for name, (source, observation) in checks.items():
        count = int((panel[source].notna() & (panel[source] > panel[observation])).sum())
        violations[name] = count
    if any(violations.values()):
        raise ValueError(f"future-data violations: {violations}")
    return violations


def main() -> None:
    panel = load_fundamental()
    panel = add_debt(panel)
    panel = add_gdp(panel)
    panel = add_investors(panel)
    panel = add_margin(panel)
    panel = add_financials(panel)
    panel = add_local_valuation_percentiles(panel)
    panel = add_derived_features(panel)
    panel = add_target(panel)

    violations = assert_no_future_data(panel)
    model = panel[panel["target_status"].notna()].copy()
    target_count = pd.read_csv(TARGET_PATH, usecols=["date"])["date"].nunique()
    expected_model_rows = target_count * len(INDEX_NAMES)
    if len(model) != expected_model_rows:
        counts = model.groupby("stockCode").size().to_dict()
        raise ValueError(f"target/factor join incomplete: expected {expected_model_rows}, got {len(model)} {counts}")

    FEATURES.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(DAILY_PARQUET, index=False)
    model.to_parquet(MODEL_PARQUET, index=False)
    date_string_columns(model).to_csv(MODEL_CSV, index=False, encoding="utf-8-sig")

    audit = {
        "dailyPanel": str(DAILY_PARQUET.relative_to(REPO)),
        "modelPanel": str(MODEL_PARQUET.relative_to(REPO)),
        "modelCsv": str(MODEL_CSV.relative_to(REPO)),
        "dailyRows": int(len(panel)),
        "dailyColumns": int(len(panel.columns)),
        "modelRows": int(len(model)),
        "modelColumns": int(len(model.columns)),
        "dateRangeByIndex": {
            code: {
                "first": group["date"].min().strftime("%Y-%m-%d"),
                "last": group["date"].max().strftime("%Y-%m-%d"),
                "rows": int(len(group)),
            }
            for code, group in panel.groupby("stockCode")
        },
        "targetRowsByIndex": model.groupby("stockCode").size().astype(int).to_dict(),
        "criticalCoverageByIndex": coverage_by_code(model),
        "futureDataViolations": violations,
        "availabilityPolicy": {
            "indexFundamental": "same trading date; target articles are published after market close",
            "nationalDebt": "latest source date on or before target date",
            "margin": "latest source date on or before target date",
            "financials": "actual LiXinger reportDate",
            "gdp": "period end plus 45 calendar days because API does not provide publication timestamp",
            "investorWeekly": "period end plus 7 calendar days",
            "investorMonthly": "period end plus 20 calendar days",
        },
        "localPercentileDefinition": "calendar windows; mid-rank empirical percentile including current observation",
    }
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
