"""Feasibility baselines on REAL data with the leakage guards and time-aware splits enforced.

Purpose: learn which tasks are learnable (and how well) BEFORE wiring a model behind `predict_risk`. These are baselines, not
products: untuned gradient boosting vs trivial reference models, one split, no model selection on the test set.

Run:  python -I -m dallal.ml.baselines   (writes docs/ml/baselines.json; needs built canonical tables)
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from dallal.config import PATHS
from dallal.data import leakage
from dallal.data.splits import Split, time_split
from dallal.ml import features as F
from dallal.ml.metrics import binary_report


def _fit_eval(x: pd.DataFrame, y: np.ndarray, sp: Split, feats: list[str], model_name: str, task: str) -> dict:
    leakage.assert_features_clean(task, x[feats])
    leakage.assert_no_label_proxy(x[feats], y)
    if model_name == "gbm":
        m = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06, max_leaf_nodes=31, l2_regularization=1.0, random_state=0)
    else:
        m = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(max_iter=500))
    t0 = time.time()
    m.fit(x.iloc[sp.train][feats], y[sp.train])
    rep = {"valid": binary_report(y[sp.valid], m.predict_proba(x.iloc[sp.valid][feats])[:, 1]),
           "test": binary_report(y[sp.test], m.predict_proba(x.iloc[sp.test][feats])[:, 1]), "fit_seconds": round(time.time() - t0, 1), "n_features": len(feats)}
    return rep


def _split_info(x: pd.DataFrame, y: np.ndarray, sp: Split) -> dict:
    return {"train": int(len(sp.train)), "valid": int(len(sp.valid)), "test": int(len(sp.test)), "train_prevalence": round(float(y[sp.train].mean()), 5),
            "test_prevalence": round(float(y[sp.test].mean()), 5), "cuts": sp.cuts}


def olist() -> dict:
    x = F.keep_dense_months(F.olist_frame(), 500).reset_index(drop=True)
    y = x["_y"].to_numpy()
    sp = time_split(x, "_t", embargo=30, origin_col="_origin")
    base = ["lead_days_at_handoff", "promised_total_days", "distance_km", "same_state", "value", "weight_g", "freight_value", "n_items",
            "purchase_to_approval_h", "approval_to_handoff_h", "handoff_hour", "handoff_dow"]
    rates = [c for c in x.columns if c.endswith("_past_late_rate")]
    counts = [c for c in x.columns if c.endswith("_past_n")]
    hist = rates + counts
    return {"split": _split_info(x, y, sp), "months_used": sorted(x["_month"].unique())[:1] + sorted(x["_month"].unique())[-1:],
            "logreg_plan_features": _fit_eval(x, y, sp, base, "logreg", "olist_late_delivery_at_handoff"),
            "gbm_plan_features": _fit_eval(x, y, sp, base, "gbm", "olist_late_delivery_at_handoff"),
            "gbm_plan_plus_history_rates_only": _fit_eval(x, y, sp, base + rates, "gbm", "olist_late_delivery_at_handoff"),
            "gbm_plan_plus_history": _fit_eval(x, y, sp, base + hist, "gbm", "olist_late_delivery_at_handoff"),
            "diagnosis": "history COUNT features grow monotonically with calendar time, so trees can use them as a clock and extrapolate badly into a later "
                         "period; rate-only history avoids that. Variant choice should be made on the validation split, not on test."}


def amazon() -> dict:
    x = F.amazon_frame()
    y = x["_y"].to_numpy()
    sp = time_split(x, "_t", embargo=1, origin_col="_origin")
    base = ["volume_cm3", "planned_service_s", "pk_at_stop", "pk_on_route", "n_stops", "capacity", "load_ratio", "has_window", "window_h", "dep_hour", "dep_dow", "svc_per_pkg"]
    hist = [c for c in x.columns if "_past_" in c]
    return {"split": _split_info(x, y, sp),
            "logreg_plan_features": _fit_eval(x, y, sp, base, "logreg", "amazon_package_failed_attempt"),
            "gbm_plan_features": _fit_eval(x, y, sp, base, "gbm", "amazon_package_failed_attempt"),
            "gbm_plan_plus_history": _fit_eval(x, y, sp, base + hist, "gbm", "amazon_package_failed_attempt")}


def lade(code: str = "sh") -> dict:
    x = F.lade_frame(code, sample=400_000)
    sp = time_split(x, "_t", origin_col="_origin")
    thr = float(np.quantile(x["_dur"].to_numpy()[sp.train], 0.9))  # threshold from TRAIN only
    y = (x["_dur"].to_numpy() > thr).astype(int)
    base = ["hour", "dow", "aoi_type", "open_tasks_courier", "accept_dist_m"]
    hist = [c for c in x.columns if "_past_" in c]
    info = _split_info(x, y, sp)
    info["slow_threshold_min_from_train_p90"] = round(thr, 1)
    return {"city": code, "split": info, "logreg_context_features": _fit_eval(x, y, sp, base, "logreg", "lade_delivery_task_duration_min"),
            "gbm_context_features": _fit_eval(x, y, sp, base, "gbm", "lade_delivery_task_duration_min"),
            "gbm_context_plus_history": _fit_eval(x, y, sp, base + hist, "gbm", "lade_delivery_task_duration_min")}


def main() -> None:
    out = {"generated": pd.Timestamp.now().isoformat(timespec="seconds"), "note": "Feasibility baselines, one chronological split, untuned. Not production models."}
    for name, fn in (("olist_late_at_handoff", olist), ("amazon_package_failed_attempt", amazon), ("lade_slow_delivery_task", lade)):
        out[name] = fn()
        print(name, json.dumps({k: v["test"] for k, v in out[name].items() if isinstance(v, dict) and "test" in v}, indent=1))
    p = PATHS.docs / "ml" / "baselines.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
