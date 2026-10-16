"""Train, calibrate and register the real-data risk models.

Three tasks, three models, three targets - never merged (their labels mean different things):
    olist_late_at_handoff           P(delivered after the promised day | plan known at carrier hand-off)        Brazil e-commerce
    amazon_package_failed_attempt   P(any non-delivered visit | route plan at departure)                         US last-mile routes
    lade_slow_delivery_task         P(accept->deliver duration > train-period P90 | context + resolved history)  China last-mile tasks

Protocol (fixed before looking at test): chronological train / valid / test with an embargo; candidates and feature sets are
compared on VALID only; a richer feature set must beat the simpler one by >= 5% relative valid PR-AUC to be adopted; the
calibrator (isotonic vs Platt) is chosen on the second half of valid after fitting on the first, then refit on all of valid;
TEST is touched once, for the chosen model. Rows with a missing feature are dropped (the serving contract refuses to impute).

Run:  python -I -m dallal.ml.train [olist|amazon|lade ...]    -> backend/artifacts/<id>/{model.joblib,card.json}, docs/ml/models.json
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from dallal.config import PATHS
from dallal.data import leakage
from dallal.data.splits import Split, time_split
from dallal.ml import features as F
from dallal.ml.metrics import binary_report, ece
from dallal.ml.registry import Calibrator, FeatureSpec, ModelCard, TrainedModel, save

RICHER_MUST_BEAT = 1.05  # relative valid PR-AUC


@dataclass
class TaskSpec:
    model_id: str
    task_id: str
    target: str
    source: str
    licence: str
    unit: str
    as_of: str
    frame: Callable[[], pd.DataFrame]
    split: Callable[[pd.DataFrame], Split]
    feature_sets: list[tuple[str, list[str]]]  # simple -> rich
    describe: dict[str, str]
    caveats: list[str]
    label: Callable[[pd.DataFrame, Split], np.ndarray] | None = None
    extra: Callable[[pd.DataFrame, Split], dict] | None = None


def _estimators() -> dict[str, Callable[[], object]]:
    return {
        "logreg": lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=500)),
        "hist_gbm": lambda: HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06, max_leaf_nodes=31, l2_regularization=1.0, random_state=0),
    }


def _auc_ci(y: np.ndarray, p: np.ndarray, n_boot: int = 100, seed: int = 0) -> list[float]:
    rng = np.random.default_rng(seed)
    n = len(y)
    if n > 120_000:  # bootstrap on a fixed-size subsample of resamples for speed; the interval is for the full-sample AUC
        size = 120_000
    else:
        size = n
    vals = []
    for _ in range(n_boot):
        i = rng.integers(0, n, size)
        if y[i].min() == y[i].max():
            continue
        vals.append(roc_auc_score(y[i], p[i]))
    return [round(float(np.quantile(vals, 0.025)), 4), round(float(np.quantile(vals, 0.975)), 4)]


def _reliability(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    order = np.argsort(p)
    out = []
    for c in np.array_split(order, bins):
        out.append({"n": int(len(c)), "mean_predicted": round(float(p[c].mean()), 5), "observed": round(float(y[c].mean()), 5)})
    return out


def _choose_calibrator(raw_v: np.ndarray, y_v: np.ndarray) -> tuple[str, dict]:
    h = len(raw_v) // 2
    scores = {}
    for kind in ("isotonic", "platt"):
        c = Calibrator.fit(kind, raw_v[:h], y_v[:h])
        p = np.clip(c(raw_v[h:]), 1e-6, 1 - 1e-6)
        scores[kind] = float(log_loss(y_v[h:], p))
    return min(scores, key=scores.get), scores  # type: ignore[arg-type]


def train_task(spec: TaskSpec) -> tuple[TrainedModel, dict]:
    t0 = time.time()
    x = spec.frame().reset_index(drop=True)
    sp = spec.split(x)
    y = spec.label(x, sp) if spec.label else x["_y"].to_numpy()
    all_feats = sorted({f for _, fs in spec.feature_sets for f in fs})
    complete = x[all_feats].notna().all(axis=1).to_numpy()
    dropped = {"rows": int(len(x)), "dropped_incomplete": int((~complete).sum()), "fraction": round(float((~complete).mean()), 4)}
    tr, va, te = (idx[complete[idx]] for idx in (sp.train, sp.valid, sp.test))
    for _, fs in spec.feature_sets:
        leakage.assert_features_clean(spec.task_id, x[fs])
        leakage.assert_no_label_proxy(x.iloc[tr][fs], y[tr])

    trials: dict[str, dict] = {}
    best: tuple[float, str, str] | None = None
    fitted: dict[tuple[str, str], object] = {}
    for fs_name, fs in spec.feature_sets:
        for est_name, mk in _estimators().items():
            m = mk()
            m.fit(x.iloc[tr][fs], y[tr])  # type: ignore[attr-defined]
            pv = m.predict_proba(x.iloc[va][fs])[:, 1]  # type: ignore[attr-defined]
            key = f"{est_name}|{fs_name}"
            trials[key] = {"valid_pr_auc": round(float(average_precision_score(y[va], pv)), 4), "valid_roc_auc": round(float(roc_auc_score(y[va], pv)), 4), "n_features": len(fs)}
            fitted[(fs_name, est_name)] = m
    # choose: best estimator per feature set, then simplest set unless a richer one clearly wins on valid
    per_set = {}
    for fs_name, _ in spec.feature_sets:
        cands = {e: trials[f"{e}|{fs_name}"]["valid_pr_auc"] for e in _estimators()}
        e = max(cands, key=cands.get)  # type: ignore[arg-type]
        per_set[fs_name] = (e, cands[e])
    chosen_set = spec.feature_sets[0][0]
    for fs_name, _ in spec.feature_sets[1:]:
        if per_set[fs_name][1] >= RICHER_MUST_BEAT * per_set[chosen_set][1]:
            chosen_set = fs_name
    est_name = per_set[chosen_set][0]
    feats = dict(spec.feature_sets)[chosen_set]
    model = fitted[(chosen_set, est_name)]
    best = (per_set[chosen_set][1], chosen_set, est_name)

    raw_v = model.predict_proba(x.iloc[va][feats])[:, 1]  # type: ignore[attr-defined]
    cal_kind, cal_scores = _choose_calibrator(raw_v, y[va])
    cal = Calibrator.fit(cal_kind, raw_v, y[va])
    p_v = cal(raw_v)
    raw_t = model.predict_proba(x.iloc[te][feats])[:, 1]  # type: ignore[attr-defined]
    p_t = cal(raw_t)

    xt = x.iloc[tr][feats]
    specs = [FeatureSpec(f, float(np.quantile(xt[f], 0.005)), float(np.quantile(xt[f], 0.995)), spec.describe.get(f, "")) for f in feats]
    q = np.quantile(p_v, [0.85, 0.95])
    thresholds = {"elevated": float(q[0]), "high": float(q[1])}
    test_report_raw = binary_report(y[te], raw_t)
    test_report = binary_report(y[te], p_t)
    metrics = {
        "valid": binary_report(y[va], p_v), "test": test_report, "test_auc_95ci": _auc_ci(y[te], p_t),
        "test_calibration": {"mean_predicted": round(float(p_t.mean()), 5), "observed": round(float(y[te].mean()), 5), "ece_uncalibrated_raw": test_report_raw["ece"],
                             "ece_calibrated": round(ece(y[te], p_t), 5), "reliability_deciles": _reliability(y[te], p_t)},
        "valid_trials": trials, "calibrator_trial_logloss": cal_scores, "chosen": {"estimator": est_name, "feature_set": chosen_set},
        "incomplete_row_handling": dropped,
    }
    # reference: the reported test AUC of every candidate, for transparency only (never used for selection)
    baselines = {}
    for (fs_name, en), m in fitted.items():
        pb = m.predict_proba(x.iloc[te][dict(spec.feature_sets)[fs_name]])[:, 1]  # type: ignore[attr-defined]
        baselines[f"{en}|{fs_name}"] = {"test_roc_auc": round(float(roc_auc_score(y[te], pb)), 4), "test_pr_auc": round(float(average_precision_score(y[te], pb)), 4)}
    t_all = x["_t"].to_numpy()
    card = ModelCard(
        model_id=spec.model_id, task_id=spec.task_id, target=spec.target, source=spec.source, licence=spec.licence, unit=spec.unit, as_of=spec.as_of,
        algorithm=("HistGradientBoosting (250 it, lr .06, 31 leaves, L2 1.0)" if est_name == "hist_gbm" else "Standardised logistic regression"),
        calibration=f"{cal_kind} fitted on the validation window ({len(va)} rows)", features=specs,
        split={"train": int(len(tr)), "valid": int(len(va)), "test": int(len(te)), "train_prevalence": round(float(y[tr].mean()), 5), "valid_prevalence": round(float(y[va].mean()), 5),
               "test_prevalence": round(float(y[te].mean()), 5), "cuts": sp.cuts, "time_min": float(t_all.min()), "time_max": float(t_all.max())},
        metrics=metrics, baselines=baselines, base_rate_train=float(y[tr].mean()), base_rate_valid=float(y[va].mean()), band_thresholds=thresholds, caveats=spec.caveats,
        trained_at=pd.Timestamp.now().isoformat(timespec="seconds"), extra=(spec.extra(x, sp) if spec.extra else {}),
    )
    tm = TrainedModel(model, cal, card)
    save(tm)
    # Local-only replay sample (never committed: the source licences forbid redistributing the data): 400 random held-out TEST rows.
    rs = np.random.default_rng(0).choice(te, size=min(400, len(te)), replace=False)
    rep = x.iloc[rs][feats].copy()
    rep["_label"], rep["_probability"] = y[rs], p_t[np.searchsorted(te, rs)]
    rdir = PATHS.data / "replay"
    rdir.mkdir(parents=True, exist_ok=True)
    rep.to_parquet(rdir / f"{spec.model_id}.parquet")
    return tm, {"seconds": round(time.time() - t0, 1), "chosen": best}


# ── task specifications ─────────────────────────────────────────────────────────────────────────────────────────────
OLIST_BASE = ["lead_days_at_handoff", "promised_total_days", "distance_km", "same_state", "value", "weight_g", "freight_value", "n_items", "purchase_to_approval_h", "approval_to_handoff_h",
              "handoff_hour", "handoff_dow"]


def _olist_frame() -> pd.DataFrame:
    return F.keep_dense_months(F.olist_frame(), 500).reset_index(drop=True)


def _amazon_frame() -> pd.DataFrame:
    x = F.amazon_frame()
    x["window_h"] = x["window_h"].fillna(0.0)  # defined encoding of "no delivery window" (has_window = 0); not an estimate of an unknown value
    return x


AMAZON_BASE = ["volume_cm3", "planned_service_s", "pk_at_stop", "pk_on_route", "n_stops", "capacity", "load_ratio", "has_window", "window_h", "dep_hour", "dep_dow", "svc_per_pkg"]
LADE_BASE = ["hour", "dow", "aoi_type", "open_tasks_courier", "accept_dist_m"]


def _lade_frame() -> pd.DataFrame:
    return F.lade_frame("sh", sample=400_000)


def _lade_label(x: pd.DataFrame, sp: Split) -> np.ndarray:
    thr = float(np.quantile(x["_dur"].to_numpy()[sp.train], 0.9))  # threshold from TRAIN only
    return (x["_dur"].to_numpy() > thr).astype(int)


def _lade_extra(x: pd.DataFrame, sp: Split) -> dict:
    return {"slow_threshold_min": round(float(np.quantile(x["_dur"].to_numpy()[sp.train], 0.9)), 1), "city": "sh"}


def specs() -> dict[str, TaskSpec]:
    return {
        "olist": TaskSpec(
            "olist_late_at_handoff_v1", "olist_late_at_handoff", "delivered after the promised calendar day (engineered from observed timestamps)", "Olist Brazilian e-commerce (public)", "CC BY-NC-SA 4.0 (non-commercial research use)",
            "order", "carrier hand-off timestamp", _olist_frame, lambda x: time_split(x, "_t", embargo=30, origin_col="_origin"),
            [("plan", OLIST_BASE)],
            {"lead_days_at_handoff": "promised date minus hand-off date (days)", "promised_total_days": "promised date minus purchase (days)", "distance_km": "seller to destination (km)"},
            ["Source: Brazilian multi-day e-commerce, 2017-2018. Not Saudi same-day delivery; probabilities describe that population.", "Right-censored edge months excluded.", "The late rate drifted between the validation and test windows; calibration-in-the-large does not survive that shift, so treat probabilities as ranking evidence.",
             "History features (seller/state/zip late rates) were evaluated and rejected: they hurt on the later period.", "Used by Dallal only when the case satisfies the feature contract and sits inside the training range."]),
        "amazon": TaskSpec(
            "amazon_failed_attempt_v1", "amazon_package_failed_attempt", "any non-delivered visit for this package on its route", "Amazon Last Mile Routing Research Challenge (public)", "CC BY-NC 4.0 (non-commercial; research/hackathon use)",
            "package", "planned route departure", _amazon_frame, lambda x: time_split(x, "_t", embargo=1, origin_col="_origin"),
            [("plan", AMAZON_BASE), ("plan+history", AMAZON_BASE + ["zone_past_fail_rate", "zone_past_n", "station_past_fail_rate", "station_past_n"])],
            {"load_ratio": "packages on route / stops", "svc_per_pkg": "planned service seconds per package at the stop"},
            ["Source: US urban van routes, one year. Failure reason is not observed: this is attempt-failure RISK, not a diagnosis.", "0.6-0.8% prevalence: expect many false alarms at any useful recall."]),
        "lade": TaskSpec(
            "lade_slow_task_v1", "lade_slow_delivery_task", "accept-to-deliver duration above the training-period P90 (engineered)", "LaDe last-mile delivery (Cainiao), Shanghai", "Apache-2.0 per HF metadata; README restricts to research use",
            "delivery task", "courier accept time", _lade_frame, lambda x: time_split(x, "_t", origin_col="_origin"),
            [("context", LADE_BASE), ("context+history", LADE_BASE + ["aoi_past_logdur", "aoi_past_n", "courier_past_logdur", "courier_past_n", "region_past_logdur", "region_past_n"])],
            {"open_tasks_courier": "tasks the courier had accepted but not completed at accept time", "aoi_past_logdur": "shrunk mean log-duration of earlier-resolved tasks in the same AOI"},
            ["Source: Shanghai intra-city tasks (Chinese yearless timestamps); a proxy for stalled / slow deliveries - LaDe has no failure labels.", "History features need a serving-time history store (resolved-before-as_of only)."],
            _lade_label, _lade_extra),
    }


def main(argv: list[str]) -> None:
    which = argv or ["olist", "amazon", "lade"]
    all_specs = specs()
    out: dict = {"generated": pd.Timestamp.now().isoformat(timespec="seconds"), "protocol": __doc__.split("Protocol")[1].split("Run:")[0].strip(), "models": {}}
    for k in which:
        tm, info = train_task(all_specs[k])
        c = tm.card
        print(f"{c.model_id}: chosen={info['chosen']} test_auc={c.metrics['test']['roc_auc']} pr_auc={c.metrics['test']['pr_auc']} ece={c.metrics['test']['ece']} ({info['seconds']}s)")
        out["models"][c.model_id] = c.to_json()
    p = PATHS.docs / "ml" / "models.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():  # keep earlier models when training a subset
        prev = json.loads(p.read_text())
        prev["models"].update(out["models"])
        out["models"] = prev["models"]
    p.write_text(json.dumps(out, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
