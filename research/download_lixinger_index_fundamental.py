from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from article_analysis.lixinger_incremental import (
    coalesce_latest,
    is_request_size_or_field_limit_error,
    missing_windows,
)


REPO = Path(__file__).resolve().parents[1]
RAW_ROOT = REPO / "data" / "raw" / "lixinger" / "index_fundamental"
DERIVED_ROOT = REPO / "data" / "derived" / "lixinger" / "index_fundamental"
ENDPOINT = "https://open.lixinger.com/api/cn/index/fundamental"

VALUATIONS = ("pe_ttm", "pb", "ps_ttm", "dyr")
WEIGHTINGS = ("mcw", "ew", "ewpvo", "avg", "median")
RAW_MARKET_FIELDS = (
    "tv",
    "ta",
    "to_r",
    "cp",
    "cpc",
    "cpa",
    "r_cp",
    "r_cpc",
    "mc",
    "mc_om",
    "cmc",
    "ecmc",
    "fpa",
    "fra",
    "fnpa",
    "fb",
    "ssa",
    "sra",
    "snsa",
    "sb",
    "ha_shm",
    "mm_nba",
    "fet_as_ma",
    "fet_snif_ma",
    "launchDate",
)


def current_valuation_fields() -> list[str]:
    return [f"{metric}.{weighting}" for metric in VALUATIONS for weighting in WEIGHTINGS]


def long_percentile_checks() -> list[str]:
    return [
        f"{metric}.{window}.{weighting}.cvpos"
        for metric in ("pe_ttm", "pb")
        for window in ("y20", "fs")
        for weighting in WEIGHTINGS
    ]


CORE_FIELDS = current_valuation_fields() + list(RAW_MARKET_FIELDS)
CHECK_FIELDS = long_percentile_checks()
ALL_FIELDS = CORE_FIELDS + CHECK_FIELDS


@dataclass(frozen=True)
class IndexDownload:
    stock_code: str
    name: str
    start_year: int


INDEX_DOWNLOADS = (
    IndexDownload("1000002", "a_share_all", 1994),
    # The published index starts in 2011, but LiXinger may expose backfilled
    # history. Starting in 2005 gives enough warm-up for later 20-year factors.
    IndexDownload("000985", "csi_all_share", 2005),
)


class LixingerApiError(RuntimeError):
    """A non-retryable API/HTTP response from LiXinger."""


class LixingerTransportError(RuntimeError):
    """A retryable network or server failure."""


def ten_year_windows(start_year: int, end_date: date) -> list[tuple[str, str]]:
    windows: list[tuple[str, str]] = []
    year = start_year
    while year <= end_date.year:
        window_end_year = min(year + 9, end_date.year)
        end = end_date if window_end_year == end_date.year else date(window_end_year, 12, 31)
        windows.append((date(year, 1, 1).isoformat(), end.isoformat()))
        year = window_end_year + 1
    return windows


def request_fingerprint(payload_without_token: dict[str, Any]) -> str:
    encoded = json.dumps(payload_without_token, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def atomic_json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def fetch(payload_without_token: dict[str, Any], token: str, retries: int = 3) -> dict[str, Any]:
    payload = {**payload_without_token, "token": token}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        ENDPOINT,
        data=body,
        headers={
            "Accept-Encoding": "gzip",
            "Content-Type": "application/json",
            "User-Agent": "ArticleAnalysis/0.1",
        },
        method="POST",
    )

    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                result = json.loads(raw.decode("utf-8"))
            if result.get("code") != 1:
                # Parameter and quota errors must not be retried blindly.
                raise LixingerApiError(f"LiXinger API error: {result.get('code')} {result.get('message')}")
            return result
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            if exc.headers.get("Content-Encoding", "").lower() == "gzip":
                raw = gzip.decompress(raw)
            response_text = raw.decode("utf-8", errors="replace")
            if 400 <= exc.code < 500:
                raise LixingerApiError(f"LiXinger HTTP {exc.code}: {response_text}") from exc
            if attempt + 1 >= retries:
                raise LixingerTransportError(
                    f"LiXinger HTTP {exc.code} after {retries} attempts: {response_text}"
                ) from exc
            time.sleep(2**attempt)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt + 1 >= retries:
                raise LixingerTransportError(
                    f"LiXinger transport failure after {retries} attempts: {exc}"
                ) from exc
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def download_request(
    *,
    stock_code: str,
    start_date: str,
    end_date: str,
    metrics: list[str],
    bundle_name: str,
    token: str,
    force: bool,
) -> Path:
    payload = {
        "stockCodes": [stock_code],
        "startDate": start_date,
        "endDate": end_date,
        "metricsList": metrics,
    }
    fingerprint = request_fingerprint(payload)
    stem = f"{stock_code}_{start_date}_{end_date}_{bundle_name}_{fingerprint[:12]}"
    raw_path = RAW_ROOT / stock_code / f"{stem}.json"
    manifest_path = RAW_ROOT / stock_code / f"{stem}.manifest.json"

    if raw_path.exists() and manifest_path.exists() and not force:
        print(f"cache hit: {raw_path.relative_to(REPO)}")
        return raw_path

    result = fetch(payload, token)
    atomic_json_write(raw_path, result)
    atomic_json_write(
        manifest_path,
        {
            "endpoint": ENDPOINT,
            "request": payload,
            "requestFingerprint": fingerprint,
            "bundle": bundle_name,
            "rowCount": len(result.get("data") or []),
            "downloadedAtUtc": pd.Timestamp.utcnow().isoformat(),
        },
    )
    print(f"downloaded {len(result.get('data') or []):5d} rows: {raw_path.relative_to(REPO)}")
    return raw_path


