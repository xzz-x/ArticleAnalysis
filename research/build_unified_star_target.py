from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


REPO = Path(__file__).resolve().parents[1]
VERIFIED = REPO / "data" / "verified"
DERIVED = REPO / "data" / "derived"

OUTPUT = DERIVED / "star_target_2022_2026_unified.csv"
AUDIT_OUTPUT = DERIVED / "star_target_2022_2026_audit.json"
CONFLICT_OUTPUT = DERIVED / "star_target_2025_source_conflicts.csv"
EXCLUSION_OUTPUT = DERIVED / "star_target_2022_2026_exclusions.csv"

OUTPUT_COLUMNS = [
    "date",
    "star",
    "star_low",
    "star_high",
    "target_mid",
    "status",
    "training_weight",
    "evidence_confidence",
    "market",
    "realtime_or_backfilled",
    "source",
    "source_priority",
    "evidence_method",
    "evidence",
    "review_status",
    "source_url",
    "source_file",
    "notes",
]

STATUS_BASE_WEIGHT = {"exact": 1.0, "range": 0.55, "approx": 0.50, "threshold": 0.0}
HISTORIC_CONFIDENCE = {"exact": 0.90, "range": 0.75, "approx": 0.60}
KNOWN_CLOSED_DIRECT_DATES = {
    "2025-10-08": "National Day holiday; both A-share market indices have no trading observation",
}


def _number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _text_column(df: pd.DataFrame, name: str) -> pd.Series:
    if name in df:
        return df[name].fillna("").astype(str)
    return pd.Series("", index=df.index, dtype="object")


