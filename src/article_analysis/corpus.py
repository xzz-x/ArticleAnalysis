from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd
from bs4 import BeautifulSoup

DATE_TITLE_RE = re.compile(r"\[(?P<date>\d{4}-\d{2}-\d{2})(?:-\d{4})?\](?P<title>.+)")
MARKDOWN_H1_RE = re.compile(r"(?m)^\s*#\s+(?P<title>.+?)\s*$")
MARKDOWN_DATE_RE = re.compile(
    r"(?P<year>\d{4})年(?P<month>\d{2})月(?P<day>\d{2})日(?:\s+\d{1,2}:\d{2})?"
)
SUFFIX_PRIORITY = {".md": 0, ".markdown": 0, ".html": 1, ".htm": 1, ".json": 2, ".txt": 3}


@dataclass
class ArticleRecord:
    article_id: str
    article_key: str
    canonical_article_id: str | None
    is_canonical: bool
    publish_date: str | None
    title: str
    text: str
    source_url: str | None
    relative_path: str
    suffix: str
    size_bytes: int
    sha256: str
    duplicate_of: str | None = None


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _path_metadata(path: Path) -> tuple[str | None, str]:
    candidates = [path.stem, path.parent.name]
    for candidate in candidates:
        match = DATE_TITLE_RE.search(candidate)
        if match:
            return match.group("date"), match.group("title").strip()
    return None, path.stem.strip()


def _article_key(path: Path) -> str:
    """Stable key shared by HTML/Markdown variants and duplicate Drive exports."""
    stem = re.sub(r"\s+", "", path.stem).strip()
    return stem


def _read_json(path: Path) -> tuple[str | None, str | None, str, str | None]:
    obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(obj, dict):
        return None, None, json.dumps(obj, ensure_ascii=False), None

    date = next((str(obj[k]) for k in ("publish_date", "date", "published_at", "time") if obj.get(k)), None)
    title = next((str(obj[k]) for k in ("title", "name") if obj.get(k)), None)
    text = next((str(obj[k]) for k in ("text", "content", "body", "article") if obj.get(k)), None)
    source_url = next((str(obj[k]) for k in ("source_url", "url", "link") if obj.get(k)), None)
    if text is None:
        text = json.dumps(obj, ensure_ascii=False)
    return date, title, text, source_url


def _markdown_metadata(raw: str) -> tuple[str | None, str | None]:
    title_match = MARKDOWN_H1_RE.search(raw)
    title = title_match.group("title").strip() if title_match else None

    date_match = MARKDOWN_DATE_RE.search(raw[:1500])
    if date_match:
        date = "{year}-{month}-{day}".format(**date_match.groupdict())
    else:
        date = None
    return date, title


def _html_metadata(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    title = None
    for attrs in (
        {"property": "og:title"},
        {"property": "twitter:title"},
        {"name": "twitter:title"},
    ):
        node = soup.find("meta", attrs=attrs)
        if node and node.get("content"):
            title = str(node.get("content")).strip()
            if title:
                break

    if not title:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True) or None

    source_url = None
    node = soup.find("meta", attrs={"property": "og:url"})
    if node and node.get("content"):
        source_url = str(node.get("content")).strip() or None

    return title, source_url


def _read_article(path: Path) -> tuple[str | None, str | None, str, str | None]:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        raw = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(raw, "lxml")
        embedded_title, source_url = _html_metadata(soup)
        for node in soup(["script", "style", "noscript"]):
            node.decompose()
        text = soup.get_text("\n", strip=True)
        return None, embedded_title, text, source_url

    if suffix == ".json":
        return _read_json(path)

    raw = path.read_text(encoding="utf-8", errors="replace")
    if suffix in {".md", ".markdown"}:
        embedded_date, embedded_title = _markdown_metadata(raw)
        return embedded_date, embedded_title, raw, None

    return None, None, raw, None


def iter_corpus_files(root: Path, include_extensions: Iterable[str]) -> Iterable[Path]:
    extensions = {ext.lower() for ext in include_extensions}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in extensions:
            yield path


def _canonicalize(records: list[ArticleRecord]) -> None:
    by_key: dict[str, list[ArticleRecord]] = {}
    for record in records:
        by_key.setdefault(record.article_key, []).append(record)

    for members in by_key.values():
        source_url = next((m.source_url for m in members if m.source_url), None)

        def rank(record: ArticleRecord) -> tuple[int, int, int, str]:
            parse_error = int(record.text.startswith("[PARSE_ERROR]"))
            suffix_rank = SUFFIX_PRIORITY.get(record.suffix, 99)
            exact_duplicate = int(record.duplicate_of is not None)
            return parse_error, suffix_rank, exact_duplicate, record.relative_path

        canonical = min(members, key=rank)
        for member in members:
            member.canonical_article_id = canonical.article_id
            member.is_canonical = member.article_id == canonical.article_id
            if not member.source_url and source_url:
                member.source_url = source_url


def ingest_corpus(
    corpus_root: Path,
    articles_parquet: Path,
    manifest_parquet: Path,
    include_extensions: Iterable[str],
) -> pd.DataFrame:
    if not corpus_root.exists():
        raise FileNotFoundError(f"Corpus root does not exist: {corpus_root}")

    records: list[ArticleRecord] = []
    first_by_hash: dict[str, str] = {}

    for path in iter_corpus_files(corpus_root, include_extensions):
        rel = path.relative_to(corpus_root).as_posix()
        digest = sha256_file(path)
        article_id = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:20]
        path_date, path_title = _path_metadata(path)

        try:
            embedded_date, embedded_title, text, source_url = _read_article(path)
        except Exception as exc:
            embedded_date, embedded_title, source_url = None, None, None
            text = f"[PARSE_ERROR] {type(exc).__name__}: {exc}"

        duplicate_of = first_by_hash.get(digest)
        if duplicate_of is None:
            first_by_hash[digest] = article_id

        # The downloaded filename has punctuation removed (e.g. 4.9 -> 49).
        # Prefer the embedded WeChat/Markdown title whenever available.
        title = (embedded_title or path_title or path.stem).strip()

        records.append(
            ArticleRecord(
                article_id=article_id,
                article_key=_article_key(path),
                canonical_article_id=None,
                is_canonical=False,
                publish_date=(embedded_date or path_date),
                title=title,
                text=text,
                source_url=source_url,
                relative_path=rel,
                suffix=path.suffix.lower(),
                size_bytes=path.stat().st_size,
                sha256=digest,
                duplicate_of=duplicate_of,
            )
        )

    _canonicalize(records)
    df = pd.DataFrame([asdict(record) for record in records])
    articles_parquet.parent.mkdir(parents=True, exist_ok=True)
    manifest_parquet.parent.mkdir(parents=True, exist_ok=True)

    if df.empty:
        df = pd.DataFrame(columns=[field for field in ArticleRecord.__dataclass_fields__])

    df.to_parquet(articles_parquet, index=False)
    df.drop(columns=["text"], errors="ignore").to_parquet(manifest_parquet, index=False)
    return df
