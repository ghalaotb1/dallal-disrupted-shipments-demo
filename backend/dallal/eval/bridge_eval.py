"""Evaluation of the model bridge: do trained models reach the agent responsibly?  (Part A real data; Part C coverage on the demo scenarios)

1. Coverage: how often do the trained models score the agent's DEMO/SYNTHETIC scenarios?  (Expected: never - the domain gate refuses them. This is the point.)
2. LaDe replay (real held-out tasks, as_of = accept + 10 min): train/serve parity of the bridged features, discrimination of the bridged scores vs the heuristic,
   abstention reasons, a point-in-time (no look-ahead) check, and an end-to-end agent run showing model-labelled results in the trace.
3. Amazon replay (real held-out routes): same parity / discrimination check for the plan-feature model.
Needs the canonical tables (local). Run: python -I -m dallal.eval.bridge_eval  -> docs/experiments/model_bridge.json
"""

from __future__ import annotations

import json
import time
from collections import Counter

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from dallal.agent.v2.runtime import AgentRuntimeV2
from dallal.config import PATHS
from dallal.data.augment.scenarios import SCENARIOS
from dallal.data.replay import lade_bundle, lade_replay
from dallal.ml import features as F
from dallal.ml import registry
from dallal.ml.pit import LadeStore
from dallal.ml.risk import TrainedRiskModel
from dallal.tools.bundle import Bundle
from dallal.tools.providers import DefaultProviders, HeuristicRiskModel


def _auc(y, p, boot: int = 300) -> dict:
    y, p = np.asarray(y), np.asarray(p)
    if len(set(y.tolist())) < 2:
        return {"n": int(len(y))}
    rng = np.random.default_rng(0)
    bs = []
    for _ in range(boot):
        i = rng.integers(0, len(y), len(y))
        if y[i].min() != y[i].max():
            bs.append(roc_auc_score(y[i], p[i]))
    return {"n": int(len(y)), "prevalence": round(float(y.mean()), 4), "roc_auc": round(float(roc_auc_score(y, p)), 4), "roc_auc_95ci": [round(float(np.quantile(bs, 0.025)), 4), round(float(np.quantile(bs, 0.975)), 4)],
            "pr_auc": round(float(average_precision_score(y, p)), 4)}


def demo_coverage(models: dict) -> dict:
    rm = TrainedRiskModel(models)
    codes: Counter = Counter()
    n = scored = 0
    for mk in SCENARIOS.values():
        for seed in range(5):
            b = mk(seed)
            rs = rm.score(b, b.subject_id, {})
            n += 1
            scored += rs.basis.startswith("trained:")
            for note in rs.meta.get("trained_models_considered", []):
                codes[f"{note['model'].split('_v')[0]}:{note['code']}"] += 1
    return {"scenarios": len(SCENARIOS), "cases": n, "scored_by_trained_model": scored, "abstention_codes": dict(codes),
            "reading": "Demo and synthetic bundles are refused by the domain gate (source/origin), so the heuristic is used and labelled as such."}


def _calib(y, p, bins: int = 10) -> dict:
    y, p = np.asarray(y, dtype=float), np.asarray(p, dtype=float)
    order = np.argsort(p)
    chunks = np.array_split(order, bins)
    ece = float(sum(len(c) / len(p) * abs(y[c].mean() - p[c].mean()) for c in chunks))
    return {"mean_predicted": round(float(p.mean()), 4), "observed_rate": round(float(y.mean()), 4), "ece": round(ece, 4), "brier": round(float(np.mean((p - y) ** 2)), 4),
            "brier_base_rate_forecast": round(float(np.mean((y.mean() - y) ** 2)), 4), "reliability_deciles": [{"n": int(len(c)), "pred": round(float(p[c].mean()), 4), "obs": round(float(y[c].mean()), 4)} for c in chunks]}


