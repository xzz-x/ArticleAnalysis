from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd


def date_windows(start: date, end: date, max_years: int = 10) -> list[tuple[str, str]]:
    """Split an arbitrary date range into contiguous API windows of at most max_years."""
    if start > end:
        return []
    result: list[tuple[str, str]] = []
    current = start
    while current <= end:
        try:
            candidate = current.replace(year=current.year + max_years) - timedelta(days=1)
        except ValueError:
            candidate = current.replace(month=2, day=28, year=current.year + max_years) - timedelta(days=1)
        finish = min(candidate, end)
        result.append((current.isoformat(), finish.isoformat()))
        current = finish + timedelta(days=1)
    return result


def _to_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", utc=True).dt.tz_convert("Asia/Shanghai").dt.date


def existing_last_date(path: Path, *, key: str | None = None, value: str | None = None) -> date | None:
    if not path.exists():
        return None
    columns = ["date"] + ([key] if key else [])
    frame = pd.read_parquet(path, columns=columns)
    if key is not None:
        frame = frame[frame[key].astype(str).str.zfill(6) == str(value).zfill(6)]
    if frame.empty:
        return None
    dates = _to_date(frame["date"]).dropna()
    return max(dates) if len(dates) else None


def missing_windows(
    output: Path,
    *,
    first_date: date,
    end_date: date,
    force: bool = False,
    key: str | None = None,
    value: str | None = None,
) -> list[tuple[str, str]]:
    """Return only the date range absent from the consolidated local dataset."""
    if force:
        return date_windows(first_date, end_date)
    last = existing_last_date(output, key=key, value=value)
    start = first_date if last is None else max(first_date, last + timedelta(days=1))
    return date_windows(start, end_date)


def coalesce_latest(frames: Iterable[pd.DataFrame], key_columns: list[str]) -> pd.DataFrame:
    """Merge overlapping API bundles while preferring the newest non-null value per field."""
    prepared: list[pd.DataFrame] = []
    for order, frame in enumerate(frames):
        if frame is None or frame.empty:
            continue
        current = frame.copy()
        current["_source_order"] = order
        prepared.append(current)
    if not prepared:
        return pd.DataFrame()

    merged = pd.concat(prepared, ignore_index=True, sort=False)
    merged = merged.sort_values(key_columns + ["_source_order"], ascending=[True] * len(key_columns) + [False])
    # groupby.first takes the first non-null value column-by-column, which is what
    # split 45+20-field bundles require. A simple drop_duplicates would discard
    # the fields present only in the earlier bundle.
    result = merged.groupby(key_columns, as_index=False, sort=True, dropna=False).first()
    return result.drop(columns=["_source_order"], errors="ignore")


_LIMIT_TERMS = re.compile(
    r"(?:http\s*413|too\s+many|maximum|max\b|exceed|limit|size|payload|response|"
    r"metrics?list|metrics?|fields?|指标|字段|过多|上限|限制|响应过大)",
    re.I,
)
_SUBJECT_TERMS = re.compile(r"(?:metrics?list|metrics?|fields?|指标|字段|payload|response|响应)", re.I)


def is_request_size_or_field_limit_error(exc: BaseException) -> bool:
    """Only allow bundle splitting for errors that actually look like size/field limits."""
    message = str(exc)
    if re.search(r"http\s*413", message, re.I):
        return True
    return bool(_LIMIT_TERMS.search(message) and _SUBJECT_TERMS.search(message))
