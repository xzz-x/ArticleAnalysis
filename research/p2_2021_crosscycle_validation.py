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

    # Contemporaneous 2021 articles used coarse half-star states. Treat an
    # "exact" published 3.5/4.0 label as a coarse bucket [S, S+0.5), not as a
    # modern fine 0.1-star point. Explicit range rows retain their stated range.
    exact = frame["status"].eq("exact").to_numpy()
    coarse_low = np.where(exact, frame["target_mid"], frame["star_low"]).astype(float)
    coarse_high = np.where(exact, frame["target_mid"] + 0.5, frame["star_high"]).astype(float)
    latent = frame["static_latent"].to_numpy(dtype=float)

    frame["coarse_bucket_low"] = coarse_low
    frame["coarse_bucket_high"] = coarse_high
    frame["latent_coarse_bucket_error"] = interval_error(latent, coarse_low, coarse_high)

    # Post-hoc structural diagnostic only: quantify how much a single intercept
    # translation would be needed to align the 2022-2024 static slope with 2021.
    # This shift is not a fitted production model and must not be used for future
    # predictions.
    shift_grid = np.linspace(-1.5, 0.5, 4001)

    def best_shift(mask: np.ndarray) -> dict[str, float | int]:
        pred = latent[mask]
        low = coarse_low[mask]
        high = coarse_high[mask]
        rows: list[tuple[float, float, float]] = []
        for shift in shift_grid:
            error = interval_error(pred + shift, low, high)
            rows.append((float(error.mean()), float((error <= 1e-12).mean()), float(shift)))
        mae, inside, shift = min(rows, key=lambda row: (row[0], -row[1], abs(row[2])))
        return {
            "n": int(mask.sum()),
            "bestInterceptShift": shift,
            "bucketMaeAfterShift": mae,
            "insideBucketRateAfterShift": inside,
        }

    dates = frame["date"]
    jan_apr = (dates < pd.Timestamp("2021-05-01")).to_numpy()
    sep_nov = (dates >= pd.Timestamp("2021-09-01")).to_numpy()

    summary = {
        "purpose": (
            "Backward cross-cycle structural check only. Uses the 2022-2024-fitted static "
            "price slope/intercept without refitting; 2021 half-star publications are "
            "evaluated as coarse buckets."
        ),
        "n": int(len(frame)),
        "coarseExactPublicationN": int(exact.sum()),
        "explicitRangeN": int((~exact).sum()),
        "staticIntercept": STATIC_INTERCEPT,
        "staticSlope": STATIC_SLOPE,
        "staticLatentCoarseBucketMae": float(frame["latent_coarse_bucket_error"].mean()),
        "staticLatentInsideCoarseBucketRate": float(
            (frame["latent_coarse_bucket_error"] <= 1e-12).mean()
        ),
        "maxStaticCoarseBucketError": float(frame["latent_coarse_bucket_error"].max()),
        "posthocUniformShiftDiagnostic": best_shift(np.ones(len(frame), dtype=bool)),
        "posthocSubperiodShiftDiagnostic": {
            "2021_Jan_Apr": best_shift(jan_apr),
            "2021_Sep_Nov": best_shift(sep_nov),
        },
        "regimeCounts": {
            str(k): int(v)
            for k, v in frame.loc[exact, "target_mid"].value_counts().sort_index().items()
        },
        "notATrainingOrSelectionSet": True,
        "warning": (
            "The post-hoc intercept shifts quantify structural anchor displacement only; "
            "they are not eligible model parameters."
        ),
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
