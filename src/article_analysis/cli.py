from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_settings
from .corpus import ingest_corpus
from .index import build_search_index, search_index
from .star_targets import extract_star_candidates


def cmd_ingest(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    df = ingest_corpus(
        corpus_root=settings.corpus_root,
        articles_parquet=settings.articles_parquet,
        manifest_parquet=settings.corpus_manifest,
        include_extensions=settings.include_extensions,
    )
    duplicates = int(df["duplicate_of"].notna().sum()) if "duplicate_of" in df.columns else 0
    print(
        json.dumps(
            {
                "articles": int(len(df)),
                "duplicates": duplicates,
                "articles_parquet": str(settings.articles_parquet),
                "manifest": str(settings.corpus_manifest),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_build_index(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    tokenizer = build_search_index(settings.articles_parquet, settings.search_db)
    print(json.dumps({"db": str(settings.search_db), "tokenizer": tokenizer}, ensure_ascii=False, indent=2))


def cmd_search(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    rows = search_index(settings.search_db, args.query, args.limit)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def cmd_extract_stars(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    df = extract_star_candidates(
        settings.articles_parquet,
        settings.star_candidates,
        context_chars=settings.context_chars,
        min_star=settings.min_star,
        max_star=settings.max_star,
    )
    print(
        json.dumps(
            {
                "candidates": int(len(df)),
                "output": str(settings.star_candidates),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ArticleAnalysis corpus research CLI")
    parser.add_argument("--config", default="config.example.yaml", help="YAML configuration path")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Parse local corpus into Parquet and manifest")
    ingest.set_defaults(func=cmd_ingest)

    build_index = sub.add_parser("build-index", help="Build local SQLite FTS index")
    build_index.set_defaults(func=cmd_build_index)

    search = sub.add_parser("search", help="Search the local corpus index")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    search.set_defaults(func=cmd_search)

    stars = sub.add_parser("extract-stars", help="Extract candidate star-level statements")
    stars.set_defaults(func=cmd_extract_stars)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
