from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, fit_linear, interval_error, prepare_panel

GRID_OUTPUT = DERIVED / "p2_online_anchor_grid.csv"
HOLDOUT_OUTPUT = DERIVED / "p2_online_anchor_holdout.csv"
SUMMARY_OUTPUT = DERIVED / "p2_online_anchor_summary.json"


def score(frame: pd.DataFrame, prediction: np.ndarray) -> dict[str, float | int]:
    pred = np.asarray(prediction, dtype=float)
    low = pd.to_numeric(frame["target_star_low"], errors="coerce").to_numpy(dtype=float)
    high = pd.to_numeric(frame["target_star_high"], errors="coerce").to_numpy(dtype=float)
    mid = pd.to_numeric(frame["target_target_mid"], errors="coerce").to_numpy(dtype=float)
    status = frame["target_status"].astype(str).to_numpy()
    trainable = np.isfinite(pred) & np.isfinite(low) & np.isfinite(high)
    exact = np.isfinite(pred) & (status == "exact") & np.isfinite(mid)
    interval_errors = interval_error(pred[trainable], low[trainable], high[trainable])
    exact_errors = np.abs(pred[exact] - mid[exact])
    return {
        "n": int(len(frame)),
        "exact_n": int(exact.sum()),
        "interval_mae": float(interval_errors.mean()) if len(interval_errors) else float("nan"),
        "exact_mae": float(exact_errors.mean()) if len(exact_errors) else float("nan"),
        "exact_within_0_1": float((exact_errors <= 0.1000001).mean()) if len(exact_errors) else float("nan"),
    }


def anchor_stat(values: list[float], method: str) -> float:
    if not values:
        raise ValueError("no historical anchors available")
    arr=np.asarray(values,dtype=float)
    if method=="mean":
        return float(np.mean(arr))
    if method=="median":
        return float(np.median(arr))
    raise ValueError(method)


def online_anchor_predict(
    train: pd.DataFrame,
    test: pd.DataFrame,
    window: int,
    method: str,
) -> tuple[np.ndarray, float]:
    fit=fit_linear(train,["log_close"])
    slope=float(fit[1][0])
    if slope>=0:
        raise ValueError("price coefficient must remain negative")

    history=train.sort_values("date").dropna(subset=["target_target_mid","log_close"]).copy()
    history=history[pd.to_numeric(history["target_training_weight"],errors="coerce")>0]
    anchors=(
        pd.to_numeric(history["target_target_mid"],errors="coerce")
        - slope*pd.to_numeric(history["log_close"],errors="coerce")
    ).dropna().astype(float).tolist()

    predictions=[]
    for row in test.sort_values("date").itertuples(index=False):
        recent=anchors[-window:] if window>0 else anchors
        intercept=anchor_stat(recent,method)
        log_close=float(row.log_close)
        predictions.append(intercept+slope*log_close)

        weight=float(row.target_training_weight) if pd.notna(row.target_training_weight) else 0.0
        mid=float(row.target_target_mid) if pd.notna(row.target_target_mid) else np.nan
        if weight>0 and np.isfinite(mid) and np.isfinite(log_close):
            anchors.append(mid-slope*log_close)

    return np.asarray(predictions,dtype=float),slope


def preholdout_grid(panel: pd.DataFrame) -> pd.DataFrame:
    folds=((2022,2023),(2023,2024))
    specs=[(w,m) for w in (10,20,40,60,120,252,504) for m in ("mean","median")]
    rows=[]
    for window,method in specs:
        fold_scores=[]
        for train_end,test_year in folds:
            train=panel[panel["year"]<=train_end].copy()
            test=panel[panel["year"]==test_year].copy().sort_values("date")
            pred,_=online_anchor_predict(train,test,window,method)
            fold_scores.append(score(test,pred))
        rows.append({
            "window":window,
            "method":method,
            "cv_exact_mae":float(np.mean([x["exact_mae"] for x in fold_scores])),
            "cv_interval_mae":float(np.mean([x["interval_mae"] for x in fold_scores])),
            "cv_exact_within_0_1":float(np.mean([x["exact_within_0_1"] for x in fold_scores])),
        })
    return pd.DataFrame(rows).sort_values(["cv_exact_mae","cv_interval_mae"],ignore_index=True)


def static_prediction(train: pd.DataFrame,test: pd.DataFrame)->np.ndarray:
    fit=fit_linear(train,["log_close"])
    return float(fit[0])+pd.to_numeric(test["log_close"],errors="coerce").to_numpy(dtype=float)*float(fit[1][0])


def main()->None:
    panel=prepare_panel()
    grid=preholdout_grid(panel)
    best=grid.iloc[0]

    train=panel[panel["year"]<=2024].copy()
    holdout=panel[panel["year"]>=2025].copy().sort_values("date")
    static_pred=static_prediction(train,holdout)
    online_pred,slope=online_anchor_predict(
        train,holdout,int(best["window"]),str(best["method"])
    )

    static_metrics=score(holdout,static_pred)
    online_metrics=score(holdout,online_pred)

    out=holdout[[
        "date","target_status","target_star_low","target_star_high",
        "target_target_mid","target_training_weight","cp","log_close"
    ]].copy()
    out["pred_static"]=static_pred
    out["pred_online_anchor"]=online_pred
    out["online_minus_static"]=online_pred-static_pred

    summary={
        "selectionPolicy":(
            "Rolling-anchor window and statistic are selected only on 2023-2024 "
            "expanding validation. During holdout prediction, only previously "
            "published target observations may update the anchor; no future target is used."
        ),
        "selectedWindow":int(best["window"]),
        "selectedStatistic":str(best["method"]),
        "selectedPreHoldoutExactMae":float(best["cv_exact_mae"]),
        "priceCoefficient":slope,
        "staticHoldoutMetrics":static_metrics,
        "onlineAnchorHoldoutMetrics":online_metrics,
        "holdoutExactMaeImprovement":float(static_metrics["exact_mae"]-online_metrics["exact_mae"]),
        "holdoutRelativeExactMaeImprovement":float(
            (static_metrics["exact_mae"]-online_metrics["exact_mae"])/static_metrics["exact_mae"]
        ),
        "interpretation":(
            "Online anchor adaptation is evidence for anchor drift only if its pre-holdout-selected "
            "rule improves the locked holdout. Because it uses prior published stars, it is an adaptive "
            "replica mechanism rather than a fully exogenous price-only formula."
        ),
    }

    DERIVED.mkdir(parents=True,exist_ok=True)
    grid.to_csv(GRID_OUTPUT,index=False,encoding="utf-8-sig")
    out.to_csv(HOLDOUT_OUTPUT,index=False,encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
