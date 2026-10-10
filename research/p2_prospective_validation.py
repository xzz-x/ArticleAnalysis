from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import REPO

DEFAULT_SPEC = REPO / "research" / "p2_frozen_candidate.json"
DEFAULT_PANEL = REPO / "data" / "features" / "star_model_panel_2022_2026.csv"
DEFAULT_TARGET = REPO / "data" / "derived" / "star_target_2022_2026_unified.csv"
DEFAULT_OUTPUT = REPO / "data" / "derived" / "p2_prospective_validation.csv"
DEFAULT_SUMMARY = REPO / "data" / "derived" / "p2_prospective_validation_summary.json"
DEFAULT_PROSPECTIVE_TARGET = REPO / "data" / "verified" / "star_target_prospective_2026_09_onward.csv"
DEFAULT_PROSPECTIVE_PRICE = REPO / "data" / "derived" / "csi_all_share_prospective_prices.csv"


def load_spec(path: Path) -> dict:
    spec=json.loads(path.read_text(encoding="utf-8"))
    if spec.get("status")!="frozen_for_prospective_validation":
        raise ValueError("candidate spec is not frozen")
    return spec


def prepare(panel_path: Path,target_path: Path,stock_code: str)->pd.DataFrame:
    panel=pd.read_csv(panel_path,low_memory=False)
    panel["stockCode"]=panel["stockCode"].astype(str).str.replace(r"\.0$","",regex=True).str.zfill(6)
    panel["date"]=pd.to_datetime(panel["date"]).dt.normalize()
    panel=panel[panel["stockCode"]==str(stock_code).zfill(6)].copy()
    panel["log_close"]=np.log(pd.to_numeric(panel["cp"],errors="coerce").where(lambda s:s>0))

    target=pd.read_csv(target_path)
    target["date"]=pd.to_datetime(target["date"]).dt.normalize()
    keep=["date","star","star_low","star_high","target_mid","status","training_weight"]
    panel=panel.drop(columns=[c for c in panel.columns if c.startswith("target_")],errors="ignore")
    panel=panel.merge(
        target[keep].rename(columns={c:f"target_{c}" for c in keep if c!="date"}),
        on="date",how="left",validate="one_to_one"
    )
    return panel.sort_values("date").reset_index(drop=True)


def append_prospective(
    frame: pd.DataFrame,
    price_path: Path | None,
    target_path: Path | None,
    stock_code: str,
) -> pd.DataFrame:
    if price_path is None or target_path is None:
        return frame
    if not price_path.exists() or not target_path.exists():
        return frame

    price = pd.read_csv(price_path)
    target = pd.read_csv(target_path)
    price["date"] = pd.to_datetime(price["date"]).dt.normalize()
    target["date"] = pd.to_datetime(target["date"]).dt.normalize()

    future = price.merge(target[["date", "star", "status"]], on="date", how="inner", validate="one_to_one")
    if future.empty:
        return frame

    future["stockCode"] = str(stock_code).zfill(6)
    future["log_close"] = np.log(pd.to_numeric(future["cp"], errors="coerce").where(lambda s: s > 0))
    future["target_star"] = pd.to_numeric(future["star"], errors="coerce")
    future["target_star_low"] = future["target_star"]
    future["target_star_high"] = future["target_star"]
    future["target_target_mid"] = future["target_star"]
    future["target_status"] = future["status"].astype(str)
    future["target_training_weight"] = np.where(future["target_status"].eq("exact"), 1.0, 0.0)

    keep = [
        "date", "stockCode", "cp", "log_close",
        "target_star", "target_star_low", "target_star_high",
        "target_target_mid", "target_status", "target_training_weight",
    ]
    combined = pd.concat([frame, future[keep]], ignore_index=True, sort=False)
    combined = combined.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return combined.reset_index(drop=True)


def observed_star(row: pd.Series)->float|None:
    if row.get("target_status")=="exact" and pd.notna(row.get("target_target_mid")):
        return float(row["target_target_mid"])
    return None


