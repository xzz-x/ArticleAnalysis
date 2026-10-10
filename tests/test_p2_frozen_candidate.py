from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "research" / "p2_frozen_candidate.json"
FUTURE_TARGET = REPO / "data" / "verified" / "star_target_prospective_2026_09_onward.csv"
FUTURE_PRICE = REPO / "data" / "verified" / "csi_all_share_prospective_2026_08_31_2026_10_09.csv"


def load_spec() -> dict:
    return json.loads(SPEC.read_text(encoding="utf-8"))


def test_p2_candidate_parameters_are_frozen() -> None:
    spec = load_spec()

    assert spec["version"] == "p2-candidate-2026-10-10"
    assert spec["status"] == "frozen_for_prospective_validation"
    assert spec["target_cutoff"] == "2026-08-31"
    assert spec["prospective_start"] == "2026-09-01"

    assert spec["price_proxy"]["name"] == "A股全指"
    assert spec["price_proxy"]["stockCode"] == "1000002"
    assert spec["latent_score"]["price_coefficient"] == -4.127707783337646
    assert spec["latent_score"]["refit_during_prospective_validation"] is False

    assert spec["adaptive_anchor"]["window_published_targets"] == 10
    assert spec["adaptive_anchor"]["method"] == "mean"
    assert spec["adaptive_anchor"]["retune_during_prospective_validation"] is False

    assert spec["publication_rule"]["threshold_star_up"] == 0.07
    assert spec["publication_rule"]["threshold_star_down"] == 0.06
    assert spec["publication_rule"]["retune_during_prospective_validation"] is False


def test_prospective_target_is_strictly_post_freeze() -> None:
    spec = load_spec()
    target = pd.read_csv(FUTURE_TARGET)
    dates = pd.to_datetime(target["date"])

    assert len(target) == 23
    assert target["status"].eq("exact").all()
    assert dates.min() >= pd.Timestamp(spec["prospective_start"])
    assert dates.max() == pd.Timestamp("2026-10-09")
    assert not dates.duplicated().any()


def test_verified_prospective_price_snapshot_matches_frozen_proxy() -> None:
    spec = load_spec()
    price = pd.read_csv(FUTURE_PRICE)
    target = pd.read_csv(FUTURE_TARGET)
    price["date"] = pd.to_datetime(price["date"])
    target["date"] = pd.to_datetime(target["date"])

    anchor = price.loc[price["date"].eq(pd.Timestamp(spec["target_cutoff"]))]
    assert len(anchor) == 1
    assert float(anchor.iloc[0]["cp"]) == 5969.33
    assert anchor.iloc[0]["source_code"] == "000985.SH"

    future_price_dates = set(price.loc[price["date"] >= pd.Timestamp(spec["prospective_start"]), "date"])
    assert set(target["date"]).issubset(future_price_dates)
