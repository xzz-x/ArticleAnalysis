from __future__ import annotations

from pathlib import Path

import pandas as pd


FINAL_COLUMNS = [
    "date",
    "star",
    "article_id",
    "title",
    "source_url",
    "confidence",
    "context",
    "review_status",
]


def merge_manual_seed_with_auto(
    auto_seed: Path,
    manual_seed: Path,
    output: Path,
) -> pd.DataFrame:
    """Merge automatic extraction with manually verified Target rows.

    Manual rows always override automatic rows for the same date.
    The output is intended as a review-stage dataset, not the final model target.
    """
    auto = pd.read_csv(auto_seed) if auto_seed.exists() else pd.DataFrame(columns=FINAL_COLUMNS)
    manual = pd.read_csv(manual_seed) if manual_seed.exists() else pd.DataFrame(columns=FINAL_COLUMNS)

    auto = auto.copy()
    manual = manual.copy()

    auto["review_status"] = auto.get("review_status", "seed_auto")
    manual["review_status"] = "verified_manual"

    combined = pd.concat([auto, manual], ignore_index=True)
    if not combined.empty:
        combined["date"] = combined["date"].astype(str)
        combined["priority"] = combined["review_status"].map(
            {"verified_manual": 2, "seed_auto": 1}
        ).fillna(0)
        combined = (
            combined.sort_values(["date", "priority", "confidence"], ascending=[True, False, False])
            .drop_duplicates("date", keep="first")
            .drop(columns="priority")
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output, index=False, encoding="utf-8-sig")
    return combined


def build_review_queue(candidates: Path, output: Path) -> pd.DataFrame:
    """Create a human-review queue from ambiguous star candidates."""
    df = pd.read_csv(candidates)
    if df.empty:
        queue = df
    else:
        queue = df[
            (df["relation"].isin(["generic", "historical", "range_or_rule"]))
            | (df["confidence"] < 0.9)
        ].copy()
        queue = queue.sort_values(
            ["confidence", "publish_date"], ascending=[True, True]
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    queue.to_csv(output, index=False, encoding="utf-8-sig")
    return queue
