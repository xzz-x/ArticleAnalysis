from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .config import load_settings
from .corpus import ingest_corpus
from .index import build_search_index, search_index
from .star_targets import (
    build_daily_target_review_queue,
    build_daily_realtime_targets,
    build_realtime_target_seed,
    extract_star_candidates,
)


def cmd_ingest(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    df = ingest_corpus(
        corpus_root=settings.corpus_root,
        articles_parquet=settings.articles_parquet,
        manifest_parquet=settings.corpus_manifest,
        include_extensions=settings.include_extensions,
    )
    duplicates = int(df["duplicate_of"].notna().sum()) if "duplicate_of" in df.columns else 0
    canonical = int(df["is_canonical"].sum()) if "is_canonical" in df.columns else int(len(df) - duplicates)
    print(
        json.dumps(
            {
                "files": int(len(df)),
                "canonical_articles": canonical,
                "exact_duplicates": duplicates,
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
                "realtime_candidates": int((df["relation"] == "realtime").sum()) if not df.empty else 0,
                "output": str(settings.star_candidates),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_build_target_seed(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    if not settings.star_candidates.exists():
        candidates = extract_star_candidates(
            settings.articles_parquet,
            settings.star_candidates,
            context_chars=settings.context_chars,
            min_star=settings.min_star,
            max_star=settings.max_star,
        )
    else:
        candidates = pd.read_csv(settings.star_candidates)

    seed = build_realtime_target_seed(candidates, settings.star_target_seed)
    print(
        json.dumps(
            {
                "seed_rows": int(len(seed)),
                "output": str(settings.star_target_seed),
                "warning": "seed_auto rows still require research review before becoming final Target",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def cmd_build_daily_target(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    target = build_daily_realtime_targets(
        settings.articles_parquet,
        settings.star_daily_target,
    )
    review = build_daily_target_review_queue(
        settings.articles_parquet,
        settings.star_daily_review_queue,
    )
    print(
        json.dumps(
            {
                "target_rows": int(len(target)),
                "first_date": target["date"].min() if not target.empty else None,
                "last_date": target["date"].max() if not target.empty else None,
                "output": str(settings.star_daily_target),
                "unresolved_rows": int(len(review)),
                "review_queue": str(settings.star_daily_review_queue),
                "review_status": "auto_high_confidence",
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

    stars = sub.add_parser("extract-stars", help="Extract and classify star-level candidate statements")
    stars.set_defaults(func=cmd_extract_stars)

    seed = sub.add_parser("build-target-seed", help="Build conservative realtime star Target seed")
    seed.set_defaults(func=cmd_build_target_seed)

    daily = sub.add_parser(
        "build-daily-target",
        help="Build one exact realtime A-share Target per article date",
    )
    daily.set_defaults(func=cmd_build_daily_target)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