def download_window(
    *, stock_code: str, start_date: str, end_date: str, token: str, force: bool
) -> list[Path]:
    try:
        return [
            download_request(
                stock_code=stock_code,
                start_date=start_date,
                end_date=end_date,
                metrics=ALL_FIELDS,
                bundle_name="core65",
                token=token,
                force=force,
            )
        ]
    except LixingerApiError as exc:
        # Do not burn two more API calls for quota/auth/parameter failures.
        # Split only when the error actually indicates a field/response limit.
        if not is_request_size_or_field_limit_error(exc):
            raise
        print(f"core65 hit a field/response limit; retrying as core45 + checks20: {exc}")
        return [
            download_request(
                stock_code=stock_code,
                start_date=start_date,
                end_date=end_date,
                metrics=CORE_FIELDS,
                bundle_name="core45",
                token=token,
                force=force,
            ),
            download_request(
                stock_code=stock_code,
                start_date=start_date,
                end_date=end_date,
                metrics=CHECK_FIELDS,
                bundle_name="checks20",
                token=token,
                force=force,
            ),
        ]


def consolidate(spec: IndexDownload, raw_paths: list[Path]) -> Path:
    output = DERIVED_ROOT / f"{spec.stock_code}_{spec.name}_core65.parquet"
    frames: list[pd.DataFrame] = []
    if output.exists():
        frames.append(pd.read_parquet(output))

    for path in raw_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("data") or []
        if rows:
            frames.append(pd.json_normalize(rows))

    if not frames:
        raise RuntimeError(f"No local or downloaded rows for {spec.stock_code} ({spec.name})")

    normalized: list[pd.DataFrame] = []
    for frame in frames:
        current = frame.copy()
        if "date" not in current.columns:
            raise RuntimeError(f"Downloaded data has no date column for {spec.stock_code}")
        current["date"] = pd.to_datetime(current["date"], utc=True).dt.tz_convert("Asia/Shanghai").dt.date
        current["stockCode"] = current["stockCode"].astype(str).str.zfill(6)
        normalized.append(current)

    df = coalesce_latest(normalized, ["date", "stockCode"])
    preferred = ["date", "stockCode"] + [field for field in ALL_FIELDS if field in df.columns]
    remaining = sorted(set(df.columns) - set(preferred))
    df = df[preferred + remaining]

    DERIVED_ROOT.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(".parquet.tmp")
    df.to_parquet(temp, index=False)
    os.replace(temp, output)
    print(
        f"consolidated {len(df):5d} rows, {len(df.columns):3d} columns, "
        f"{df['date'].min()}..{df['date'].max()}: {output.relative_to(REPO)}"
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Download core LiXinger index fundamental history")
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    token = os.getenv("LIXINGER_TOKEN", "").strip()
    if not token:
        raise RuntimeError("LIXINGER_TOKEN is not configured")

    print(f"metrics: core={len(CORE_FIELDS)}, checks={len(CHECK_FIELDS)}, total={len(ALL_FIELDS)}")
    for spec in INDEX_DOWNLOADS:
        output = DERIVED_ROOT / f"{spec.stock_code}_{spec.name}_core65.parquet"
        windows = missing_windows(
            output,
            first_date=date(spec.start_year, 1, 1),
            end_date=args.end_date,
            force=args.force,
        )
        if not windows:
            print(f"up to date: {output.relative_to(REPO)} through {args.end_date}")
            continue

        paths: list[Path] = []
        for start_date, end_date in windows:
            paths.extend(
                download_window(
                    stock_code=spec.stock_code,
                    start_date=start_date,
                    end_date=end_date,
                    token=token,
                    force=args.force,
                )
            )
        consolidate(spec, paths)


if __name__ == "__main__":
    main()
