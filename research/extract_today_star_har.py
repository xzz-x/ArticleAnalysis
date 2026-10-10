#!/usr/bin/env python3
"""
Rank candidate "今天几星" Mini Program API calls from a HAR export.

This utility is intentionally conservative:
- it never prints cookies / authorization headers / obvious token-like values;
- it ranks requests that look like star/history/market-data endpoints;
- it emits only small structural samples, not full responses.

Usage:
    python research/extract_today_star_har.py capture.har
    python research/extract_today_star_har.py capture.har \
        --json-out today_star_candidates.json --top 50
"""
from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DATE_RE = re.compile(r"\b(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})\b")
SENSITIVE_RE = re.compile(
    r"(authorization|cookie|token|secret|session|openid|unionid|credential|passwd|password|code)",
    re.I,
)
URL_HINTS = {
    "history": 6,
    "histor": 5,
    "star": 6,
    "score": 5,
    "rating": 5,
    "trend": 4,
    "chart": 4,
    "date": 2,
    "market": 2,
    "valuation": 3,
    "estimate": 2,
    "index": 1,
}
TEXT_HINTS = {
    "中证全指": 8,
    "000985": 8,
    "星级": 8,
    "历史星级": 10,
    "今天几星": 6,
}
STAR_KEY_RE = re.compile(r"(star|score|rating|level|xing|星级)", re.I)


def redact_scalar(key: str, value: Any) -> Any:
    if SENSITIVE_RE.search(key):
        return "<redacted>"
    if isinstance(value, str) and len(value) > 160:
        return value[:157] + "..."
    return value


def sanitize_mapping(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: redact_scalar(k, sanitize_mapping(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_mapping(v) for v in obj[:20]]
    return obj


def sanitize_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            query.append((key, "<redacted>" if SENSITIVE_RE.search(key) else value))
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), "")
        )
    except Exception:
        return url.split("#", 1)[0]


def request_body(entry: dict[str, Any]) -> Any:
    post = entry.get("request", {}).get("postData") or {}

    if isinstance(post.get("params"), list):
        out = {}
        for item in post["params"]:
            key = str(item.get("name", ""))
            out[key] = redact_scalar(key, item.get("value"))
        return out

    text = post.get("text")
    if not isinstance(text, str) or not text:
        return None

    try:
        return sanitize_mapping(json.loads(text))
    except Exception:
        pairs = parse_qsl(text, keep_blank_values=True)
        if pairs:
            return {key: redact_scalar(key, value) for key, value in pairs}
        return "<non-JSON body omitted>"


def response_text(entry: dict[str, Any]) -> str:
    response_content = entry.get("response", {}).get("content") or {}
    text = response_content.get("text")
    if not isinstance(text, str):
        return ""

    if response_content.get("encoding") == "base64":
        try:
            return base64.b64decode(text).decode("utf-8", errors="replace")
        except Exception:
            return ""

    return text


def walk(obj: Any, path: str = "$"):
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{path}.{key}"
            yield child, key, value
            yield from walk(value, child)
    elif isinstance(obj, list):
        for index, value in enumerate(obj[:500]):
            yield from walk(value, f"{path}[{index}]")


def structural_summary(text: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "json": False,
        "top_level_keys": [],
        "date_samples": [],
        "star_field_samples": [],
    }

    dates = []
    for match in DATE_RE.finditer(text):
        value = match.group(1)
        if value not in dates:
            dates.append(value)
        if len(dates) == 6:
            break
    summary["date_samples"] = dates

    try:
        obj = json.loads(text)
    except Exception:
        return summary

    summary["json"] = True
    if isinstance(obj, dict):
        summary["top_level_keys"] = list(obj.keys())[:30]
    elif isinstance(obj, list):
        summary["top_level_keys"] = ["<array>"]

    star_samples = []
    seen = set()
    for path, key, value in walk(obj):
        if STAR_KEY_RE.search(str(key)) and isinstance(value, (int, float, str)):
            marker = (path, str(value))
            if marker in seen:
                continue
            star_samples.append({"path": path, "value": value})
            seen.add(marker)
            if len(star_samples) == 12:
                break

    summary["star_field_samples"] = star_samples
    return summary


def score_entry(
    entry: dict[str, Any],
    text: str,
    summary: dict[str, Any],
) -> tuple[int, list[str]]:
    request = entry.get("request", {})
    url = str(request.get("url", ""))
    url_lower = url.lower()

    score = 0
    reasons = []

    for token, weight in URL_HINTS.items():
        if token in url_lower:
            score += weight
            reasons.append(f"url:{token}")

    sample = text[:2_000_000]
    for token, weight in TEXT_HINTS.items():
        if token in sample:
            score += weight
            reasons.append(f"response:{token}")

    date_count = len(DATE_RE.findall(sample))
    if date_count >= 2:
        score += 3
        reasons.append("multiple_dates")
    if date_count >= 20:
        score += 5
        reasons.append("date_series")

    if summary["star_field_samples"]:
        score += 8
        reasons.append("star_like_field")

    if summary["json"]:
        score += 1
        reasons.append("json")

    if entry.get("response", {}).get("status") == 200:
        score += 1

    return score, reasons


def analyze(har: dict[str, Any]) -> list[dict[str, Any]]:
    entries = har.get("log", {}).get("entries", [])
    candidates = []

    for entry_index, entry in enumerate(entries):
        request = entry.get("request", {})
        text = response_text(entry)
        summary = structural_summary(text)
        score, reasons = score_entry(entry, text, summary)

        if score < 4:
            continue

        url = str(request.get("url", ""))
        parts = urlsplit(url)

        candidates.append(
            {
                "rank_score": score,
                "entry_index": entry_index,
                "method": request.get("method"),
                "host": parts.netloc,
                "path": parts.path,
                "url": sanitize_url(url),
                "status": entry.get("response", {}).get("status"),
                "mime_type": (
                    entry.get("response", {}).get("content") or {}
                ).get("mimeType"),
                "request_body": request_body(entry),
                "response": summary,
                "reasons": reasons,
            }
        )

    candidates.sort(key=lambda item: (-item["rank_score"], item["entry_index"]))
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("har", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--top", type=int, default=30)
    args = parser.parse_args()

    with args.har.open("r", encoding="utf-8") as handle:
        har = json.load(handle)

    candidates = analyze(har)[: max(1, args.top)]

    if args.json_out:
        args.json_out.write_text(
            json.dumps(candidates, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"candidate_count={len(candidates)}")
    for rank, candidate in enumerate(candidates, 1):
        print(
            f"[{rank:02d}] score={candidate['rank_score']:02d} "
            f"{candidate['method']} "
            f"{candidate['host']}{candidate['path']} "
            f"status={candidate['status']}"
        )
        print("     reasons=" + ",".join(candidate["reasons"]))

        dates = candidate["response"]["date_samples"]
        if dates:
            print("     dates=" + ",".join(dates))

        star_fields = candidate["response"]["star_field_samples"]
        if star_fields:
            print(
                "     star_fields="
                + json.dumps(star_fields[:4], ensure_ascii=False)
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
