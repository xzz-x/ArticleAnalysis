from __future__ import annotations

import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED

SERIES = DERIVED / "p2_implied_anchor_series.csv"
SEGMENTS_OUTPUT = DERIVED / "p2_anchor_change_point_segments.csv"
SUMMARY_OUTPUT = DERIVED / "p2_anchor_change_point_summary.json"

START = pd.Timestamp("2025-01-01")
END = pd.Timestamp("2026-08-31")
MIN_SEGMENT = 20
MAX_SEGMENTS = 8


def segment_sse(prefix: np.ndarray, prefix2: np.ndarray, i: int, j: int) -> float:
    n = j - i
    total = prefix[j] - prefix[i]
    total2 = prefix2[j] - prefix2[i]
    return float(total2 - total * total / n)


def dynamic_programming(y: np.ndarray) -> tuple[pd.DataFrame, int, list[int]]:
    n = len(y)
    prefix = np.concatenate([[0.0], np.cumsum(y)])
    prefix2 = np.concatenate([[0.0], np.cumsum(y * y)])

    inf = float("inf")
    dp = np.full((MAX_SEGMENTS + 1, n + 1), inf)
    prev = np.full((MAX_SEGMENTS + 1, n + 1), -1, dtype=int)
    dp[0, 0] = 0.0

    for k in range(1, MAX_SEGMENTS + 1):
        for j in range(k * MIN_SEGMENT, n + 1):
            lo = (k - 1) * MIN_SEGMENT
            hi = j - MIN_SEGMENT
            for i in range(lo, hi + 1):
                value = dp[k - 1, i] + segment_sse(prefix, prefix2, i, j)
                if value < dp[k, j]:
                    dp[k, j] = value
                    prev[k, j] = i

    candidates = []
    for k in range(1, MAX_SEGMENTS + 1):
        rss = float(dp[k, n])
        if not np.isfinite(rss) or rss <= 0:
            continue
        # k segment means + (k-1) break locations.
        parameter_count = 2 * k - 1
        bic = float(n * np.log(rss / n) + parameter_count * np.log(n))
        candidates.append({
            "segments": k,
            "rss": rss,
            "bic": bic,
            "parameterCount": parameter_count,
        })

    table = pd.DataFrame(candidates).sort_values("segments").reset_index(drop=True)
    selected = int(table.loc[table["bic"].idxmin(), "segments"])

    bounds = [n]
    k = selected
    j = n
    while k > 0:
        i = int(prev[k, j])
        if i < 0:
            raise RuntimeError("failed to reconstruct selected segmentation")
        bounds.append(i)
        j = i
        k -= 1
    bounds = sorted(bounds)
    return table, selected, bounds


def main() -> None:
    frame = pd.read_csv(SERIES)
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    use = frame[
        frame["date"].between(START, END)
        & pd.to_numeric(frame["anchor_deviation"], errors="coerce").notna()
    ].copy().sort_values("date").reset_index(drop=True)

    y = pd.to_numeric(use["anchor_deviation"], errors="coerce").to_numpy(dtype=float)
    candidates, selected, bounds = dynamic_programming(y)

    segment_rows = []
    for segment_number, (start, stop) in enumerate(zip(bounds[:-1], bounds[1:]), start=1):
        group = use.iloc[start:stop].copy()
        values = group["anchor_deviation"].to_numpy(dtype=float)
        segment_rows.append({
            "segment": segment_number,
            "start": group["date"].iloc[0].strftime("%Y-%m-%d"),
            "end": group["date"].iloc[-1].strftime("%Y-%m-%d"),
            "n": int(len(group)),
            "meanAnchorDeviation": float(np.mean(values)),
            "medianAnchorDeviation": float(np.median(values)),
            "sdAnchorDeviation": float(np.std(values, ddof=1)),
            "meanStaticRoundError": float(group["static_round_error"].mean()),
        })

    segments = pd.DataFrame(segment_rows)
    breaks = [row["start"] for row in segment_rows[1:]]

    summary = {
        "purpose": (
            "Post-hoc description of whether the 2025-to-freeze implied-anchor drift "
            "looks smooth or piecewise constant. This analysis is not a prediction model."
        ),
        "window": {"start": START.strftime("%Y-%m-%d"), "end": END.strftime("%Y-%m-%d")},
        "observations": int(len(use)),
        "minimumSegmentObservations": MIN_SEGMENT,
        "candidateSegmentCounts": candidates.to_dict(orient="records"),
        "selectedSegmentsByBIC": selected,
        "selectedBreakStarts": breaks,
        "segments": segment_rows,
        "interpretation": (
            "Persistent piecewise levels support regime-like anchor behavior. They do not "
            "prove manual recalibration: publication granularity, omitted market-wide inputs, "
            "or source/proxy changes can produce similar statistical breaks."
        ),
        "cleanPredictionRule": (
            "No breakpoint or segment mean from this post-hoc diagnostic may be used to "
            "retune the frozen prospective models."
        ),
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    segments.to_csv(SEGMENTS_OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