def _finalize(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    result["date"] = pd.to_datetime(result["date"]).dt.strftime("%Y-%m-%d")
    for column in ("star", "star_low", "star_high", "target_mid", "training_weight", "evidence_confidence"):
        result[column] = _number(result[column])

    point = result["star"].notna()
    missing_low = point & result["star_low"].isna()
    missing_high = point & result["star_high"].isna()
    result.loc[missing_low, "star_low"] = result.loc[missing_low, "star"].to_numpy()
    result.loc[missing_high, "star_high"] = result.loc[missing_high, "star"].to_numpy()
    bounded = result["star_low"].notna() & result["star_high"].notna()
    result.loc[bounded, "target_mid"] = (
        result.loc[bounded, "star_low"] + result.loc[bounded, "star_high"]
    ) / 2

    result = result[OUTPUT_COLUMNS].sort_values("date").reset_index(drop=True)
    if result["date"].duplicated().any():
        duplicates = result.loc[result["date"].duplicated(False), "date"].tolist()
        raise ValueError(f"duplicate unified target dates: {duplicates}")
    invalid_bounds = result["star_low"].notna() & result["star_high"].notna() & (
        result["star_low"] > result["star_high"]
    )
    if invalid_bounds.any():
        raise ValueError(f"invalid target bounds: {result.loc[invalid_bounds, 'date'].tolist()}")
    return result


def load_historic_year(year: int) -> pd.DataFrame:
    path = VERIFIED / f"daily_star_{year}.csv"
    source = pd.read_csv(path)
    status = source["status"].astype(str)
    confidence = status.map(HISTORIC_CONFIDENCE)
    if confidence.isna().any():
        raise ValueError(f"unexpected {year} statuses: {sorted(status[confidence.isna()].unique())}")

    result = pd.DataFrame(
        {
            "date": source["date"],
            "star": _number(source["star"]),
            "star_low": _number(source["star_low"]),
            "star_high": _number(source["star_high"]),
            "target_mid": pd.NA,
            "status": status,
            "training_weight": status.map(STATUS_BASE_WEIGHT) * confidence,
            "evidence_confidence": confidence,
            "market": "A股",
            "realtime_or_backfilled": "realtime",
            "source": f"verified/daily_star_{year}.csv",
            "source_priority": "historic_verified_annual",
            "evidence_method": _text_column(source, "method"),
            "evidence": _text_column(source, "evidence"),
            "review_status": "historic_verified",
            "source_url": "",
            "source_file": _text_column(source, "source_file"),
            "notes": _text_column(source, "star_text"),
        }
    )
    return _finalize(result)


def load_historical_article_targets(
    valid_trading_dates: set[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load optional 2022-2024 direct article evidence produced by the historical pipeline.

    The verified annual files are also the market-calendar authority for these
    years. Holiday/weekend articles may discuss a reference star state but must
    not create a new daily realtime Target.
    """
    exact_path = DERIVED / "star_target_historical_direct.csv"
    review_path = DERIVED / "star_target_historical_review_queue.csv"
    empty = pd.DataFrame(columns=OUTPUT_COLUMNS)
    empty_exclusions = pd.DataFrame(
        columns=["date", "market", "reason", "evidence", "review_status", "source_file", "source_url", "title"]
    )
    if not exact_path.exists():
        return empty, empty, empty_exclusions

    exact_source = pd.read_csv(exact_path)
    exact_source = exact_source[
        exact_source["date"].astype(str).str[:4].isin(["2022", "2023", "2024"])
    ].copy()
    if valid_trading_dates is not None:
        exact_source = exact_source[
            exact_source["date"].astype(str).isin(valid_trading_dates)
        ].copy()
    confidence = _number(exact_source["confidence"]).fillna(0.985)
    exact = pd.DataFrame(
        {
            "date": exact_source["date"],
            "star": _number(exact_source["star"]),
            "star_low": _number(exact_source["star"]),
            "star_high": _number(exact_source["star"]),
            "target_mid": _number(exact_source["star"]),
            "status": "exact",
            "training_weight": confidence,
            "evidence_confidence": confidence,
            "market": exact_source.get("market", "A股"),
            "realtime_or_backfilled": exact_source.get("realtime_or_backfilled", "realtime"),
            "source": "derived/star_target_historical_direct.csv",
            "source_priority": "historical_direct_article_evidence",
            "evidence_method": exact_source["evidence_method"],
            "evidence": exact_source["evidence"],
            "review_status": exact_source["review_status"],
            "source_url": _text_column(exact_source, "source_url"),
            "source_file": _text_column(exact_source, "relative_path"),
            "notes": "",
        }
    )
    exact = _finalize(exact)

    if not review_path.exists():
        return exact, empty, empty_exclusions

    review_source = pd.read_csv(review_path)
    review_source = review_source[
        review_source["date"].astype(str).str[:4].isin(["2022", "2023", "2024"])
    ].copy()
    if valid_trading_dates is not None:
        review_source = review_source[
            review_source["date"].astype(str).isin(valid_trading_dates)
        ].copy()
    closed = review_source[review_source["reason"] == "market_closed_no_new_target"].copy()
    usable = review_source[
        review_source["reason"].isin(["approximate_range", "near_threshold_only"])
    ].copy()
    status = usable["reason"].map({"approximate_range": "range", "near_threshold_only": "threshold"})
    confidence = status.map({"range": 0.75, "threshold": 0.50})
    review = pd.DataFrame(
        {
            "date": usable["date"],
            "star": pd.NA,
            "star_low": _number(usable["range_low"]),
            "star_high": _number(usable["range_high"]),
            "target_mid": pd.NA,
            "status": status,
            "training_weight": status.map(STATUS_BASE_WEIGHT) * confidence,
            "evidence_confidence": confidence,
            "market": usable.get("market", "A股"),
            "realtime_or_backfilled": "realtime",
            "source": "derived/star_target_historical_review_queue.csv",
            "source_priority": "historical_direct_article_interval_or_threshold",
            "evidence_method": usable["reason"],
            "evidence": usable["evidence"],
            "review_status": usable["review_status"],
            "source_url": _text_column(usable, "source_url"),
            "source_file": _text_column(usable, "relative_path"),
            "notes": usable["reason"].map(
                {
                    "approximate_range": "exact decimal intentionally not inferred from direct article interval",
                    "near_threshold_only": "only proximity to the reference star is known",
                }
            ),
        }
    )
    review = _finalize(review)
    exclusions = pd.DataFrame(
        {
            "date": closed["date"],
            "market": closed.get("market", "A股"),
            "reason": closed["reason"],
            "evidence": closed["evidence"],
            "review_status": closed["review_status"],
            "source_file": _text_column(closed, "relative_path"),
            "source_url": _text_column(closed, "source_url"),
            "title": closed["title"],
        }
    )
    return exact, review, exclusions


def apply_historical_article_priority(
    annual: pd.DataFrame,
    direct: pd.DataFrame,
    review: pd.DataFrame,
    exclusions: pd.DataFrame,
) -> pd.DataFrame:
    covered = set(direct["date"]) | set(review["date"]) | set(exclusions["date"])
    fallback = annual[~annual["date"].isin(covered)].copy()
    return _finalize(pd.concat([fallback, direct, review], ignore_index=True))


def load_direct_targets() -> pd.DataFrame:
    source = pd.read_csv(DERIVED / "star_target_2025_2026.csv")
    confidence = _number(source["confidence"]).fillna(0.95)
    result = pd.DataFrame(
        {
            "date": source["date"],
            "star": _number(source["star"]),
            "star_low": _number(source["star"]),
            "star_high": _number(source["star"]),
            "target_mid": _number(source["star"]),
            "status": "exact",
            "training_weight": confidence,
            "evidence_confidence": confidence,
            "market": source["market"],
            "realtime_or_backfilled": source["realtime_or_backfilled"],
            "source": "derived/star_target_2025_2026.csv",
            "source_priority": "direct_article_evidence",
            "evidence_method": source["evidence_method"],
            "evidence": source["evidence"],
            "review_status": source["review_status"],
            "source_url": source["drive_url"],
            "source_file": source["drive_file_id"],
            "notes": _text_column(source, "notes"),
        }
    )
    if result["star"].isna().any():
        raise ValueError("direct target contains a missing exact star")
    return _finalize(result)


def load_review_targets() -> tuple[pd.DataFrame, pd.DataFrame]:
    source = pd.read_csv(DERIVED / "star_target_review_queue_2025_2026.csv")
    closed = source[source["reason"] == "market_closed_no_new_target"].copy()
    usable = source[source["reason"] != "market_closed_no_new_target"].copy()

    status = usable["reason"].map({"approximate_range": "range", "near_threshold_only": "threshold"})
    if status.isna().any():
        raise ValueError(f"unexpected review reasons: {sorted(usable.loc[status.isna(), 'reason'].unique())}")
    confidence = status.map({"range": 0.75, "threshold": 0.50})
    result = pd.DataFrame(
        {
            "date": usable["date"],
            "star": pd.NA,
            "star_low": _number(usable["range_low"]),
            "star_high": _number(usable["range_high"]),
            "target_mid": pd.NA,
            "status": status,
            "training_weight": status.map(STATUS_BASE_WEIGHT) * confidence,
            "evidence_confidence": confidence,
            "market": usable["market"],
            "realtime_or_backfilled": "realtime",
            "source": "derived/star_target_review_queue_2025_2026.csv",
            "source_priority": "direct_article_interval_or_threshold",
            "evidence_method": usable["reason"],
            "evidence": usable["evidence"],
            "review_status": usable["review_status"],
            "source_url": usable["drive_url"],
            "source_file": usable["drive_file_id"],
            "notes": usable.apply(
                lambda row: (
                    f"reference_star={row['reference_star']}; only proximity is known"
                    if row["reason"] == "near_threshold_only"
                    else "exact decimal intentionally not inferred from interval"
                ),
                axis=1,
            ),
        }
    )
    exclusions = closed[
        ["date", "market", "reason", "evidence", "review_status", "drive_file_id", "drive_url", "title"]
    ].copy()
    return _finalize(result), exclusions


def exclude_known_closed_direct(
    direct: pd.DataFrame, exclusions: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    closed = direct[direct["date"].isin(KNOWN_CLOSED_DIRECT_DATES)].copy()
    if len(closed) != len(KNOWN_CLOSED_DIRECT_DATES):
        missing = sorted(set(KNOWN_CLOSED_DIRECT_DATES) - set(closed["date"]))
        raise ValueError(f"known closed direct dates are missing from source: {missing}")
    extra = pd.DataFrame(
        {
            "date": closed["date"],
            "market": closed["market"],
            "reason": "market_closed_no_new_target",
            "evidence": closed["evidence"],
            "review_status": "excluded_by_market_calendar_audit",
            "drive_file_id": closed["source_file"],
            "drive_url": closed["source_url"],
            "title": closed["date"].map(KNOWN_CLOSED_DIRECT_DATES),
        }
    )
    kept = direct[~direct["date"].isin(KNOWN_CLOSED_DIRECT_DATES)].copy()
    return kept, pd.concat([exclusions, extra], ignore_index=True).sort_values("date")


def normalize_annual_2025() -> pd.DataFrame:
    source = pd.read_csv(VERIFIED / "daily_star_2025.csv")
    result = source.copy()
    result["star"] = _number(result["star"])
    result["star_low"] = _number(result["star_low"]).fillna(result["star"])
    result["star_high"] = _number(result["star_high"]).fillna(result["star"])
    return result


def conflict_audit(annual: pd.DataFrame, direct: pd.DataFrame, review: pd.DataFrame) -> pd.DataFrame:
    selected = pd.concat(
        [
            direct[["date", "star", "star_low", "star_high", "status", "source_priority"]],
            review[["date", "star", "star_low", "star_high", "status", "source_priority"]],
        ],
        ignore_index=True,
    )
    merged = annual.merge(selected, on="date", how="inner", suffixes=("_annual", "_selected"))
    selected_point = _number(merged["star_selected"])
    conflict = selected_point.notna() & (
        (selected_point < _number(merged["star_low_annual"]))
        | (selected_point > _number(merged["star_high_annual"]))
    )
    interval_changed = selected_point.isna() & (
        (_number(merged["star_low_annual"]) != _number(merged["star_low_selected"]))
        | (_number(merged["star_high_annual"]) != _number(merged["star_high_selected"]))
        | (merged["status_annual"] != merged["status_selected"])
    )
    return merged[conflict | interval_changed].sort_values("date").reset_index(drop=True)


def legacy_only_2025(annual: pd.DataFrame, direct: pd.DataFrame, review: pd.DataFrame, exclusions: pd.DataFrame) -> pd.DataFrame:
    covered = set(direct["date"]) | set(review["date"]) | set(exclusions["date"])
    legacy = annual[~annual["date"].isin(covered)].copy()
    if (legacy["status"] != "exact").any():
        raise ValueError(f"legacy-only non-exact rows require review: {legacy.to_dict('records')}")
    confidence = 0.70
    result = pd.DataFrame(
        {
            "date": legacy["date"],
            "star": legacy["star"],
            "star_low": legacy["star_low"],
            "star_high": legacy["star_high"],
            "target_mid": legacy["star"],
            "status": "exact",
            "training_weight": confidence,
            "evidence_confidence": confidence,
            "market": "A股",
            "realtime_or_backfilled": "realtime",
            "source": "verified/daily_star_2025.csv",
            "source_priority": "legacy_only_gap_fill",
            "evidence_method": "legacy_annual_exact_without_embedded_evidence",
            "evidence": "",
            "review_status": "needs_direct_evidence_audit",
            "source_url": "",
            "source_file": "daily_star_2025.csv",
            "notes": "Kept only because no direct-pipeline or review-queue row exists for this trading date.",
        }
    )
    return _finalize(result)


def records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return json.loads(df.where(pd.notna(df), None).to_json(orient="records", force_ascii=False))


def main() -> None:
    historic_annual = pd.concat([load_historic_year(year) for year in (2022, 2023, 2024)], ignore_index=True)
    valid_historic_trading_dates = set(historic_annual["date"].astype(str))
    historic_direct, historic_review, historic_exclusions = load_historical_article_targets(
        valid_historic_trading_dates
    )
    historic = apply_historical_article_priority(
        historic_annual,
        historic_direct,
        historic_review,
        historic_exclusions,
    )
    direct = load_direct_targets()
    review, exclusions = load_review_targets()
    exclusions = pd.concat([historic_exclusions, exclusions], ignore_index=True, sort=False)
    direct, exclusions = exclude_known_closed_direct(direct, exclusions)
    annual_2025 = normalize_annual_2025()
    legacy = legacy_only_2025(annual_2025, direct, review, exclusions)
    conflicts = conflict_audit(annual_2025, direct, review)

    unified = _finalize(pd.concat([historic, direct, review, legacy], ignore_index=True))
    DERIVED.mkdir(parents=True, exist_ok=True)
    unified.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    conflicts.to_csv(CONFLICT_OUTPUT, index=False, encoding="utf-8-sig")
    exclusions.to_csv(EXCLUSION_OUTPUT, index=False, encoding="utf-8-sig")

    by_year_status = (
        unified.assign(year=unified["date"].str[:4])
        .groupby(["year", "status"])
        .size()
        .unstack(fill_value=0)
        .astype(int)
        .to_dict(orient="index")
    )
    audit = {
        "output": str(OUTPUT.relative_to(REPO)),
        "rowCount": int(len(unified)),
        "firstDate": unified["date"].min(),
        "lastDate": unified["date"].max(),
        "duplicateDates": int(unified["date"].duplicated().sum()),
        "byYearStatus": by_year_status,
        "bySourcePriority": unified["source_priority"].value_counts().astype(int).to_dict(),
        "trainableRows": int((unified["training_weight"] > 0).sum()),
        "thresholdOnlyRows": int((unified["status"] == "threshold").sum()),
        "marketClosedExclusions": int(len(exclusions)),
        "historicalDirectExactRows": int(len(historic_direct)),
        "historicalDirectReviewRows": int(len(historic_review)),
        "historicalCalendarPolicy": "2022-2024 direct article evidence is admitted only on verified A-share trading dates",
        "historicalAnnualFallbackRows": int((historic["source_priority"] == "historic_verified_annual").sum()),
        "legacyOnlyGapFills": records(legacy[["date", "star", "evidence_confidence", "review_status"]]),
        "2025SourceConflictCount": int(len(conflicts)),
        "sourcePolicy": [
            "2022-2024: direct article evidence overrides verified annual files when the historical pipeline is present; annual files remain fallback",
            "2025-2026: direct article evidence overrides the legacy annual file",
            "review intervals remain intervals; threshold-only evidence is not trainable",
            "market-closed articles are excluded",
            "legacy annual data fills only dates absent from both direct evidence and review queue",
        ],
    }
    AUDIT_OUTPUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
