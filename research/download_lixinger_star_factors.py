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
RAW_ROOT = REPO / "data" / "raw" / "lixinger"
DERIVED_ROOT = REPO / "data" / "derived" / "lixinger"
BASE_URL = "https://open.lixinger.com/api"


class LixingerApiError(RuntimeError):
    pass


def windows(start_year: int, end: date) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    year = start_year
    while year <= end.year:
        end_year = min(year + 9, end.year)
        finish = end if end_year == end.year else date(end_year, 12, 31)
        result.append((date(year, 1, 1).isoformat(), finish.isoformat()))
        year = end_year + 1
    return result


def fingerprint(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def atomic_json(path: Path, content: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def post(endpoint: str, payload_without_token: dict[str, Any], token: str) -> dict[str, Any]:
    body = json.dumps({**payload_without_token, "token": token}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{endpoint}",
        data=body,
        headers={
            "Accept-Encoding": "gzip",
            "Content-Type": "application/json",
            "User-Agent": "ArticleAnalysis/0.1",
        },
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                result = json.loads(raw.decode("utf-8"))
            if result.get("code") != 1:
                raise LixingerApiError(f"{endpoint}: {result.get('code')} {result.get('message')}")
            return result
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            if exc.headers.get("Content-Encoding", "").lower() == "gzip":
                raw = gzip.decompress(raw)
            text = raw.decode("utf-8", errors="replace")
            if 400 <= exc.code < 500:
                raise LixingerApiError(f"{endpoint}: HTTP {exc.code}: {text}") from exc
            if attempt == 2:
                raise RuntimeError(f"{endpoint}: HTTP {exc.code}: {text}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if attempt == 2:
                raise RuntimeError(f"{endpoint}: transport failure: {exc}") from exc
        time.sleep(2**attempt)
    raise AssertionError("unreachable")


def fetch_cached(
    *, dataset: str, endpoint: str, payload: dict[str, Any], token: str, force: bool
) -> Path:
    digest = fingerprint({"endpoint": endpoint, **payload})
    stem = f"{payload['startDate']}_{payload.get('endDate', 'current')}_{digest[:12]}"
    raw_path = RAW_ROOT / dataset / f"{stem}.json"
    manifest_path = RAW_ROOT / dataset / f"{stem}.manifest.json"
    if raw_path.exists() and manifest_path.exists() and not force:
        print(f"cache hit: {dataset}/{raw_path.name}")
        return raw_path

    result = post(endpoint, payload, token)
    atomic_json(raw_path, result)
    atomic_json(
        manifest_path,
        {
            "endpoint": f"{BASE_URL}{endpoint}",
            "request": payload,
            "requestFingerprint": digest,
            "rowCount": len(result.get("data") or []),
            "downloadedAtUtc": pd.Timestamp.utcnow().isoformat(),
        },
    )
    print(f"downloaded {dataset}: {len(result.get('data') or []):5d} rows")
    return raw_path


def consolidate(dataset: str, raw_paths: list[Path], key_columns: list[str]) -> Path:
    output_dir = DERIVED_ROOT / dataset
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{dataset}.parquet"

    frames: list[pd.DataFrame] = []
    if output.exists():
        frames.append(pd.read_parquet(output))
    for path in raw_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("data"):
            frames.append(pd.json_normalize(payload["data"]))
    if not frames:
        raise RuntimeError(f"{dataset}: no local or downloaded rows")

    normalized: list[pd.DataFrame] = []
    for frame in frames:
        current = frame.copy()
        if "date" not in current:
            raise RuntimeError(f"{dataset}: API response does not contain date")
        current["date"] = pd.to_datetime(current["date"], utc=True).dt.tz_convert("Asia/Shanghai").dt.date
        if "stockCode" in current:
            current["stockCode"] = current["stockCode"].astype(str).str.zfill(6)
        normalized.append(current)
    keys = [column for column in key_columns if column in normalized[-1]]
    df = coalesce_latest(normalized, keys)
    temp = output.with_suffix(".parquet.tmp")
    df.to_parquet(temp, index=False)
    os.replace(temp, output)
    print(f"consolidated {dataset}: {len(df):5d} rows, {len(df.columns):3d} columns, {df.date.min()}..{df.date.max()}")
    return output


NATIONAL_DEBT_METRICS = [
    "tcm_m3", "tcm_m6", "tcm_y1", "tcm_y2", "tcm_y3",
    "tcm_y5", "tcm_y7", "tcm_y10", "tcm_y20", "tcm_y30",
]
INVESTOR_METRICS = [
    "ni", "nia", "nib", "non_ni", "non_nia", "non_nib",
    "nni_m", "n_non_ni_m", "nni_w", "n_non_ni_w",
]
GDP_LEVELS = ["gdp", "gdp_cp", "per_gdp", "pi_gdp", "si_gdp", "ti_gdp", "gni"]
GDP_METRICS = [
    *[f"y.{level}.{expr}" for level in GDP_LEVELS for expr in ("t", "t_y2y")],
    *[
        f"q.{level}.{expr}"
        for level in GDP_LEVELS
        for expr in ("t", "t_y2y", "c", "c_y2y", "c_c2c", "c_2y", "ttm", "ttm_y2y", "ttm_c2c")
    ],
    *[
        f"{grain}.{level}.{expr}"
        for level in ("pi_gdp_c_r", "si_gdp_c_r", "ti_gdp_c_r")
        for grain, exprs in (("y", ("t", "t_y2y")), ("q", ("t", "t_y2y", "t_c2c")))
        for expr in exprs
    ],
]

# All fields are selected because they directly support the documented first
# model (earnings growth and ROE) or plausible quality/funding controls.
FINANCIAL_METRICS = [
    "q.ps.oi.ttm", "q.ps.oi.ttm_y2y", "q.ps.oi.c", "q.ps.oi.c_y2y",
    "q.ps.op.ttm", "q.ps.op.ttm_y2y",
    "q.ps.np.ttm", "q.ps.np.ttm_y2y", "q.ps.np.c", "q.ps.np.c_y2y",
    "q.ps.npatoshopc.ttm", "q.ps.npatoshopc.ttm_y2y",
    "q.ps.npadnrpatoshaopc.ttm", "q.ps.npadnrpatoshaopc.ttm_y2y",
    "q.ps.da_om.ttm", "q.ps.fa_om.ttm",
    "q.cfs.ncffoa.ttm", "q.cfs.ncffoa.ttm_y2y",
    "q.cfs.ncffia.ttm", "q.cfs.ncffia.ttm_y2y",
    "q.cfs.ncfffa.ttm", "q.cfs.ncfffa.ttm_y2y",
    "q.m.roe.ttm", "q.m.roe.ttm_y2y",
    "q.m.roe_atoshaopc.ttm", "q.m.roe_atoshaopc.ttm_y2y",
    "q.m.roa.ttm", "q.m.roa.ttm_y2y",
    "q.m.fcf.ttm", "q.m.fcf.ttm_y2y",
    "q.m.l.t", "q.m.tl_ta_r.t", "q.m.np_s_r.ttm",
]


@dataclass(frozen=True)
class FinancialIndex:
    stock_code: str
    start_year: int


FINANCIAL_INDICES = (FinancialIndex("1000002", 1994), FinancialIndex("000985", 2011))


def download_macro(dataset: str, endpoint: str, metrics: list[str], token: str, end: date, force: bool) -> None:
    output = DERIVED_ROOT / dataset / f"{dataset}.parquet"
    request_windows = missing_windows(
        output,
        first_date=date(1994, 1, 1),
        end_date=end,
        force=force,
    )
    if not request_windows:
        print(f"up to date: {dataset} through {end}")
        return

    raw_paths = [
        fetch_cached(
            dataset=dataset,
            endpoint=endpoint,
            payload={"areaCode": "cn", "startDate": start, "endDate": finish, "metricsList": metrics},
            token=token,
            force=force,
        )
        for start, finish in request_windows
    ]
    consolidate(dataset, raw_paths, ["date", "areaCode"])


def download_financials(token: str, end: date, force: bool) -> None:
    raw_paths: list[Path] = []
    endpoint = "/cn/index/fs/hybrid"
    output = DERIVED_ROOT / "index_financials" / "index_financials.parquet"
    for index in FINANCIAL_INDICES:
        request_windows = missing_windows(
            output,
            first_date=date(index.start_year, 1, 1),
            end_date=end,
            force=force,
            key="stockCode",
            value=index.stock_code,
        )
        for start, finish in request_windows:
            raw_paths.append(
                fetch_cached(
                    dataset="index_financials",
                    endpoint=endpoint,
                    payload={
                        "stockCodes": [index.stock_code],
                        "startDate": start,
                        "endDate": finish,
                        "metricsList": FINANCIAL_METRICS,
                    },
                    token=token,
                    force=force,
                )
            )
    if not raw_paths:
        print(f"up to date: index_financials through {end}")
        return
    consolidate("index_financials", raw_paths, ["date", "stockCode"])


def download_margin(token: str, end: date, force: bool) -> None:
    endpoint = "/cn/company/market-data/margin-trading-and-securities-lending"
    output = DERIVED_ROOT / "margin" / "margin.parquet"
    request_windows = missing_windows(
        output,
        first_date=date(1994, 1, 1),
        end_date=end,
        force=force,
    )
    if not request_windows:
        print(f"up to date: margin through {end}")
        return

    raw_paths = [
        fetch_cached(
            dataset="margin",
            endpoint=endpoint,
            payload={"startDate": start_date, "endDate": end_date},
            token=token,
            force=force,
        )
        for start_date, end_date in request_windows
    ]
    consolidate("margin", raw_paths, ["date"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Download remaining LiXinger star-replica factor data")
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    token = os.getenv("LIXINGER_TOKEN", "").strip()
    if not token:
        raise RuntimeError("LIXINGER_TOKEN is not configured")

    print(f"national_debt metrics={len(NATIONAL_DEBT_METRICS)}")
    print(f"gdp metrics={len(GDP_METRICS)}")
    print(f"investor metrics={len(INVESTOR_METRICS)}")
    print(f"index_financial metrics={len(FINANCIAL_METRICS)}")
    download_macro("national_debt", "/macro/national-debt", NATIONAL_DEBT_METRICS, token, args.end_date, args.force)
    download_macro("gdp", "/macro/gdp", GDP_METRICS, token, args.end_date, args.force)
    download_macro("investor", "/macro/investor", INVESTOR_METRICS, token, args.end_date, args.force)
    download_margin(token, args.end_date, args.force)
    download_financials(token, args.end_date, args.force)


if __name__ == "__main__":
    main()