def seed_history(frame: pd.DataFrame,cutoff: pd.Timestamp,slope: float,window: int)->tuple[list[float],float]:
    past=frame[frame["date"]<=cutoff].copy()
    past=past[
        past["target_status"].eq("exact")
        & pd.to_numeric(past["target_target_mid"],errors="coerce").notna()
        & pd.to_numeric(past["log_close"],errors="coerce").notna()
    ].sort_values("date")
    if len(past)<window:
        raise ValueError(f"need at least {window} exact historical targets to seed candidate")
    history=(
        pd.to_numeric(past["target_target_mid"],errors="coerce")
        - slope*pd.to_numeric(past["log_close"],errors="coerce")
    ).tail(window).astype(float).tolist()
    return history,float(past.iloc[-1]["target_target_mid"])


def predict(frame: pd.DataFrame,spec: dict)->pd.DataFrame:
    cutoff=pd.Timestamp(spec["target_cutoff"])
    start=pd.Timestamp(spec["prospective_start"])
    slope=float(spec["latent_score"]["price_coefficient"])
    window=int(spec["adaptive_anchor"]["window_published_targets"])
    method=str(spec["adaptive_anchor"]["method"])
    up=float(spec["publication_rule"]["threshold_star_up"])
    down=float(spec["publication_rule"]["threshold_star_down"])

    if method!="mean":
        raise ValueError("frozen evaluator currently supports the frozen mean anchor only")

    anchors,state=seed_history(frame,cutoff,slope,window)
    future=frame[frame["date"]>=start].copy().sort_values("date")
    rows=[]
    for _,row in future.iterrows():
        if not np.isfinite(row["log_close"]):
            continue
        anchor=float(np.mean(anchors[-window:]))
        latent=anchor+slope*float(row["log_close"])
        delta=latent-state
        prediction=state
        if delta>=up or delta<=-down:
            prediction=float(np.round(latent/0.1)*0.1)

        actual=observed_star(row)
        rows.append({
            "date":row["date"].strftime("%Y-%m-%d"),
            "cp":float(row["cp"]),
            "anchor_before_prediction":anchor,
            "latent_star":latent,
            "previous_published_state":state,
            "prediction":prediction,
            "actual_exact_star":actual,
            "absolute_error":abs(prediction-actual) if actual is not None else np.nan,
        })

        # Strict one-step information flow: only after the prediction may today's
        # observed published star update tomorrow's state and anchor history.
        if actual is not None:
            state=actual
            anchors.append(actual-slope*float(row["log_close"]))

    return pd.DataFrame(rows)


def main()->None:
    parser=argparse.ArgumentParser(description="Evaluate the frozen P2 candidate on genuinely unseen future dates")
    parser.add_argument("--spec",type=Path,default=DEFAULT_SPEC)
    parser.add_argument("--panel",type=Path,default=DEFAULT_PANEL)
    parser.add_argument("--target",type=Path,default=DEFAULT_TARGET)
    parser.add_argument("--output",type=Path,default=DEFAULT_OUTPUT)
    parser.add_argument("--summary",type=Path,default=DEFAULT_SUMMARY)
    parser.add_argument("--prospective-target",type=Path,default=DEFAULT_PROSPECTIVE_TARGET)
    parser.add_argument("--prospective-price",type=Path,default=DEFAULT_PROSPECTIVE_PRICE)
    args=parser.parse_args()

    spec=load_spec(args.spec)
    frame=prepare(args.panel,args.target,spec["price_proxy"]["stockCode"])
    frame=append_prospective(
        frame,
        args.prospective_price,
        args.prospective_target,
        spec["price_proxy"]["stockCode"],
    )
    result=predict(frame,spec)

    observed=result["actual_exact_star"].notna() if not result.empty else pd.Series(dtype=bool)
    summary={
        "candidateVersion":spec["version"],
        "targetCutoff":spec["target_cutoff"],
        "prospectiveStart":spec["prospective_start"],
        "prospectiveRows":int(len(result)),
        "observedExactRows":int(observed.sum()) if len(result) else 0,
        "exactMae":(
            float(result.loc[observed,"absolute_error"].mean())
            if len(result) and observed.any() else None
        ),
        "status":(
            "evaluated"
            if len(result) and observed.any()
            else "awaiting_genuinely_unseen_price_and_target_data"
        ),
        "parametersFrozen":True,
    }

    args.output.parent.mkdir(parents=True,exist_ok=True)
    result.to_csv(args.output,index=False,encoding="utf-8-sig")
    args.summary.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
