from __future__ import annotations

import json

import numpy as np
import pandas as pd

from dynamic_price_residual_analysis import DERIVED, prepare_panel

PROSPECTIVE_TARGET = DERIVED.parent / "verified" / "star_target_prospective_2026_09_onward.csv"
PROSPECTIVE_PRICE = DERIVED.parent / "verified" / "csi_all_share_prospective_2026_08_31_2026_10_09.csv"

SUMMARY_OUTPUT = DERIVED / "p2_nonlinear_price_curve_summary.json"
COEF_OUTPUT = DERIVED / "p2_nonlinear_price_curve_coefficients.csv"
PRED_OUTPUT = DERIVED / "p2_nonlinear_price_curve_predictions.csv"
RESIDUAL_OUTPUT = DERIVED / "p2_nonlinear_price_curve_residual_by_star.csv"

DEGREES = (1, 2, 3, 4)


def fine_exact(frame: pd.DataFrame) -> pd.DataFrame:
    use = frame[
        frame["target_status"].eq("exact")
        & pd.to_numeric(frame["target_target_mid"], errors="coerce").notna()
        & pd.to_numeric(frame["cp"], errors="coerce").gt(0)
        & pd.to_datetime(frame["date"]).ge(pd.Timestamp("2022-05-31"))
    ].copy()
    use["target"] = pd.to_numeric(use["target_target_mid"], errors="coerce")
    use["weight"] = pd.to_numeric(use["target_training_weight"], errors="coerce").fillna(1.0)
    use["x"] = -np.log(pd.to_numeric(use["cp"], errors="coerce"))
    use["year"] = pd.to_datetime(use["date"]).dt.year
    return use.sort_values("date").reset_index(drop=True)


def build_prospective() -> pd.DataFrame:
    price = pd.read_csv(PROSPECTIVE_PRICE)
    target = pd.read_csv(PROSPECTIVE_TARGET)
    price["date"] = pd.to_datetime(price["date"]).dt.normalize()
    target["date"] = pd.to_datetime(target["date"]).dt.normalize()
    out = price.merge(target[["date", "star", "status"]], on="date", how="inner", validate="one_to_one")
    out["target"] = pd.to_numeric(out["star"], errors="coerce")
    out["weight"] = 1.0
    out["x"] = -np.log(pd.to_numeric(out["cp"], errors="coerce"))
    out["year"] = out["date"].dt.year
    return out.sort_values("date").reset_index(drop=True)


