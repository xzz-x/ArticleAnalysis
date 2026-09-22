from __future__ import annotations

import runpy
from datetime import date
from pathlib import Path


MODULE = runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "research" / "download_lixinger_index_fundamental.py")
)


def test_core_and_check_metric_bundles_are_unique() -> None:
    core = MODULE["CORE_FIELDS"]
    checks = MODULE["CHECK_FIELDS"]
    all_fields = MODULE["ALL_FIELDS"]

    assert len(core) == 45
    assert len(checks) == 20
    assert len(all_fields) == 65
    assert len(set(all_fields)) == len(all_fields)


def test_ten_year_windows_are_contiguous() -> None:
    windows = MODULE["ten_year_windows"](1994, date(2026, 9, 22))

    assert windows == [
        ("1994-01-01", "2003-12-31"),
        ("2004-01-01", "2013-12-31"),
        ("2014-01-01", "2023-12-31"),
        ("2024-01-01", "2026-09-22"),
    ]


def test_request_fingerprint_is_order_independent() -> None:
    fingerprint = MODULE["request_fingerprint"]

    assert fingerprint({"a": 1, "b": 2}) == fingerprint({"b": 2, "a": 1})


def test_remaining_factor_download_bundles_are_sized_and_unique() -> None:
    module = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "research" / "download_lixinger_star_factors.py")
    )

    assert len(module["NATIONAL_DEBT_METRICS"]) == 10
    assert len(module["GDP_METRICS"]) == 92
    assert len(module["INVESTOR_METRICS"]) == 10
    assert len(module["FINANCIAL_METRICS"]) == 33
    assert len(set(module["GDP_METRICS"])) == len(module["GDP_METRICS"])
    assert len(set(module["FINANCIAL_METRICS"])) == len(module["FINANCIAL_METRICS"])
