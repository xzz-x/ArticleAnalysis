from __future__ import annotations

import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, prepare_panel
from p2_online_anchor_analysis import online_anchor_predict, preholdout_grid, score

GRID_OUTPUT = DERIVED / "p2_adaptive_hysteresis_grid.csv"
HOLDOUT_OUTPUT = DERIVED / "p2_adaptive_hysteresis_holdout.csv"
SUMMARY_OUTPUT = DERIVED / "p2_adaptive_hysteresis_summary.json"


def last_observed_state(train: pd.DataFrame) -> float:
    use=train.sort_values("date").copy()
    use=use[
        (pd.to_numeric(use["target_training_weight"],errors="coerce")>0)
        & pd.to_numeric(use["target_target_mid"],errors="coerce").notna()
    ]
    if use.empty:
        raise ValueError("no prior published target state")
    return float(use.iloc[-1]["target_target_mid"])


def adaptive_hysteresis_publish(
    latent: np.ndarray,
    train: pd.DataFrame,
    test: pd.DataFrame,
    threshold_up: float,
    threshold_down: float,
) -> np.ndarray:
    """One-step publication rule using only the previously observed published star."""
    state=last_observed_state(train)
    out=[]
    for value,row in zip(np.asarray(latent,dtype=float),test.sort_values("date").itertuples(index=False)):
        if np.isfinite(value):
            delta=float(value-state)
            if delta>=threshold_up or delta<=-threshold_down:
                state=float(np.round(value/0.1)*0.1)
        out.append(state)

        # After predicting date t, its published target is available for date t+1.
        weight=float(row.target_training_weight) if pd.notna(row.target_training_weight) else 0.0
        mid=float(row.target_target_mid) if pd.notna(row.target_target_mid) else np.nan
        if weight>0 and np.isfinite(mid):
            state=mid
    return np.asarray(out,dtype=float)


def threshold_grid(
    panel: pd.DataFrame,
    window: int,
    method: str,
) -> pd.DataFrame:
    folds=((2022,2023),(2023,2024))
    rows=[]
    for up in np.arange(0.02,0.151,0.01):
        for down in np.arange(0.02,0.151,0.01):
            fold_scores=[]
            for train_end,test_year in folds:
                train=panel[panel["year"]<=train_end].copy()
                test=panel[panel["year"]==test_year].copy().sort_values("date")
                latent,_=online_anchor_predict(train,test,window,method)
                pred=adaptive_hysteresis_publish(
                    latent,train,test,float(np.round(up,2)),float(np.round(down,2))
                )
                fold_scores.append(score(test,pred))
            rows.append({
                "threshold_up":float(np.round(up,2)),
                "threshold_down":float(np.round(down,2)),
                "cv_exact_mae":float(np.mean([x["exact_mae"] for x in fold_scores])),
                "cv_interval_mae":float(np.mean([x["interval_mae"] for x in fold_scores])),
                "cv_exact_within_0_1":float(np.mean([x["exact_within_0_1"] for x in fold_scores])),
            })
    return pd.DataFrame(rows).sort_values(["cv_exact_mae","cv_interval_mae"],ignore_index=True)


def main()->None:
    panel=prepare_panel()

    anchor_grid=preholdout_grid(panel)
    best_anchor=anchor_grid.iloc[0]
    window=int(best_anchor["window"])
    method=str(best_anchor["method"])

    grid=threshold_grid(panel,window,method)
    best=grid.iloc[0]

    train=panel[panel["year"]<=2024].copy()
    holdout=panel[panel["year"]>=2025].copy().sort_values("date")
    latent,slope=online_anchor_predict(train,holdout,window,method)
    discrete=adaptive_hysteresis_publish(
        latent,train,holdout,float(best["threshold_up"]),float(best["threshold_down"])
    )

    anchor_metrics=score(holdout,latent)
    discrete_metrics=score(holdout,discrete)

    out=holdout[[
        "date","target_status","target_star_low","target_star_high",
        "target_target_mid","target_training_weight","cp","log_close"
    ]].copy()
    out["pred_online_anchor"]=latent
    out["pred_adaptive_hysteresis"]=discrete
    out["hysteresis_minus_anchor"]=discrete-latent

    summary={
        "selectionPolicy":(
            "Anchor window/statistic and hysteresis thresholds are selected only on "
            "2023-2024 expanding validation. Each prediction may use today's price "
            "and previously published stars, but never today's or future target."
        ),
        "anchorWindow":window,
        "anchorStatistic":method,
        "thresholdUp":float(best["threshold_up"]),
        "thresholdDown":float(best["threshold_down"]),
        "thresholdPreHoldoutExactMae":float(best["cv_exact_mae"]),
        "priceCoefficient":slope,
        "onlineAnchorHoldoutMetrics":anchor_metrics,
        "adaptiveHysteresisHoldoutMetrics":discrete_metrics,
        "holdoutExactMaeImprovementVsAnchor":float(
            anchor_metrics["exact_mae"]-discrete_metrics["exact_mae"]
        ),
        "holdoutRelativeExactMaeImprovementVsAnchor":float(
            (anchor_metrics["exact_mae"]-discrete_metrics["exact_mae"])
            /anchor_metrics["exact_mae"]
        ),
        "interpretation":(
            "A positive locked-holdout improvement means publication-state hysteresis "
            "adds information beyond leakage-safe online anchor adaptation."
        ),
    }

    DERIVED.mkdir(parents=True,exist_ok=True)
    grid.to_csv(GRID_OUTPUT,index=False,encoding="utf-8-sig")
    out.to_csv(HOLDOUT_OUTPUT,index=False,encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
