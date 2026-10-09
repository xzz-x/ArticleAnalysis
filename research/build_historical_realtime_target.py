from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from article_analysis.star_targets import (
    APPROX_RANGE_RE,
    ASHARE_ARTICLE_MARKER,
    GLOBAL_ARTICLE_MARKER,
    MARKET_CLOSED_RE,
    NEAR_THRESHOLD_RE,
    extract_realtime_observation_from_article,
)


REPO = Path(__file__).resolve().parents[1]
DEFAULT_ARTICLES = REPO / ".local" / "screw_star" / "articles.parquet"
DERIVED = REPO / "data" / "derived"

TARGET_OUTPUT = DERIVED / "star_target_historical_direct.csv"
REVIEW_OUTPUT = DERIVED / "star_target_historical_review_queue.csv"
CONFLICT_OUTPUT = DERIVED / "star_target_historical_source_conflicts.csv"
AUDIT_OUTPUT = DERIVED / "star_target_historical_audit.json"

CURRENT_RANGE_CUES = (
    "今天",
    "今日",
    "目前",
    "当前",
    "收盘",
    "还在",
    "回到",
    "回到了",
    "重回",
    "边界",
)
NONCURRENT_RANGE_CUES = (
    "上周",
    "上个月",
    "昨天",
    "昨日",
    "此前",
    "之前",
    "当时",
    "曾经",
    "历史",
    "如果",
    "假如",
    "才能",
    "才回到",
)


def is_canonical(row: object) -> bool:
    value = getattr(row, "is_canonical", None)
    if value is not None:
        return bool(value)
    return not bool(getattr(row, "duplicate_of", None))


def is_ashare_daily(title: str) -> bool:
    return ASHARE_ARTICLE_MARKER in (title or "") and GLOBAL_ARTICLE_MARKER not in (title or "")


def sentence_chunks(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[。！？\n])", text or "") if part.strip()]


def classify_review(opening: str) -> dict[str, object]:
    market_closed = MARKET_CLOSED_RE.search(opening)
    if market_closed:
        return {
            "reason": "market_closed_no_new_target",
            "range_low": None,
            "range_high": None,
            "reference_star": None,
            "evidence": re.sub(r"\s+", " ", market_closed.group(0)).strip(),
        }

    for sentence in sentence_chunks(opening):
        compact = re.sub(r"\s+", " ", sentence).strip()
        if any(cue in compact for cue in NONCURRENT_RANGE_CUES):
            continue
        if not any(cue in compact for cue in CURRENT_RANGE_CUES):
            continue

        range_match = APPROX_RANGE_RE.search(compact)
        if range_match:
            low = float(range_match.group("low"))
            high = float(range_match.group("high"))
            return {
                "reason": "approximate_range",
                "range_low": min(low, high),
                "range_high": max(low, high),
                "reference_star": None,
                "evidence": compact,
            }

        threshold = NEAR_THRESHOLD_RE.search(compact)
        if threshold:
            return {
                "reason": "near_threshold_only",
                "range_low": None,
                "range_high": None,
                "reference_star": float(threshold.group("star")),
                "evidence": compact,
            }

    compact = re.sub(r"\s+", " ", opening).strip()
    return {
        "reason": "no_exact_text_evidence",
        "range_low": None,
        "range_high": None,
        "reference_star": None,
        "evidence": compact[:320],
    }