def _operating_points(y, p, thresholds: dict) -> dict:
    y, p = np.asarray(y), np.asarray(p)
    out = {}
    for name, thr in thresholds.items():
        flag = p >= thr
        tp = int((flag & (y == 1)).sum())
        out[name] = {"threshold": round(float(thr), 4), "flag_rate": round(float(flag.mean()), 4), "precision": round(tp / max(int(flag.sum()), 1), 4), "recall": round(tp / max(int(y.sum()), 1), 4)}
    for k in (0.05, 0.10, 0.20):
        top = np.argsort(-p)[: max(1, int(len(p) * k))]
        out[f"top{int(k * 100)}%"] = {"precision": round(float(y[top].mean()), 4), "recall": round(float(y[top].sum() / max(y.sum(), 1)), 4), "lift": round(float(y[top].mean() / max(y.mean(), 1e-9)), 2)}
    return out


def lade_part(models: dict, n: int, seed: int = 0, agent_cases: int = 600) -> dict:
    from dallal.ml.adapters import ADAPTERS

    m = models["lade_slow_task_v1"]
    thr = float(m.card.extra["slow_threshold_min"])
    t0 = time.time()
    cases, stream = lade_replay(n, seed, 10.0, m.card.split["cuts"]["test_start"], thr)
    rm = TrainedRiskModel({"lade_slow_task_v1": m})
    store = rm._store("lade_slow_task_v1", m)  # builds the point-in-time store (cold start cost is reported)
    cold = time.time() - t0
    heur = HeuristicRiskModel()
    ad = ADAPTERS["lade_slow_task_v1"]
    recs, lat = [], []
    for _, r in cases.iterrows():
        b = lade_bundle(r)
        t1 = time.perf_counter()
        rs = rm.score(b, b.subject_id, {})
        lat.append((time.perf_counter() - t1) * 1000)
        o = ad.build(b, b.subject_id, m.card, store)
        note = rs.meta["trained_models_considered"][0]
        forced = float(m.calibrator(m.raw(m._frame(o.features)))[0]) if o.ok else None
        oor = note.get("features_outside_training_range", [])
        recs.append({"slow": int(r["slow"]), "row": int(r["_row"]), "code": note["code"], "p": rs.probability if rs.basis.startswith("trained:") else None, "forced": forced, "oor": oor,
                     "band": rs.band if rs.basis.startswith("trained:") else None, "h": heur.score(b, b.subject_id, {}).score})
    df = pd.DataFrame(recs)
    sc = df[df.p.notna()]
    ab = df[df.p.isna() & df.forced.notna()]
    thresholds = {"elevated_band": m.card.band_thresholds["elevated"], "high_band": m.card.band_thresholds["high"]}
    out = {"cases": int(len(df)), "as_of": "accept + 10 min, held-out TEST window only", "latency_ms": {"p50": round(float(np.percentile(lat, 50)), 2), "p95": round(float(np.percentile(lat, 95)), 2), "mean": round(float(np.mean(lat)), 2),
                                                                                                         "cold_store_build_s": round(cold, 1)},
           "abstention_codes": df.code.value_counts().to_dict(), "coverage": round(float(len(sc) / len(df)), 3), "features_outside_range_when_abstaining": dict(Counter(f for l_ in df.oor for f in l_)),
           "trained_model_via_bridge": _auc(sc.slow, sc.p), "heuristic_same_cases": _auc(sc.slow, sc.h), "heuristic_distinct_scores": int(df.h.nunique()),
           "forced_scores_on_abstained_cases_if_range_check_were_off": _auc(ab.slow, ab.forced) if len(ab) else None, "calibration_on_replay": _calib(sc.slow, sc.p),
           "operating_points": _operating_points(sc.slow, sc.p, thresholds)}
    # train/serve parity: bridged features vs the training-time frame built from the full stream
    full = F.lade_frame("sh", sample=None)
    cols = m.feature_names
    diffs = {c: 0.0 for c in cols}
    exact = cmp_n = 0
    for _, r in cases.head(400).iterrows():
        b = lade_bundle(r)
        o = ad.build(b, b.subject_id, m.card, store)
        if not o.ok:
            continue
        ref = full.iloc[int(r["_row"])]
        cmp_n += 1
        d = {c: abs(o.features[c] - float(ref[c])) for c in cols}
        exact += all(v < 1e-6 for v in d.values())
        for c in cols:
            diffs[c] = max(diffs[c], d[c])
    out["parity_vs_training_frame"] = {"compared": cmp_n, "rows_identical_within_1e-6": exact, "max_abs_diff_per_feature": {c: round(v, 8) for c, v in diffs.items()}}
    # point in time: a store that has never seen anything accepted after T gives the same features for every case before T
    T = cases["as_of_ts"].median()
    trunc = LadeStore(stream[stream["as_of_ts"] <= T], m.card.extra["history_prior_logdur"], m.card.extra["history_prior_n"], m.card.extra.get("history_keys"))
    bad = chk = 0
    for _, r in cases[cases["as_of_ts"] <= T].head(300).iterrows():
        t = pd.Timestamp(r["as_of_ts"])
        a_ = (store.open_tasks(r["courier_id"], t), store.past_mean_logdur("aoi", r["dest_zone_id"], t), store.past_mean_logdur("courier", r["courier_id"], t))
        b_ = (trunc.open_tasks(r["courier_id"], t), trunc.past_mean_logdur("aoi", r["dest_zone_id"], t), trunc.past_mean_logdur("courier", r["courier_id"], t))
        chk += 1
        bad += a_ != b_
    out["point_in_time_check"] = {"cases_checked": chk, "feature_mismatches_when_future_rows_removed": int(bad)}
    # end to end through the agent (screening trigger): model-backed vs heuristic-backed agent on the same real cases
    rows = []
    for _, r in cases.head(agent_cases).iterrows():
        for label, risk in (("model", rm), ("heuristic", heur)):
            res = AgentRuntimeV2(mode="no_inquiry", providers=DefaultProviders(risk=risk)).start(lade_bundle(r))
            call = next((c for c in res.state.calls if c.tool == "predict_risk"), None)
            rk = ((getattr(call, "data", None) or {}).get("risk") or {}) if call else {}
            watch = bool(res.run.decision.get("watch"))
            rows.append({"agent": label, "slow": int(r["slow"]), "called": call is not None, "source": rk.get("source"), "band": rk.get("band"), "decision": res.run.decision["type"], "watch": watch,
                         "n_steps": len(res.run.steps)})
    ad_df = pd.DataFrame(rows)
    ag = {}
    for label in ("model", "heuristic"):
        d = ad_df[ad_df.agent == label]
        flagged = d[(d.decision != "resolved") | d.watch]
        ag[label] = {"runs": int(len(d)), "called_predict_risk": int(d.called.sum()), "risk_source": d.source.value_counts(dropna=False).to_dict(), "decisions": d.decision.value_counts().to_dict(), "watch_flags": int(d.watch.sum()), "band_distribution": d.band.value_counts(dropna=False).to_dict(),
                     "flag_rate": round(float(len(flagged) / len(d)), 3), "precision_of_flagged": round(float(flagged.slow.mean()), 3) if len(flagged) else None,
                     "recall_of_slow": round(float(flagged.slow.sum() / max(d.slow.sum(), 1)), 3), "base_rate": round(float(d.slow.mean()), 3)}
    out["agent_end_to_end"] = ag
    return out


