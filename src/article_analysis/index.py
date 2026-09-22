from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd


def _create_fts(conn: sqlite3.Connection) -> str:
    conn.execute("DROP TABLE IF EXISTS articles_fts")
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE articles_fts USING fts5("
            "article_id UNINDEXED, title, text, tokenize='trigram')"
        )
        return "trigram"
    except sqlite3.OperationalError:
        conn.execute(
            "CREATE VIRTUAL TABLE articles_fts USING fts5("
            "article_id UNINDEXED, title, text, tokenize='unicode61')"
        )
        return "unicode61"


def _is_canonical(row: object) -> bool:
    value = getattr(row, "is_canonical", None)
    if value is not None:
        return bool(value)
    return not bool(getattr(row, "duplicate_of", None))


def build_search_index(articles_parquet: Path, db_path: Path) -> str:
    df = pd.read_parquet(articles_parquet)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS articles")
        conn.execute(
            "CREATE TABLE articles ("
            "article_id TEXT PRIMARY KEY, publish_date TEXT, title TEXT, relative_path TEXT, "
            "sha256 TEXT, source_url TEXT)"
        )
        tokenizer = _create_fts(conn)

        metadata_rows = []
        fts_rows = []
        for row in df.itertuples(index=False):
            if not _is_canonical(row):
                continue
            metadata_rows.append(
                (
                    row.article_id,
                    getattr(row, "publish_date", None),
                    row.title,
                    row.relative_path,
                    row.sha256,
                    getattr(row, "source_url", None),
                )
            )
            fts_rows.append((row.article_id, row.title, row.text or ""))

        conn.executemany(
            "INSERT INTO articles(article_id, publish_date, title, relative_path, sha256, source_url) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            metadata_rows,
        )
        conn.executemany(
            "INSERT INTO articles_fts(article_id, title, text) VALUES (?, ?, ?)",
            fts_rows,
        )
        conn.commit()

    return tokenizer


def search_index(db_path: Path, query: str, limit: int = 20) -> list[dict[str, str | float | None]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        sql = """
        SELECT a.article_id,
               a.publish_date,
               a.title,
               a.relative_path,
               a.source_url,
               bm25(articles_fts) AS rank,
               snippet(articles_fts, 2, '[', ']', ' … ', 32) AS snippet
        FROM articles_fts
        JOIN articles a USING(article_id)
        WHERE articles_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """
        rows = conn.execute(sql, (query, limit)).fetchall()
        return [dict(row) for row in rows]
