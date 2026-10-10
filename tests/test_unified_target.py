from __future__ import annotations

from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[1]
TARGET = REPO / "data" / "derived" / "star_target_2022_2026_unified.csv"


def load_target() -> pd.DataFrame:
    return pd.read_csv(TARGET)


def test_unified_target_has_one_row_per_date() -> None:
    target = load_target()

    assert len(target) == 1129
    assert target["date"].is_unique
    assert target["date"].min() == "2022-01-04"
    assert target["date"].max() == "2026-08-31"
    assert int((target["training_weight"] > 0).sum()) == 1126


def test_direct_article_evidence_overrides_conflicting_legacy_2025_value() -> None:
    row = load_target().set_index("date").loc["2025-01-24"]

    assert row["star"] == 5.1
    assert row["source_priority"] == "direct_article_evidence"


def test_review_intervals_are_not_collapsed_to_legacy_points() -> None:
    row = load_target().set_index("date").loc["2025-06-20"]

    assert row["status"] == "range"
    assert pd.isna(row["star"])
    assert row["star_low"] == 5.0
    assert row["star_high"] == 5.1
    assert row["target_mid"] == 5.05


def test_threshold_only_and_market_closed_rows_are_not_trainable_targets() -> None:
    target = load_target().set_index("date")
    threshold = target.loc["2025-06-12"]

    assert threshold["status"] == "threshold"
    assert threshold["training_weight"] == 0
    assert pd.isna(threshold["target_mid"])
    for date in (
        "2025-02-04",
        "2025-05-05",
        "2025-06-02",
        "2025-10-08",
        "2026-02-23",
        "2026-05-05",
    ):
        assert date not in target.index


def test_2025_08_26_intraday_threshold_is_not_promoted_to_closing_exact() -> None:
    row = load_target().set_index("date").loc["2025-08-26"]

    assert row["status"] == "threshold"
    assert pd.isna(row["star"])
    assert pd.isna(row["target_mid"])
    assert row["source_priority"] == "direct_article_interval_or_threshold"
    assert row["training_weight"] == 0
    assert row["review_status"] == "next_day_backlink_intraday_threshold"