def amazon_part(models: dict, n_routes: int = 120, seed: int = 0) -> dict:
    m = models["amazon_failed_attempt_v1"]
    base = PATHS.canonical / "amazon_lmrrc"
    ship, rt, st, lab = (pd.read_parquet(base / f"{t}.training.parquet") for t in ("shipment", "route", "stop", "label"))
    test_day = m.card.split["cuts"]["test_start"]
    rt = rt[rt["day_index"] >= test_day]
    pick = rt.sample(min(n_routes, len(rt)), random_state=seed)
    y_map = lab.set_index("entity_id")["value"]
    rm = TrainedRiskModel({"amazon_failed_attempt_v1": m})
    recs = []
    full = F.amazon_frame().set_index("_sid")
    cols = m.feature_names
    maxdiff = {c: 0.0 for c in cols}
    for _, r in pick.iterrows():
        ships = ship[ship["route_id"] == r["route_id"]]
        stops = st[st["route_id"] == r["route_id"]]
        dep = pd.Timestamp(r["planned_departure_ts"])
        b = Bundle(f"amazon-replay:{r['route_id']}", dep, "", {"kind": "route_plan"}, {"shipment": ships, "route": pd.DataFrame([r]), "stop": stops})
        from dallal.ml.adapters import ADAPTERS

        for _, s in ships.iterrows():
            o = ADAPTERS["amazon_failed_attempt_v1"].build(Bundle(b.scenario_id, dep, s["shipment_id"], {}, b.tables), s["shipment_id"], m.card, rm._store("amazon_failed_attempt_v1", m))
            if not o.ok:
                recs.append({"code": o.code, "y": int(y_map[s["shipment_id"]]), "p": None})
                continue
            for c in cols:
                maxdiff[c] = max(maxdiff[c], abs(o.features[c] - float(full.loc[s["shipment_id"], c])))
            pr = m.predict(o.features)
            recs.append({"code": "ok" if pr else "out_of_training_range", "y": int(y_map[s["shipment_id"]]), "p": None if pr is None else pr.probability})
    df = pd.DataFrame(recs)
    sc = df[df.p.notna()]
    return {"routes": int(len(pick)), "packages": int(len(df)), "coverage": round(float(len(sc) / len(df)), 4), "abstention_codes": df.code.value_counts().to_dict(),
            "trained_model_via_bridge": _auc(sc.y, sc.p), "max_abs_feature_diff_vs_training_frame": {c: round(v, 6) for c, v in maxdiff.items()}}


