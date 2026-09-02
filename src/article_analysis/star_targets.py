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

# The generic candidate scanner below intentionally has broad recall. Building the
# actual daily A-share Target needs a narrower, article-opening extractor so that
# prior-article links, book ratings, intraday values and global-market stars do not
# become labels.
PRECISE_STAR_TOKEN = (
    r"(?<![\d.\-–—~～至])(?<!\d到)"
    r"(?P<star>[1-5](?:\.\d)?)(?!\s*[-–—~～至到])\s*星(?:级)?"
)
ASHARE_ARTICLE_MARKER = "指数估值数据"
GLOBAL_ARTICLE_MARKER = "美股指数估值数据"
OPENING_TEXT_CHARS = 3000

CLOSE_STAR_RE = re.compile(
    r"(?:截止到收盘|截至收盘|截止收盘|到收盘(?:的时候)?|收盘(?:时|后)?)"
    r"[^。！？\n]{0,100}?" + PRECISE_STAR_TOKEN
)
TODAY_MARKET_STAR_RE = re.compile(
    r"(?:今天|今日)(?:大盘|A股|市场)[^。！？\n]{0,140}?" + PRECISE_STAR_TOKEN
)
OPENING_STATE_STAR_RE = re.compile(
    r"(?:还在|回到|回到了|重回|达到|涨到|上涨到|摸到)\s*" + PRECISE_STAR_TOKEN
)
APPROX_RANGE_RE = re.compile(
    r"(?P<low>[1-5](?:\.\d)?)\s*[-–—~～至到]\s*"
    r"(?P<high>[1-5](?:\.\d)?)\s*星(?:级)?"
)
NEAR_THRESHOLD_RE = re.compile(
    r"距离\s*(?P<star>[1-5](?:\.\d)?)\s*星(?:级)?\s*很接近"
)
MARKET_CLOSED_RE = re.compile(r"A股没有交易[^。！？\n]{0,60}")

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


@dataclass(frozen=True)
class RealtimeStarObservation:
    star: float
    evidence: str
    evidence_method: str
    confidence: float


def _context(text: str, start: int, end: int, chars: int) -> str:
    left = max(0, start - chars)
    right = min(len(text), end + chars)
    return re.sub(r"\s+", " ", text[left:right]).strip()


def _is_ashare_daily_article(title: str) -> bool:
    return ASHARE_ARTICLE_MARKER in title and GLOBAL_ARTICLE_MARKER not in title


def extract_realtime_observation_from_article(
    *,
    title: str,
    text: str,
    opening_chars: int = OPENING_TEXT_CHARS,
) -> RealtimeStarObservation | None:
    """Extract one exact closing A-share star from the article opening.

    Evidence priority is deliberate:

    1. an explicit closing cue (``截止到收盘`` / ``到收盘``);
    2. a same-sentence ``今天大盘`` style statement;
    3. the first opening-state phrase such as ``还在4.2星``.

    The Markdown H1 is removed before scanning. This matters for articles such as
    2026-01-06, whose title rounds the regime to ``3星级`` while the body gives the
    exact closing value ``3.9星``. Range-only statements such as ``4.9-5星`` are
    rejected by ``PRECISE_STAR_TOKEN``.
    """
    if not _is_ashare_daily_article(title or ""):
        return None

    lines = (text or "").splitlines()
    opening = "\n".join(lines[1:])[:opening_chars] if lines else ""
    patterns = (
        ("closing_statement", CLOSE_STAR_RE, 1.0),
        ("today_market_statement", TODAY_MARKET_STAR_RE, 0.995),
        ("opening_state_statement", OPENING_STATE_STAR_RE, 0.99),
    )
    for method, pattern, confidence in patterns:
        match = pattern.search(opening)
        if match:
            return RealtimeStarObservation(
                star=float(match.group("star")),
                evidence=re.sub(r"\s+", " ", match.group(0)).strip(),
                evidence_method=method,
                confidence=confidence,
            )
    return None


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


def build_daily_realtime_targets(
    articles_parquet: Path,
    output_csv: Path,
    *,
    opening_chars: int = OPENING_TEXT_CHARS,
) -> pd.DataFrame:
    """Build a conservative daily A-share Target directly from article openings.

    One exact observation is selected per canonical article. If more than one
    canonical article exists for a date and their values disagree, that date is
    omitted instead of being guessed.
    """
    articles = pd.read_parquet(articles_parquet)
    rows: list[dict] = []
    for article in articles.itertuples(index=False):
        if not _is_canonical(article):
            continue
        observation = extract_realtime_observation_from_article(
            title=article.title,
            text=article.text or "",
            opening_chars=opening_chars,
        )
        if observation is None:
            continue
        rows.append(
            {
                "date": getattr(article, "publish_date", None),
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

    result = pd.DataFrame(rows)
    if not result.empty:
        keep: list[pd.DataFrame] = []
        for _, group in result.groupby("date", sort=False, dropna=False):
            if group["star"].nunique(dropna=True) == 1:
                keep.append(group.sort_values("confidence", ascending=False).head(1))
        result = pd.concat(keep, ignore_index=True) if keep else result.iloc[0:0]
        result = result.sort_values("date", na_position="last").reset_index(drop=True)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_csv, index=False, encoding="utf-8-sig")
    return result


def build_daily_target_review_queue(
    articles_parquet: Path,
    output_csv: Path,
    *,
    opening_chars: int = OPENING_TEXT_CHARS,
) -> pd.DataFrame:
    """Account for A-share daily articles that lack one exact text Target."""
    articles = pd.read_parquet(articles_parquet)
    rows: list[dict] = []
    for article in articles.itertuples(index=False):
        if not _is_canonical(article) or not _is_ashare_daily_article(article.title):
            continue
        if extract_realtime_observation_from_article(
            title=article.title,
            text=article.text or "",
            opening_chars=opening_chars,
        ) is not None:
            continue

        lines = (article.text or "").splitlines()
        opening = "\n".join(lines[1:])[:opening_chars] if lines else ""
        compact = re.sub(r"\s+", " ", opening).strip()
        range_match = APPROX_RANGE_RE.search(opening)
        threshold_match = NEAR_THRESHOLD_RE.search(opening)

        market_closed_match = MARKET_CLOSED_RE.search(opening)
        if market_closed_match:
            reason = "market_closed_no_new_target"
            evidence = re.sub(r"\s+", " ", market_closed_match.group(0)).strip()
        elif range_match:
            reason = "approximate_range"
            evidence = re.sub(r"\s+", " ", range_match.group(0)).strip()
        elif threshold_match:
            reason = "near_threshold_only"
            evidence = re.sub(r"\s+", " ", threshold_match.group(0)).strip()
        else:
            reason = "no_exact_text_evidence"
            evidence = compact[:240]

        rows.append(
            {
                "date": getattr(article, "publish_date", None),
                "market": "A股",
                "article_id": article.article_id,
                "title": article.title,
                "source_url": getattr(article, "source_url", None),
                "reason": reason,
                "range_low": (
                    min(float(range_match.group("low")), float(range_match.group("high")))
                    if range_match
                    else None
                ),
                "range_high": (
                    max(float(range_match.group("low")), float(range_match.group("high")))
                    if range_match
                    else None
                ),
                "reference_star": float(threshold_match.group("star")) if threshold_match else None,
                "evidence": evidence,
                "review_status": "pending_manual_or_image_review",
                "relative_path": article.relative_path,
            }
        )

    result = pd.DataFrame(rows)
    if not result.empty:
        result = result.sort_values("date", na_position="last").reset_index(drop=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_csv, index=False, encoding="utf-8-sig")
    return result