def resolve_exact_rows(rows: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if rows.empty:
        return rows, pd.DataFrame(columns=["date", "reason", "values", "article_ids"])
    kept: list[pd.DataFrame] = []
    conflicts: list[dict[str, object]] = []
    for date_value, group in rows.groupby("date", sort=True):
        values = sorted(set(float(v) for v in group["star"].dropna()))
        if len(values) == 1:
            kept.append(group.sort_values("confidence", ascending=False).head(1))
        else:
            conflicts.append(
                {
                    "date": date_value,
                    "reason": "conflicting_exact_articles",
                    "values": "|".join(str(v) for v in values),
                    "article_ids": "|".join(group["article_id"].astype(str)),
                }
            )
    exact = pd.concat(kept, ignore_index=True) if kept else rows.iloc[0:0].copy()
    return exact.sort_values("date").reset_index(drop=True), pd.DataFrame(conflicts)


def compare_legacy(exact: pd.DataFrame, start_year: int, end_year: int) -> pd.DataFrame:
    conflicts: list[pd.DataFrame] = []
    for year in range(start_year, end_year + 1):
        path = REPO / "data" / "verified" / f"daily_star_{year}.csv"
        if not path.exists():
            continue
        legacy = pd.read_csv(path)
        legacy["date"] = pd.to_datetime(legacy["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        legacy["legacy_star"] = pd.to_numeric(legacy.get("star"), errors="coerce")
        direct = exact[exact["date"].str.startswith(str(year))][
            ["date", "star", "confidence", "evidence_method", "evidence", "article_id", "title"]
        ]
        merged = direct.merge(
            legacy[["date", "legacy_star", "status"]],
            on="date",
            how="inner",
            suffixes=("_direct", "_legacy"),
        )
        mismatch = merged[
            merged["legacy_star"].notna()
            & ((merged["star"] - merged["legacy_star"]).abs() > 1e-9)
        ].copy()
        if not mismatch.empty:
            conflicts.append(mismatch)
    return pd.concat(conflicts, ignore_index=True) if conflicts else pd.DataFrame()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recover historical realtime A-share star targets from the canonical article corpus"
    )
    parser.add_argument("--articles-parquet", type=Path, default=DEFAULT_ARTICLES)
    parser.add_argument("--start-year", type=int, default=2012)
    parser.add_argument("--end-year", type=int, default=2024)
    args = parser.parse_args()

    articles = pd.read_parquet(args.articles_parquet)
    exact_rows: list[dict[str, object]] = []
    review_rows: list[dict[str, object]] = []
    article_counts: dict[int, int] = {}

    for article in articles.itertuples(index=False):
        if not is_canonical(article) or not is_ashare_daily(str(article.title)):
            continue
        published = pd.to_datetime(getattr(article, "publish_date", None), errors="coerce")
        if pd.isna(published):
            continue
        year = int(published.year)
        if year < args.start_year or year > args.end_year:
            continue
        article_counts[year] = article_counts.get(year, 0) + 1
        date_value = published.strftime("%Y-%m-%d")

        observation = extract_realtime_observation_from_article(
            title=str(article.title),
            text=str(article.text or ""),
            publish_date=date_value,
        )
        if observation is not None:
            exact_rows.append(
                {
                    "date": date_value,
                    "star": observation.star,
                    "market": "A股",
                    "source_type": "公众号当日估值文章",
                    "realtime_or_backfilled": "realtime",
                    "article_id": article.article_id,
                    "title": article.title,
                    "source_url": getattr(article, "source_url", None),
                    "confidence": observation.confidence,
                    "evidence": observation.evidence,
                    "evidence_method": observation.evidence_method,
                    "review_status": "auto_high_confidence",
                    "relative_path": article.relative_path,
                }
            )
            continue

        lines = str(article.text or "").splitlines()
        opening = "\n".join(lines[1:])[:3000] if lines else ""
        review = classify_review(opening)
        review_rows.append(
            {
                "date": date_value,
                "market": "A股",
                "article_id": article.article_id,
                "title": article.title,
                "source_url": getattr(article, "source_url", None),
                **review,
                "review_status": "pending_manual_or_image_review",
                "relative_path": article.relative_path,
            }
        )

    exact_all = pd.DataFrame(exact_rows)
    review = pd.DataFrame(review_rows)
    exact, exact_conflicts = resolve_exact_rows(exact_all)
    if not review.empty and not exact.empty:
        review = review[~review["date"].isin(set(exact["date"]))].copy()
    review = review.sort_values(["date", "reason"]).reset_index(drop=True) if not review.empty else review

    source_conflicts = compare_legacy(exact, args.start_year, args.end_year)

    DERIVED.mkdir(parents=True, exist_ok=True)
    exact.to_csv(TARGET_OUTPUT, index=False, encoding="utf-8-sig")
    review.to_csv(REVIEW_OUTPUT, index=False, encoding="utf-8-sig")
    source_conflicts.to_csv(CONFLICT_OUTPUT, index=False, encoding="utf-8-sig")

    present_years = sorted(article_counts)
    expected_years = list(range(args.start_year, args.end_year + 1))
    audit = {
        "articlesParquet": str(args.articles_parquet),
        "requestedYears": expected_years,
        "corpusYearsPresent": present_years,
        "corpusMissingYears": [year for year in expected_years if year not in article_counts],
        "articleCountByYear": {str(k): int(v) for k, v in sorted(article_counts.items())},
        "exactTargets": int(len(exact)),
        "reviewRows": int(len(review)),
        "reviewReasonCounts": (
            review["reason"].value_counts().astype(int).to_dict() if not review.empty else {}
        ),
        "sameDayExactConflicts": (
            exact_conflicts.to_dict(orient="records") if not exact_conflicts.empty else []
        ),
        "legacyExactConflictCount": int(len(source_conflicts)),
        "policy": [
            "Only canonical A-share 指数估值数据 articles are scanned.",
            "Historical, hypothetical, threshold and intraday star mentions are rejected as exact labels.",
            "Exact closing/current evidence has priority; ranges remain ranges and are not collapsed.",
            "Missing corpus years are reported explicitly rather than backfilled or guessed.",
        ],
    }
    AUDIT_OUTPUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