def latency_clean(models: dict, n: int = 600) -> dict:
    """Per-case inference latency on an IDLE machine: bridge (feature build + point-in-time store) + calibrated prediction, warm store; and predict-only."""
    m = models["lade_slow_task_v1"]
    cases, _ = lade_replay(n, 1, 10.0, m.card.split["cuts"]["test_start"], m.card.extra["slow_threshold_min"])
    rm = TrainedRiskModel({"lade_slow_task_v1": m})
    rm._store("lade_slow_task_v1", m)
    bundles = [lade_bundle(r) for _, r in cases.iterrows()]
    lat = []
    for b in bundles:
        t = time.perf_counter()
        rm.score(b, b.subject_id, {})
        lat.append((time.perf_counter() - t) * 1000)
    from dallal.ml.adapters import ADAPTERS

    feats = [ADAPTERS["lade_slow_task_v1"].build(b, b.subject_id, m.card, rm._store("lade_slow_task_v1", m)).features for b in bundles[:200]]
    feats = [f for f in feats if f]
    t = time.perf_counter()
    for f in feats:
        m.predict(f)
    pred_ms = (time.perf_counter() - t) * 1000 / max(len(feats), 1)
    return {"cases": n, "bridge_plus_predict_ms": {"p50": round(float(np.percentile(lat, 50)), 2), "p95": round(float(np.percentile(lat, 95)), 2), "p99": round(float(np.percentile(lat, 99)), 2), "mean": round(float(np.mean(lat)), 2)},
            "predict_only_ms_mean": round(pred_ms, 3), "note": "measured with nothing else running; adapter + calibrated model only (no agent runtime, no HTTP)"}


def main() -> None:
    models = {i: registry.load(i) for i in registry.available()}
    rep = {"generated": pd.Timestamp.now().isoformat(timespec="seconds"), "origin": "real public data replays (LaDe, Amazon) + synthetic demo scenarios", "demo_scenarios": demo_coverage(models),
           "lade_replay": lade_part(models, 2000), "amazon_replay": amazon_part(models)}
    rep["latency_idle_machine"] = latency_clean(models)
    (PATHS.docs / "experiments").mkdir(parents=True, exist_ok=True)
    (PATHS.docs / "experiments" / "model_bridge.json").write_text(json.dumps(rep, indent=2, default=str) + "\n")
    print(json.dumps(rep, indent=1, default=str)[:4000])


if __name__ == "__main__":
    main()
