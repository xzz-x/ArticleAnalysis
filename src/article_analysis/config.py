from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Settings:
    timezone: str
    corpus_root: Path
    workspace_root: Path
    articles_parquet: Path
    corpus_manifest: Path
    search_db: Path
    star_candidates: Path
    include_extensions: tuple[str, ...]
    context_chars: int
    min_star: float
    max_star: float


def _resolve_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def load_settings(config_path: str | Path = "config.example.yaml") -> Settings:
    config_path = Path(config_path)
    raw: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    corpus_cfg = raw.get("corpus", {})
    workspace_cfg = raw.get("workspace", {})
    star_cfg = raw.get("star_extraction", {})

    root_env = corpus_cfg.get("root_env", "ARTICLE_ANALYSIS_CORPUS_ROOT")
    corpus_root_value = os.getenv(root_env, "").strip()
    if not corpus_root_value:
        raise RuntimeError(
            f"Missing corpus path. Set environment variable {root_env} to the local Google Drive corpus root."
        )

    workspace_root = Path(workspace_cfg.get("root", ".local/screw_star")).expanduser()
    workspace_root.mkdir(parents=True, exist_ok=True)

    return Settings(
        timezone=str(raw.get("timezone", "Asia/Shanghai")),
        corpus_root=Path(corpus_root_value).expanduser().resolve(),
        workspace_root=workspace_root.resolve(),
        articles_parquet=_resolve_path(workspace_root, workspace_cfg.get("articles_parquet", "articles.parquet")),
        corpus_manifest=_resolve_path(workspace_root, workspace_cfg.get("corpus_manifest", "corpus_manifest.parquet")),
        search_db=_resolve_path(workspace_root, workspace_cfg.get("search_db", "corpus.sqlite3")),
        star_candidates=_resolve_path(workspace_root, workspace_cfg.get("star_candidates", "star_candidates.csv")),
        include_extensions=tuple(ext.lower() for ext in corpus_cfg.get("include_extensions", [".html", ".htm", ".txt", ".md", ".json"])),
        context_chars=int(star_cfg.get("context_chars", 140)),
        min_star=float(star_cfg.get("min_star", 1.0)),
        max_star=float(star_cfg.get("max_star", 6.0)),
    )
