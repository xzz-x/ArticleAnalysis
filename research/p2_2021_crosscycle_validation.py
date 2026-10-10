from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import REPO

TARGET = REPO / "data" / "verified" / "star_target_2021_crosscycle_sample.csv"
PRICE = REPO / "data" / "derived" / "csi_all_share_2021_prices.csv"
OUTPUT = REPO / "data" / "derived" / "p2_2021_crosscycle_validation.csv"
SUMMARY = REPO / "data" / "derived" / "p2_2021_crosscycle_validation_summary.json"

STATIC_INTERCEPT = 39.95198926812065
STATIC_SLOPE = -4.127707783337646


def interval_error(pred: np.ndarray, low: np.ndarray, high: np.ndarray) -> np.ndarray:
    return np.where(pred < low, low - pred, np.where(pred > high, pred - high, 0.0))


def main() -> None:
    target = pd.read_csv(TARGET)
    price = pd.read_csv(PRICE)
    target["date"] = pd.to_datetime(target["date"])
    price["date"] = pd.to_datetime(price["date"])

    frame = target.merge(price[["date", "cp"]], on="date", how="left", validate="one_to_one")
    if frame["cp"].isna().any():
        missing = frame.loc[frame["cp"].isna(), "date"].dt.strftime("%Y-%m-%d").tolist()
        raise RuntimeError(f"missing 2021 CSI All Share prices for {missing}")

    frame["log_close"] = np.log(frame["cp"].astype(float))
    frame["static_latent"] = STATIC_INTERCEPT + STATIC_SLOPE * frame["log_close"]
    frame["static_round_0_5"] = np.round(frame["static_latent"] / 0.5) * 0.5
    frame["static_round_0_1"] = np.round(frame["static_latent"] / 0.1) * 0.1

    low = frame["star_low"].to_numpy(dtype=float)
    high = frame["star_high"].to_numpy(dtype=float)
    latent = frame["static_latent"].to_numpy(dtype=float)
    rounded_05 = frame["static_round_0_5"].to_numpy(dtype=float)

    frame["latent_interval_error"] = interval_error(latent, low, high)
    frame["round_0_5_interval_error"] = interval_error(rounded_05, low, high)

    exact = frame["status"].eq("exact").to_numpy()
    exact_target = frame.loc[exact, "target_mid"].to_numpy(dtype=float)
    exact_round_05 = frame.loc[exact, "static_round_0_5"].to_numpy(dtype=float)
    exact_latent = frame.loc[exact, "static_latent"].to_numpy(dtype=float)

    summary = {
        "purpose": (
            "Backward cross-cycle check only. Uses the 2022-2024-fitted static price formula "
            "without refitting on 2021."
        ),
        "n": int(len(frame)),
        "exactN": int(exact.sum()),
        "rangeN": int((~exact).sum()),
        "staticIntercept": STATIC_INTERCEPT,
        "staticSlope": STATIC_SLOPE,
        "latentIntervalMae": float(frame["latent_interval_error"].mean()),
        "round0_5IntervalMae": float(frame["round_0_5_interval_error"].mean()),
        "exactLatentMae": float(np.abs(exact_latent - exact_target).mean()),
        "exactRound0_5Mae": float(np.abs(exact_round_05 - exact_target).mean()),
        "exactRound0_5MatchRate": float(np.isclose(exact_round_05, exact_target, atol=1e-8).mean()),
        "exactRound0_5Within0_5": float((np.abs(exact_round_05 - exact_target) <= 0.5000001).mean()),
        "maxRound0_5Error": float(np.abs(exact_round_05 - exact_target).max()),
        "regimeCounts": {
            str(k): int(v)
            for k, v in frame.loc[exact, "target_mid"].value_counts().sort_index().items()
        },
        "notATrainingOrSelectionSet": True,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
