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


@dataclass
class ArticleRecord:
    article_id: str
    publish_date: str | None
    title: str
    text: str
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


def _read_json(path: Path) -> tuple[str | None, str | None, str]:
    obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(obj, dict):
        return None, None, json.dumps(obj, ensure_ascii=False)

    date = next((str(obj[k]) for k in ("publish_date", "date", "published_at", "time") if obj.get(k)), None)
    title = next((str(obj[k]) for k in ("title", "name") if obj.get(k)), None)
    text = next((str(obj[k]) for k in ("text", "content", "body", "article") if obj.get(k)), None)
    if text is None:
        text = json.dumps(obj, ensure_ascii=False)
    return date, title, text


def _read_article(path: Path) -> tuple[str | None, str | None, str]:
    suffix = path.suffix.lower()
    if suffix in {".html", ".htm"}:
        raw = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(raw, "lxml")
        for node in soup(["script", "style", "noscript"]):
            node.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else None
        text = soup.get_text("\n", strip=True)
        return None, title, text
    if suffix == ".json":
        return _read_json(path)
    return None, None, path.read_text(encoding="utf-8", errors="replace")


def iter_corpus_files(root: Path, include_extensions: Iterable[str]) -> Iterable[Path]:
    extensions = {ext.lower() for ext in include_extensions}
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix.lower() in extensions:
            yield path


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
            embedded_date, embedded_title, text = _read_article(path)
        except Exception as exc:
            embedded_date, embedded_title, text = None, None, f"[PARSE_ERROR] {type(exc).__name__}: {exc}"

        duplicate_of = first_by_hash.get(digest)
        if duplicate_of is None:
            first_by_hash[digest] = article_id

        records.append(
            ArticleRecord(
                article_id=article_id,
                publish_date=(embedded_date or path_date),
                title=(path_title or embedded_title or path.stem).strip(),
                text=text,
                relative_path=rel,
                suffix=path.suffix.lower(),
                size_bytes=path.stat().st_size,
                sha256=digest,
                duplicate_of=duplicate_of,
            )
        )

    df = pd.DataFrame([asdict(record) for record in records])
    articles_parquet.parent.mkdir(parents=True, exist_ok=True)
    manifest_parquet.parent.mkdir(parents=True, exist_ok=True)

    if df.empty:
        df = pd.DataFrame(columns=[field for field in ArticleRecord.__dataclass_fields__])

    df.to_parquet(articles_parquet, index=False)
    df.drop(columns=["text"], errors="ignore").to_parquet(manifest_parquet, index=False)
    return df
