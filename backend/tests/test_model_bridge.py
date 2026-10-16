"""The model bridge: domain gate, point-in-time correctness, coded abstention, honest labelling. Synthetic data only (no datasets needed)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from dallal.agent.v2.state import CaseStateV2
from dallal.data.augment.scenarios import SCENARIOS
from dallal.ml import registry
from dallal.ml.adapters import LadeSlowTaskAdapter
from dallal.ml.pit import LadeStore, NullStore
from dallal.ml.risk import TrainedRiskModel
from dallal.tools.base import ToolContext
from dallal.tools.builtin import build_registry
from dallal.tools.bundle import Bundle
from dallal.tools.providers import DefaultProviders, HeuristicRiskModel

T0 = pd.Timestamp("2000-06-04 11:00")
FEATS = ["hour", "dow", "aoi_type", "open_tasks_courier", "accept_dist_m", "aoi_past_logdur", "aoi_past_n", "courier_past_logdur", "courier_past_n", "region_past_logdur", "region_past_n"]


def _stream(extra: list[dict] | None = None) -> pd.DataFrame:
    """A small task stream: courier C1 / AOI A1 / region R1; durations in minutes; as_of = accept time, available_at = completion."""
    rows = []
    for i, (acc_h, dur) in enumerate([(-30, 60), (-20, 120), (-10, 90), (-3, 400), (-1.5, 30)]):  # -3h task is still open at T0; -1.5h task too
        acc = T0 + pd.Timedelta(hours=acc_h)
        rows.append({"shipment_id": f"s{i}", "courier_id": "C1", "dest_zone_id": "A1", "dest_region": "R1", "as_of_ts": acc, "available_at_ts": acc + pd.Timedelta(minutes=dur), "log_dur": np.log1p(dur)})
    rows += extra or []
    return pd.DataFrame(rows)


def _toy_model(domains=("lade",)) -> registry.TrainedModel:
    rng = np.random.default_rng(0)
    x = pd.DataFrame({f: rng.uniform(0, 10, 500) for f in FEATS})
    y = (rng.uniform(size=500) < 0.2).astype(int)
    est = LogisticRegression().fit(x, y)
    raw = est.predict_proba(x)[:, 1]
    cal = registry.Calibrator.fit("platt", raw, y)
    p = cal(raw)
    card = registry.ModelCard("lade_slow_task_v1", "t", "slow task", "toy", "n/a", "task", "accept", "logreg", "platt", [registry.FeatureSpec(f, -1e6, 1e6) for f in FEATS], {}, {"test": {"roc_auc": 0.8}}, {},
                              0.2, 0.2, {"elevated": float(np.quantile(p, .85)), "high": float(np.quantile(p, .95))}, [], "t", valid_domains=list(domains),
                              extra={"slow_threshold_min": 216.0, "history_prior_logdur": 4.0, "history_prior_n": 10.0})
    return registry.TrainedModel(est, cal, card)


def _bundle(origin="observed", source="lade", as_of=T0, with_accept=True, delivered=False, acc_ts=None) -> Bundle:
    acc_ts = acc_ts or (T0 - pd.Timedelta(minutes=10))
    ship = pd.DataFrame([{"shipment_id": "X", "courier_id": "C1", "dest_lat": 31.0, "dest_lng": 121.0, "dest_zone_id": "A1", "dest_zone_type": 3, "dest_region": "R1", "origin": origin, "source_id": source}])
    ev = []
    if with_accept:
        ev.append({"shipment_id": "X", "event_type": "accepted", "ts": acc_ts, "lat": 31.001, "lng": 121.001})
    if delivered:
        ev.append({"shipment_id": "X", "event_type": "delivered", "ts": as_of - pd.Timedelta(minutes=1)})
    return Bundle("t", as_of, "X", {}, {"shipment": ship, "event": pd.DataFrame(ev) if ev else pd.DataFrame(columns=["shipment_id", "event_type", "ts"])})


def _stream_with_case() -> pd.DataFrame:
    acc = T0 - pd.Timedelta(minutes=10)  # the case task itself is in the store, as it would be in an operational DB
    return _stream([{"shipment_id": "X", "courier_id": "C1", "dest_zone_id": "A1", "dest_region": "R1", "as_of_ts": acc, "available_at_ts": acc + pd.Timedelta(minutes=500), "log_dur": np.log1p(500)}])


def _store(stream=None) -> LadeStore:
    return LadeStore(stream if stream is not None else _stream_with_case(), prior=4.0, prior_n=10.0)


def build(bundle, store=None, model=None):
    m = model or _toy_model()
    return LadeSlowTaskAdapter().build(bundle, "X", m.card, store or _store())


def test_features_are_computed_as_of_acceptance_from_the_store():
    o = build(_bundle())
    assert o.ok and o.as_of_used == (T0 - pd.Timedelta(minutes=10)).isoformat()
    f = o.features
    assert f["hour"] == 10.0 and f["aoi_type"] == 3.0 and f["accept_dist_m"] == pytest.approx(140, abs=10)
    # at t = 10:50 the courier had accepted s0..s4 and X; s0, s1, s2 and s4 were already done; X is the case itself -> only s3 (done 14:40) is open
    assert f["open_tasks_courier"] == 1.0
    # history resolved strictly before t: s0, s1, s2 and s4 (done 10:00); s3 completes later and X is the case itself
    assert f["aoi_past_n"] == 4.0
    exp = (np.log1p(60) + np.log1p(120) + np.log1p(90) + np.log1p(30) + 4.0 * 10) / (4 + 10)
    assert f["aoi_past_logdur"] == pytest.approx(exp)


def test_no_look_ahead_future_rows_cannot_change_features():
    base = build(_bundle()).features
    future = [{"shipment_id": f"f{i}", "courier_id": "C1", "dest_zone_id": "A1", "dest_region": "R1", "as_of_ts": T0 + pd.Timedelta(hours=1 + i), "available_at_ts": T0 + pd.Timedelta(hours=2 + i), "log_dur": 9.0} for i in range(5)]
    s2 = _stream_with_case()
    s2 = pd.concat([s2, pd.DataFrame(future)], ignore_index=True)
    assert build(_bundle(), _store(s2)).features == base  # tasks accepted/resolved after t are invisible
    # a task that completed BEFORE acceptance does change history (legitimate information)
    early = [{"shipment_id": "e", "courier_id": "C1", "dest_zone_id": "A1", "dest_region": "R1", "as_of_ts": T0 - pd.Timedelta(hours=3), "available_at_ts": T0 - pd.Timedelta(hours=2), "log_dur": 5.0}]
    assert build(_bundle(), _store(pd.concat([_stream_with_case(), pd.DataFrame(early)], ignore_index=True))).features["aoi_past_n"] == base["aoi_past_n"] + 1


@pytest.mark.parametrize("kw,code", [
    (dict(origin="demo"), "domain_mismatch"), (dict(origin="synthetic"), "domain_mismatch"), (dict(source="dallal-demo"), "domain_mismatch"),
    (dict(with_accept=False), "missing_input"), (dict(delivered=True), "target_known"),
    (dict(acc_ts=T0 - pd.Timedelta(minutes=300)), "target_decided"),
])
def test_coded_abstentions(kw, code):
    o = build(_bundle(**kw))
    assert not o.ok and o.code == code and o.detail


def test_missing_history_store_and_unknown_courier_abstain():
    assert build(_bundle(), NullStore()).code == "no_point_in_time_store"
    st = LadeStore(_stream_with_case().assign(courier_id="OTHER"), prior=4.0)
    assert build(_bundle(), st).code == "missing_input"


def test_model_without_domains_is_never_auto_scored():
    o = LadeSlowTaskAdapter().build(_bundle(), "X", _toy_model(domains=()).card, _store())
    assert o.code == "not_bridged"


def test_provider_labels_model_vs_heuristic_and_records_why():
    m = _toy_model()
    rm = TrainedRiskModel({"lade_slow_task_v1": m}, HeuristicRiskModel(), {"lade_slow_task_v1": _store()})
    good = rm.score(_bundle(), "X", {})
    assert good.basis == "trained:lade_slow_task_v1" and good.meta["source"] == "model" and good.meta["features_as_of"] and "heuristic_for_comparison" in good.meta
    demo = SCENARIOS["healthy"](3)
    fb = rm.score(demo, demo.subject_id, {})
    assert fb.basis == "prototype-heuristic" and fb.meta["source"] == "heuristic" and fb.meta["trained_models_considered"][0]["code"] == "domain_mismatch"
    assert "abstained" in fb.meta["why_heuristic"]


def test_tool_result_says_model_or_heuristic_in_plain_words():
    reg = build_registry()
    m = _toy_model()
    for bundle, prov, word in ((_bundle(), TrainedRiskModel({"lade_slow_task_v1": m}, HeuristicRiskModel(), {"lade_slow_task_v1": _store()}), "MODEL"),
                               (SCENARIOS["healthy"](3), TrainedRiskModel({"lade_slow_task_v1": m}), "HEURISTIC")):
        st = CaseStateV2(bundle.subject_id, {}, bundle.as_of)
        st.facts = {}
        res = reg["predict_risk"].fn(ToolContext(bundle, st, DefaultProviders(risk=prov)), {})
        assert any(line.startswith(word) for line in res.facts) and res.data["risk"]["source"] == word.lower()
