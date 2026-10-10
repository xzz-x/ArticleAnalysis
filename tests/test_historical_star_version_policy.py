from __future__ import annotations

from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[1]
ANCHORS = REPO / "data" / "verified" / "star_historical_version_anchors.csv"


def test_historical_version_anchors_are_nontraining_evidence() -> None:
    frame = pd.read_csv(ANCHORS)
    assert not frame.empty
    assert frame["training_allowed"].astype(str).str.lower().eq("false").all()
    assert frame["publication_version"].notna().all()
    assert frame["source_type"].notna().all()


def test_version_anchor_regimes_cover_known_precision_transition() -> None:
    frame = pd.read_csv(ANCHORS).set_index("date")

    assert frame.loc["2018-12-19", "publication_version"] == "legacy_empirical_coarse"
    assert frame.loc["2021-04-01", "publication_version"] == "legacy_half_star"
    assert frame.loc["2022-04-07", "publication_version"] == "transition_coarse_plus_fine"
    assert float(frame.loc["2022-04-07", "contemporaneous_display_star"]) == 4.5
    assert float(frame.loc["2022-04-07", "contemporaneous_fine_star"]) == 4.8
    assert frame.loc["2022-05-31", "publication_version"] == "modern_0_1_transition"
