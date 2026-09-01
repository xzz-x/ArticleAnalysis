from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ARABIC_HALF_RE = re.compile(r"(?<!\d)(?P<star>[1-5])\s*星半")
ARABIC_STAR_RE = re.compile(r"(?<![\d.])(?P<star>[1-6](?:\.\d)?)\s*星(?!半)(?:级)?")
# Downloaded filenames sometimes remove decimal punctuation: 4.9 -> 49星.
# This pattern is used only on the title as a fallback.
COMPACT_TITLE_STAR_RE = re.compile(r"(?<!\d)(?P<whole>[1-5])(?P<decimal>\d)\s*星(?:级)?")
CHINESE_HALF_RE = re.compile(r"(?P<star>[一二三四五])\s*星半")
CHINESE_STAR_RE = re.compile(r"(?P<star>[一二三四五六])\s*星(?!半)(?:级)?")
CHINESE_NUMBERS = {"一": 1.0, "二": 2.0, "三": 3.0, "四": 4.0, "五": 5.0, "六": 6.0}

RANGE_RE = re.compile(
    r"(?:[1-6](?:\.\d)?|[一二三四五六])\s*星(?:级)?\s*[-–—~～至到]\s*"
    r"(?:[1-6](?:\.\d)?|[一二三四五六])"
)
CURRENT_CUES = (
    "截止到收盘",
    "截至收盘",
    "截止收盘",
    "今天大盘",
    "今日大盘",
    "今天市场",
    "今日市场",
    "目前",
    "当前",
    "今天回到",
    "今日回到",
    "又回到",
    "回到",
)
HISTORICAL_CUES = (
    "当时",
    "比如",
    "例如",
    "历史",
    "此前",
    "之前",
    "曾经",
    "过去",
    "熊市",
    "2024年",
    "2023年",
    "2022年",
    "2021年",
    "2020年",
    "2019年",
    "2018年",
    "2017年",
    "2016年",
    "2015年",
    "2014年",
    "2013年",
    "2012年",
)
BOILERPLATE_CUES = (
    "1星为泡沫阶段",
    "5星为投资价值最高阶段",
    "不同星级代表的含义",
    "5星级-5.9星级",
    "4星级-4.9星级",
    "3星级-3.9星级",
)


@dataclass(frozen=True)
class StarCandidate:
    article_id: str
    publish_date: str | None
    title: str
    source_url: str | None
    star: float
    context: str
    pattern: str
    source_location: str
    relation: str
    confidence: float
    relative_path: str


def _context(text: str, start: int, end: int, chars: int) -> str:
    left = max(0, start - chars)
    right = min(len(text), end + chars)
    return re.sub(r"\s+", " ", text[left:right]).strip()


def _relation(title: str, context: str, source_location: str) -> str:
    joined = f"{title} {context}"
    if any(cue in joined for cue in BOILERPLATE_CUES) or RANGE_RE.search(context):
        return "range_or_rule"

    if source_location == "title" and "指数估值数据" in title and "回到" in title:
        return "realtime"

    has_current = any(cue in context for cue in CURRENT_CUES)
    has_historical = any(cue in context for cue in HISTORICAL_CUES)

    if has_current and not has_historical:
        return "realtime"
    if has_historical:
        return "historical"
    return "generic"


def _confidence(title: str, context: str, source_location: str, relation: str) -> float:
    if relation == "range_or_rule":
        return 0.20
    if relation == "historical":
        return 0.55

    if relation == "realtime":
        if source_location == "title" and "指数估值数据" in title and "回到" in title:
            return 0.99
        if "截止到收盘" in context or "截至收盘" in context or "截止收盘" in context:
            return 0.995
        if "今天大盘" in context or "今日大盘" in context:
            return 0.99
        if "目前" in context or "当前" in context:
            return 0.96
        return 0.93

    joined = f"{title} {context}"
    if "螺丝钉星级" in joined or "今天几星" in joined:
        return 0.82
    if "指数估值数据" in title:
        return 0.72
    if "星级" in joined:
        return 0.62
    return 0.45


def _star_value(pattern_name: str, match: re.Match[str]) -> float:
    if pattern_name == "arabic":
        return float(match.group("star"))
    if pattern_name == "arabic_half":
        return float(match.group("star")) + 0.5
    if pattern_name == "compact_title":
        return float(f"{match.group('whole')}.{match.group('decimal')}")
    if pattern_name == "chinese_half":
        return CHINESE_NUMBERS[match.group("star")] + 0.5
    return CHINESE_NUMBERS[match.group("star")]