def weighted_lstsq(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> np.ndarray:
    root = np.sqrt(w)
    return np.linalg.lstsq(x * root[:, None], y * root, rcond=None)[0]


def fit_poly(train: pd.DataFrame, degree: int) -> dict[str, object]:
    use = train.dropna(subset=["x", "target", "weight"]).copy()
    use = use[use["weight"] > 0]
    raw_x = use["x"].to_numpy(dtype=float)
    mean = float(np.average(raw_x, weights=use["weight"].to_numpy(dtype=float)))
    sd = float(np.sqrt(np.average((raw_x - mean) ** 2, weights=use["weight"].to_numpy(dtype=float))))
    if not np.isfinite(sd) or sd <= 0:
        raise ValueError("invalid x scale")
    z = (raw_x - mean) / sd
    design = np.column_stack([np.ones(len(use)), *[z ** power for power in range(1, degree + 1)]])
    y = use["target"].to_numpy(dtype=float)
    w = use["weight"].to_numpy(dtype=float)
    beta = weighted_lstsq(design, y, w)
    return {
        "degree": degree,
        "mean": mean,
        "sd": sd,
        "beta": beta,
        "n": int(len(use)),
    }


def predict(frame: pd.DataFrame, fit: dict[str, object]) -> np.ndarray:
    x = frame["x"].to_numpy(dtype=float)
    z = (x - float(fit["mean"])) / float(fit["sd"])
    degree = int(fit["degree"])
    design = np.column_stack([np.ones(len(frame)), *[z ** power for power in range(1, degree + 1)]])
    return design @ np.asarray(fit["beta"], dtype=float)


def score(frame: pd.DataFrame, pred: np.ndarray) -> dict[str, float | int]:
    actual = frame["target"].to_numpy(dtype=float)
    pred = np.asarray(pred, dtype=float)
    mask = np.isfinite(actual) & np.isfinite(pred)
    actual = actual[mask]
    pred = pred[mask]
    err = np.abs(pred - actual)
    rounded = np.round(pred / 0.1) * 0.1
    rerr = np.abs(rounded - actual)
    return {
        "n": int(mask.sum()),
        "continuousMae": float(err.mean()),
        "continuousRmse": float(np.sqrt(np.mean(err**2))),
        "roundedMae": float(rerr.mean()),
        "roundedExactMatch": float((rerr <= 1e-8).mean()),
        "roundedWithin0_1": float((rerr <= 0.1000001).mean()),
        "maxRoundedError": float(rerr.max()),
    }


def serialize(fold: str, fit: dict[str, object]) -> list[dict[str, object]]:
    beta = np.asarray(fit["beta"], dtype=float)
    rows = [{
        "fold": fold,
        "degree": int(fit["degree"]),
        "term": "intercept",
        "coefficient": float(beta[0]),
        "xMean": float(fit["mean"]),
        "xSd": float(fit["sd"]),
    }]
    for power, value in enumerate(beta[1:], start=1):
        rows.append({
            "fold": fold,
            "degree": int(fit["degree"]),
            "term": f"z^{power}",
            "coefficient": float(value),
            "xMean": float(fit["mean"]),
            "xSd": float(fit["sd"]),
        })
    return rows


def residual_by_star(frame: pd.DataFrame, pred: np.ndarray, model: str) -> pd.DataFrame:
    out = frame[["date", "target"]].copy()
    out["prediction"] = pred
    out["residual"] = out["target"] - out["prediction"]
    out["model"] = model
    rows = []
    for star, group in out.groupby("target"):
        if len(group) < 5:
            continue
        rows.append({
            "model": model,
            "star": float(star),
            "n": int(len(group)),
            "meanResidual": float(group["residual"].mean()),
            "medianResidual": float(group["residual"].median()),
            "sdResidual": float(group["residual"].std(ddof=1)),
        })
    return pd.DataFrame(rows)


def main() -> None:
    panel = fine_exact(prepare_panel())
    prospective = build_prospective()

    folds = []
    coef_rows = []
    for train_end, test_year in ((2022, 2023), (2023, 2024)):
        train = panel[panel["year"] <= train_end].copy()
        test = panel[panel["year"] == test_year].copy()
        result = {"trainEnd": train_end, "testYear": test_year, "models": {}}
        for degree in DEGREES:
            fit = fit_poly(train, degree)
            result["models"][f"degree{degree}"] = score(test, predict(test, fit))
            coef_rows.extend(serialize(f"{train_end}->{test_year}", fit))
        folds.append(result)

    pre_summary = {}
    for degree in DEGREES:
        key = f"degree{degree}"
        pre_summary[key] = {
            "meanContinuousMae": float(np.mean([x["models"][key]["continuousMae"] for x in folds])),
            "meanRoundedMae": float(np.mean([x["models"][key]["roundedMae"] for x in folds])),
            "meanRoundedExactMatch": float(np.mean([x["models"][key]["roundedExactMatch"] for x in folds])),
        }

    selected_degree = int(
        min(
            DEGREES,
            key=lambda degree: (
                pre_summary[f"degree{degree}"]["meanRoundedMae"],
                pre_summary[f"degree{degree}"]["meanContinuousMae"],
            ),
        )
    )

    train = panel[panel["year"] <= 2024].copy()
    observed = panel[(panel["year"] >= 2025) & (panel["date"] <= pd.Timestamp("2026-08-31"))].copy()

    final_results = {}
    prediction_rows = []
    residual_frames = []
    for degree in DEGREES:
        fit = fit_poly(train, degree)
        coef_rows.extend(serialize("2022-2024_final", fit))

        observed_pred = predict(observed, fit)
        prospective_pred = predict(prospective, fit)

        final_results[f"degree{degree}"] = {
            "observed2025ToFreeze": score(observed, observed_pred),
            "firstProspectiveSepOct2026": score(prospective, prospective_pred),
        }

        for frame, pred, period in (
            (observed, observed_pred, "observed_2025_to_freeze"),
            (prospective, prospective_pred, "first_prospective_sep_oct_2026"),
        ):
            current = frame[["date", "target", "cp"]].copy()
            current["period"] = period
            current["degree"] = degree
            current["prediction"] = pred
            current["roundedPrediction"] = np.round(pred / 0.1) * 0.1
            current["absoluteError"] = np.abs(current["prediction"] - current["target"])
            prediction_rows.append(current)

        residual_frames.append(
            residual_by_star(
                train,
                predict(train, fit),
                f"degree{degree}",
            )
        )

    selected = f"degree{selected_degree}"
    summary = {
        "purpose": (
            "Test whether apparent anchor drift/regime shifts are partly caused by forcing "
            "a linear log-price-to-star mapping onto a nonlinear relationship."
        ),
        "targetPolicy": "modern fine exact stars from 2022-05-31 onward",
        "selectionPolicy": (
            "Polynomial degree is selected only on the 2023 and 2024 expanding folds. "
            "2025-2026 and Sep-Oct 2026 are diagnostic only."
        ),
        "xDefinition": "-log(A股全指 close)",
        "expandingFolds": folds,
        "preHoldoutSummary": pre_summary,
        "selectedDegreeByPreHoldout": selected_degree,
        "selectedModel": selected,
        "postSelectionDiagnostics": final_results,
        "researchWarning": (
            "The nonlinear-price architecture was proposed after the first Sep-Oct 2026 "
            "prospective window had already been inspected. Its future-window score is therefore "
            "post-hoc architecture evidence, not a clean prospective confirmation. Any promotion "
            "requires dates strictly after 2026-10-09."
        ),
    }

    DERIVED.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(coef_rows).to_csv(COEF_OUTPUT, index=False, encoding="utf-8-sig")
    pd.concat(prediction_rows, ignore_index=True).to_csv(PRED_OUTPUT, index=False, encoding="utf-8-sig")
    pd.concat(residual_frames, ignore_index=True).to_csv(RESIDUAL_OUTPUT, index=False, encoding="utf-8-sig")
    SUMMARY_OUTPUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
