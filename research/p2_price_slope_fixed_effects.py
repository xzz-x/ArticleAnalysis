from __future__ import annotations

import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, prepare_panel

PROSPECTIVE_TARGET = DERIVED.parent / "verified" / "star_target_prospective_2026_09_onward.csv"
PROSPECTIVE_PRICE = DERIVED.parent / "verified" / "csi_all_share_prospective_2026_08_31_2026_10_09.csv"

MONTHLY_OUTPUT = DERIVED / "p2_month_fixed_effect_anchor.csv"
SUMMARY_OUTPUT = DERIVED / "p2_price_slope_fixed_effect_summary.json"


def fine_exact(frame: pd.DataFrame) -> pd.DataFrame:
    use = frame[
        frame["target_status"].eq("exact")
        & pd.to_numeric(frame["target_target_mid"], errors="coerce").notna()
        & pd.to_numeric(frame["log_close"], errors="coerce").notna()
        & (pd.to_datetime(frame["date"]) >= pd.Timestamp("2022-05-31"))
    ].copy()
    use["star"] = pd.to_numeric(use["target_target_mid"], errors="coerce")
    use["weight"] = pd.to_numeric(use["target_training_weight"], errors="coerce").fillna(1.0)
    use["month"] = pd.to_datetime(use["date"]).dt.to_period("M").astype(str)
    use["year"] = pd.to_datetime(use["date"]).dt.year
    return use.sort_values("date")


def fe_slope(frame: pd.DataFrame, group_col: str = "month") -> dict[str, float | int]:
    use = frame.dropna(subset=["star", "log_close", group_col]).copy()
    pieces = []
    for _, g in use.groupby(group_col):
        if len(g) < 2:
            continue
        w = g["weight"].to_numpy(dtype=float)
        x = g["log_close"].to_numpy(dtype=float)
        y = g["star"].to_numpy(dtype=float)
        xbar = float(np.average(x, weights=w))
        ybar = float(np.average(y, weights=w))
        pieces.append((x - xbar, y - ybar, w))
    if not pieces:
        return {"n": 0, "groups": 0, "slope": float("nan")}
    dx = np.concatenate([p[0] for p in pieces])
    dy = np.concatenate([p[1] for p in pieces])
    w = np.concatenate([p[2] for p in pieces])
    denom = float(np.sum(w * dx * dx))
    slope = float(np.sum(w * dx * dy) / denom) if denom > 0 else float("nan")
    return {
        "n": int(len(dx)),
        "groups": int(len(pieces)),
        "slope": slope,
    }


def monthly_anchors(frame: pd.DataFrame, slope: float) -> pd.DataFrame:
    rows = []
    for month, g in frame.groupby("month"):
        w = g["weight"].to_numpy(dtype=float)
        x = g["log_close"].to_numpy(dtype=float)
        y = g["star"].to_numpy(dtype=float)
        implied = y - slope * x
        rows.append(
            {
                "month": month,
                "start": pd.to_datetime(g["date"]).min().strftime("%Y-%m-%d"),
                "end": pd.to_datetime(g["date"]).max().strftime("%Y-%m-%d"),
                "n": int(len(g)),
                "anchor": float(np.average(implied, weights=w)),
                "anchor_sd": float(np.sqrt(np.average((implied - np.average(implied, weights=w)) ** 2, weights=w))),
                "mean_star": float(np.average(y, weights=w)),
                "mean_close": float(np.average(pd.to_numeric(g["cp"], errors="coerce"), weights=w)),
            }
        )
    out = pd.DataFrame(rows).sort_values("month").reset_index(drop=True)
    out["anchor_change"] = out["anchor"].diff()
    return out


def build_prospective() -> pd.DataFrame:
    price = pd.read_csv(PROSPECTIVE_PRICE)
    target = pd.read_csv(PROSPECTIVE_TARGET)
    price["date"] = pd.to_datetime(price["date"]).dt.normalize()
    target["date"] = pd.to_datetime(target["date"]).dt.normalize()
    out = price.merge(target[["date", "star", "status"]], on="date", how="inner", validate="one_to_one")
    out["log_close"] = np.log(pd.to_numeric(out["cp"], errors="coerce"))
    out["target_target_mid"] = pd.to_numeric(out["star"], errors="coerce")
    out["target_status"] = out["status"]
    out["target_training_weight"] = 1.0
    return out.sort_values("date")


def main() -> None:
    panel = prepare_panel()
    precise = fine_exact(panel)

    pre = precise[precise["year"] <= 2024].copy()
    observed = precise[precise["year"] >= 2025].copy()
    prospective = fine_exact(build_prospective())

    pre_full = fe_slope(pre)
    by_year = {}
    for year, group in precise.groupby("year"):
        by_year[str(int(year))] = fe_slope(group)

    # Estimate the mechanism slope only from 2022-06..2024 monthly within-group
    # variation, then inspect the month-specific intercept/anchor sequence.
    slope = float(pre_full["slope"])
    month_anchor = monthly_anchors(precise, slope)
    month_anchor.to_csv(MONTHLY_OUTPUT, index=False, encoding="utf-8-sig")

    future_fe = fe_slope(prospective) if len(prospective) else {"n": 0, "groups": 0, "slope": None}

    anchors_pre = month_anchor[month_anchor["month"] <= "2024-12"]
    anchors_obs = month_anchor[(month_anchor["month"] >= "2025-01") & (month_anchor["month"] <= "2026-08")]

    def anchor_block(frame: pd.DataFrame) -> dict[str, float | int | None]:
        a = frame["anchor"].to_numpy(dtype=float)
        changes = frame["anchor_change"].dropna().to_numpy(dtype=float)
        return {
            "months": int(len(frame)),
            "anchorMean": float(np.mean(a)) if len(a) else None,
            "anchorSdAcrossMonths": float(np.std(a, ddof=1)) if len(a) > 1 else None,
            "meanAbsoluteMonthlyChange": float(np.mean(np.abs(changes))) if len(changes) else None,
            "maxAbsoluteMonthlyChange": float(np.max(np.abs(changes))) if len(changes) else None,
        }

    summary = {
        "method": (
            "Weighted within-month fixed-effects regression on fine 0.1-star exact labels "
            "from 2022-05-31 onward. Month-specific intercepts absorb slow anchor variation; "
            "the slope is identified only from within-month price/star co-movement."
        ),
        "preHoldoutSlope2022_06_to_2024": pre_full,
        "slopeByYearDescriptive": by_year,
        "observed2025_2026SlopeDescriptive": fe_slope(observed),
        "firstProspectiveSlopePostHocDiagnostic": future_fe,
        "monthlyAnchorUsingPreHoldoutSlope": {
            "preHoldout": anchor_block(anchors_pre),
            "observed2025_toFreeze": anchor_block(anchors_obs),
        },
        "comparisonToOriginalStaticSlope": {
            "originalSlope": -4.127707783337646,
            "fixedEffectSlope": slope,
            "difference": float(slope - (-4.127707783337646)),
        },
    }
    SUMMARY_OUTPUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
