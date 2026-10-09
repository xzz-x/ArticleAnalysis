from __future__ import annotations

from datetime import date

import pandas as pd

from article_analysis.lixinger_incremental import (
    coalesce_latest,
    is_request_size_or_field_limit_error,
    missing_windows,
)


def test_missing_windows_requests_only_dates_after_local_tail(tmp_path):
    path = tmp_path / "cached.parquet"
    pd.DataFrame(
        {
            "date": ["2026-09-20", "2026-09-21", "2026-09-22"],
            "stockCode": ["1000002"] * 3,
        }
    ).to_parquet(path, index=False)

    assert missing_windows(
        path,
        first_date=date(1994, 1, 1),
        end_date=date(2026, 10, 10),
    ) == [("2026-09-23", "2026-10-10")]


def test_missing_windows_skips_api_when_already_current(tmp_path):
    path = tmp_path / "cached.parquet"
    pd.DataFrame({"date": ["2026-10-10"]}).to_parquet(path, index=False)

    assert missing_windows(
        path,
        first_date=date(1994, 1, 1),
        end_date=date(2026, 10, 10),
    ) == []


def test_coalesce_latest_keeps_fields_from_split_bundles():
    core = pd.DataFrame(
        {
            "date": ["2026-10-10"],
            "stockCode": ["1000002"],
            "pe_ttm.mcw": [12.0],
            "pb.y20.mcw.cvpos": [pd.NA],
        }
    )
    checks = pd.DataFrame(
        {
            "date": ["2026-10-10"],
            "stockCode": ["1000002"],
            "pe_ttm.mcw": [pd.NA],
            "pb.y20.mcw.cvpos": [0.23],
        }
    )

    merged = coalesce_latest([core, checks], ["date", "stockCode"])

    assert len(merged) == 1
    assert merged.loc[0, "pe_ttm.mcw"] == 12.0
    assert merged.loc[0, "pb.y20.mcw.cvpos"] == 0.23


def test_bundle_fallback_classifier_does_not_treat_quota_as_size_error():
    assert not is_request_size_or_field_limit_error(
        RuntimeError("LiXinger API error: quota exceeded for this account")
    )
    assert is_request_size_or_field_limit_error(
        RuntimeError("metricsList exceeds maximum field limit")
    )