def _scan_source(
    *,
    source: str,
    source_location: str,
    article_id: str,
    publish_date: str | None,
    title: str,
    source_url: str | None,
    relative_path: str,
    context_chars: int,
    min_star: float,
    max_star: float,
) -> list[StarCandidate]:
    candidates: list[StarCandidate] = []
    seen: set[tuple[str, int, int, float]] = set()

    patterns: list[tuple[str, re.Pattern[str]]] = [
        ("arabic_half", ARABIC_HALF_RE),
        ("arabic", ARABIC_STAR_RE),
        ("chinese_half", CHINESE_HALF_RE),
        ("chinese", CHINESE_STAR_RE),
    ]
    if source_location == "title":
        patterns.append(("compact_title", COMPACT_TITLE_STAR_RE))

    for pattern_name, pattern in patterns:
        for match in pattern.finditer(source or ""):
            star = _star_value(pattern_name, match)
            if not (min_star <= star <= max_star):
                continue

            key = (source_location, match.start(), match.end(), star)
            if key in seen:
                continue
            seen.add(key)

            context = (
                source.strip()
                if source_location == "title"
                else _context(source, match.start(), match.end(), context_chars)
            )
            relation = _relation(title, context, source_location)
            candidates.append(
                StarCandidate(
                    article_id=article_id,
                    publish_date=publish_date,
                    title=title,
                    source_url=source_url,
                    star=star,
                    context=context,
                    pattern=pattern_name,
                    source_location=source_location,
                    relation=relation,
                    confidence=_confidence(title, context, source_location, relation),
                    relative_path=relative_path,
                )
            )

    return candidates


def extract_candidates_from_article(
    *,
    article_id: str,
    publish_date: str | None,
    title: str,
    text: str,
    relative_path: str,
    source_url: str | None = None,
    context_chars: int = 140,
    min_star: float = 1.0,
    max_star: float = 6.0,
) -> list[StarCandidate]:
    rows = _scan_source(
        source=title or "",
        source_location="title",
        article_id=article_id,
        publish_date=publish_date,
        title=title,
        source_url=source_url,
        relative_path=relative_path,
        context_chars=context_chars,
        min_star=min_star,
        max_star=max_star,
    )
    rows.extend(
        _scan_source(
            source=text or "",
            source_location="text",
            article_id=article_id,
            publish_date=publish_date,
            title=title,
            source_url=source_url,
            relative_path=relative_path,
            context_chars=context_chars,
            min_star=min_star,
            max_star=max_star,
        )
    )
    return rows


def _is_canonical(article: object) -> bool:
    value = getattr(article, "is_canonical", None)
    if value is not None:
        return bool(value)
    return not bool(getattr(article, "duplicate_of", None))


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
        if not _is_canonical(article):
            continue
        for candidate in extract_candidates_from_article(
            article_id=article.article_id,
            publish_date=getattr(article, "publish_date", None),
            title=article.title,
            text=article.text or "",
            source_url=getattr(article, "source_url", None),
            relative_path=article.relative_path,
            context_chars=context_chars,
            min_star=min_star,
            max_star=max_star,
        ):
            rows.append(candidate.__dict__)

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values(
            ["publish_date", "confidence", "article_id", "source_location"],
            ascending=[True, False, True, True],
            na_position="last",
        )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_csv, index=False, encoding="utf-8-sig")
    return result


def build_realtime_target_seed(candidates: pd.DataFrame, output_csv: Path) -> pd.DataFrame:
    """Create a conservative seed Target from unambiguous realtime article statements.

    This does not pretend to be the final historical Target. It only keeps dates where
    all high-confidence realtime candidates in an article agree on one star value.
    """
    if candidates.empty:
        result = pd.DataFrame(
            columns=[
                "date",
                "star",
                "article_id",
                "title",
                "source_url",
                "confidence",
                "context",
                "review_status",
            ]
        )
    else:
        realtime = candidates[
            (candidates["relation"] == "realtime") & (candidates["confidence"] >= 0.90)
        ].copy()
        rows: list[dict] = []
        for article_id, group in realtime.groupby("article_id", sort=False):
            stars = sorted(set(float(v) for v in group["star"].dropna()))
            if len(stars) != 1:
                continue
            best = group.sort_values("confidence", ascending=False).iloc[0]
            rows.append(
                {
                    "date": best["publish_date"],
                    "star": stars[0],
                    "article_id": article_id,
                    "title": best["title"],
                    "source_url": best.get("source_url"),
                    "confidence": float(best["confidence"]),
                    "context": best["context"],
                    "review_status": "seed_auto",
                }
            )
        result = pd.DataFrame(rows)
        if not result.empty:
            result = result.sort_values(["date", "confidence"], ascending=[True, False])
            # Multiple same-day articles may repeat the same market star. Keep the strongest row.
            result = result.drop_duplicates(subset=["date", "star"], keep="first")

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_csv, index=False, encoding="utf-8-sig")
    return result
