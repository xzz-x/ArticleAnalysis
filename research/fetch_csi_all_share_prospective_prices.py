from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

from dynamic_price_residual_analysis import REPO

DEFAULT_OUTPUT = REPO / "data" / "derived" / "csi_all_share_prospective_prices.csv"


def fetch_eastmoney(start: str, end: str) -> pd.DataFrame:
    params = {
        "secid": "1.000985",
        "klt": "101",
        "fqt": "0",
        "beg": start.replace("-", ""),
        "end": end.replace("-", ""),
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    }
    url = "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/zs000985.html",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    data = payload.get("data") or {}
    klines = data.get("klines") or []
    rows = []
    for raw in klines:
        parts = raw.split(",")
        if len(parts) < 3:
            continue
        rows.append(
            {
                "date": parts[0],
                "open": float(parts[1]),
                "cp": float(parts[2]),
                "high": float(parts[3]),
                "low": float(parts[4]),
                "volume": float(parts[5]),
                "amount": float(parts[6]),
                "pct_change": float(parts[8]),
                "source": "eastmoney_public_kline",
                "source_code": "000985.SH",
            }
        )
    if not rows:
        raise RuntimeError(f"Eastmoney returned no 000985 daily rows: {payload}")
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch prospective CSI All Share (000985.SH) closes")
    parser.add_argument("--start", default="2026-08-31")
    parser.add_argument("--end", default="2026-10-09")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--anchor-date", default="2026-08-31")
    parser.add_argument("--anchor-close", type=float, default=5969.33)
    parser.add_argument("--anchor-tolerance", type=float, default=0.05)
    parser.add_argument("--skip-anchor-check", action="store_true")
    args = parser.parse_args()

    frame = fetch_eastmoney(args.start, args.end)
    observed = None
    if not args.skip_anchor_check:
        anchor = frame[frame["date"] == args.anchor_date]
        if anchor.empty:
            raise RuntimeError(f"anchor date {args.anchor_date} missing from public 000985 series")
        observed = float(anchor.iloc[0]["cp"])
        if abs(observed - args.anchor_close) > args.anchor_tolerance:
            raise RuntimeError(
                f"000985 proxy mismatch on {args.anchor_date}: public={observed}, "
                f"frozen-series={args.anchor_close}, tolerance={args.anchor_tolerance}"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(
        json.dumps(
            {
                "source": "Eastmoney public kline",
                "code": "000985.SH",
                "rows": int(len(frame)),
                "minDate": str(frame["date"].min()),
                "maxDate": str(frame["date"].max()),
                "anchorDate": None if args.skip_anchor_check else args.anchor_date,
                "anchorClose": observed,
                "anchorMatched": None if args.skip_anchor_check else True,
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
