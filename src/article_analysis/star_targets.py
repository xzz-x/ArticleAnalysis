from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ARABIC_HALF_RE = re.compile(r"(?<!\d)(?P<star>[1-5])\s*星半")
ARABIC_STAR_RE = re.compile(r"(?<!\d)(?P<star>[1-6](?:\.\d)?)\s*星(?!半)(?:级)?")
CHINESE_HALF_RE = re.compile(r"(?P<star>[一二三四五])\s*星半")
CHINESE_STAR_RE = re.compile(r"(?P<star>[一二三四五六])\s*星(?!半)(?:级)?")
CHINESE_NUMBERS = {"一": 1.0, "二": 2.0, "三": 3.0, "四": 4.0, "五": 5.0, "六": 6.0}


@dataclass(frozen=True)
class StarCandidate:
    article_id: str
    publish_date: str | None
    title: str
    star: float
    context: str
    pattern: str
    confidence: float
    relative_path: str


def _confidence(title: str, context: str) -> float:
    joined = f"{title} {context}"
    if "螺丝钉星级" in joined or "今天几星" in joined:
        return 0.98
    if "今日" in context and "星" in context:
        return 0.95
    if "指数估值数据" in title and "星" in context:
        return 0.93
    if "目前" in context and "星" in context:
        return 0.88
    if "星级" in joined:
        return 0.80
    return 0.55


def _context(text: str, start: int, end: int, chars: int) -> str:
    left = max(0, start - chars)
    right = min(len(text), end + chars)
    return re.sub(r"\s+", " ", text[left:right]).strip()


def extract_candidates_from_article(
    *,
    article_id: str,
    publish_date: str | None,
    title: str,
    text: str,
    relative_path: str,
    context_chars: int = 140,
    min_star: float = 1.0,
    max_star: float = 6.0,
) -> list[StarCandidate]:
    candidates: list[StarCandidate] = []
    seen: set[tuple[int, int, float]] = set()

    patterns = (
        ("arabic_half", ARABIC_HALF_RE),
        ("arabic", ARABIC_STAR_RE),
        ("chinese_half", CHINESE_HALF_RE),
        ("chinese", CHINESE_STAR_RE),
    )

    for pattern_name, pattern in patterns:
        for match in pattern.finditer(text or ""):
            raw_star = match.group("star")
            if pattern_name == "arabic":
                star = float(raw_star)
            elif pattern_name == "arabic_half":
                star = float(raw_star) + 0.5
            elif pattern_name == "chinese_half":
                star = CHINESE_NUMBERS[raw_star] + 0.5
            else:
                star = CHINESE_NUMBERS[raw_star]

            if not (min_star <= star <= max_star):
                continue

            key = (match.start(), match.end(), star)
            if key in seen:
                continue
            seen.add(key)

            context = _context(text, match.start(), match.end(), context_chars)
            candidates.append(
                StarCandidate(
                    article_id=article_id,
                    publish_date=publish_date,
                    title=title,
                    star=star,
                    context=context,
                    pattern=pattern_name,
                    confidence=_confidence(title, context),
                    relative_path=relative_path,
                )
            )

    return candidates


def extract_star_candidates(
    articles_parquet: Path,
    output_csv: Path,
    *,
    context_chars: int = 140,
    min_star: float = 1.0,
    max_star: float = 6.0,
) -> pd.DataFrame:
    articles = pd.read_parquet(articles_parquet)
    rows: list[dict] = []

    for article in articles.itertuples(index=False):
        if getattr(article, "duplicate_of", None):
            continue
        for candidate in extract_candidates_from_article(
            article_id=article.article_id,
            publish_date=getattr(article, "publish_date", None),
            title=article.title,
            text=article.text or "",
            relative_path=article.relative_path,
            context_chars=context_chars,
            min_star=min_star,
            max_star=max_star,
        ):
            rows.append(candidate.__dict__)

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(
            ["publish_date", "confidence", "article_id"],
            ascending=[True, False, True],
            na_position="last",
        )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_csv, index=False, encoding="utf-8-sig")
    return result
