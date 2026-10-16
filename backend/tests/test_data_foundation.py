from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from dallal.config import PATHS
from dallal.data import leakage, splits
from dallal.data.registry import load_registry
from dallal.data.schema import SchemaViolation, validate_frame

PROV = dict(origin="observed", source_id="t", source_record_id=None, adapter_version="v", scenario_id=None, generator_seed=None)


def _shipments(n=3, **over):
    df = pd.DataFrame({"shipment_id": [f"t:{i}" for i in range(n)], **PROV})
    for k, v in over.items():
        df[k] = v
    return df


# ── registry ────────────────────────────────────────────────────────────────
def test_registry_valid_and_decisions_complete():
    reg = load_registry()
    assert {d.decision for d in reg.datasets} == {"select", "secondary", "reject"}
    for d in reg.by_decision("select"):
        assert d.license and d.redistribution and d.evidence_level == "data"
    for d in reg.by_decision("reject"):
        assert d.reason and not d.files


def test_lock_covers_every_registry_file():
    import json

    lock = json.loads(PATHS.lock.read_text())
    for d in load_registry().datasets:
        for f in d.files:
            assert f"{d.id}/{f.name}" in lock, f"{d.id}/{f.name} missing from lock"


# ── schema contract ─────────────────────────────────────────────────────────
def test_duplicate_key_rejected():
    df = _shipments(2)
    df.loc[1, "shipment_id"] = df.loc[0, "shipment_id"]
    with pytest.raises(SchemaViolation, match="duplicate"):
        validate_frame("shipment", df)


def test_unknown_column_rejected():
    with pytest.raises(SchemaViolation, match="unknown"):
        validate_frame("shipment", _shipments().assign(mystery=1))


def test_enum_domain_enforced():
    ev = pd.DataFrame({"event_id": ["e"], "shipment_id": ["s"], "event_type": ["teleported"], "ts_quality": ["exact"], **PROV})
    with pytest.raises(SchemaViolation, match="enum"):
        validate_frame("event", ev)


def test_adapter_provides_contract_blocks_undeclared_fill():
    df = _shipments(value=[1.0, 2.0, 3.0])
    validate_frame("shipment", df, provides={"value"})
    with pytest.raises(SchemaViolation, match="not declared"):
        validate_frame("shipment", df, provides={"cod_amount"})


def test_synthetic_requires_scenario_and_observed_forbids_it():
    syn = _shipments().assign(origin="synthetic")
    with pytest.raises(SchemaViolation, match="scenario_id"):
        validate_frame("shipment", syn)
    obs = _shipments().assign(scenario_id="x")
    with pytest.raises(SchemaViolation, match="must not carry"):
        validate_frame("shipment", obs)


def _label(as_of, avail):
    return pd.DataFrame({"label_id": ["l"], "task": ["t"], "entity_type": ["shipment"], "entity_id": ["s"], "value": [1.0],
                         "as_of_ts": [pd.Timestamp(as_of)], "available_at_ts": [pd.Timestamp(avail)], "as_of_day_index": [pd.NA],
                         "available_at_day_index": [pd.NA], "definition": "d", **PROV, "origin": "engineered"})


def test_label_must_resolve_after_prediction():
    validate_frame("label", _label("2024-01-01", "2024-01-02"))
    with pytest.raises(SchemaViolation, match="after as_of"):
        validate_frame("label", _label("2024-01-02", "2024-01-02"))


def test_randomized_action_requires_propensity():
    a = pd.DataFrame({"action_id": ["a"], "subject_type": ["shipment"], "subject_id": ["s"], "kind": ["verify_address"],
                      "assignment": ["randomized"], "propensity": [np.nan], **PROV, "origin": "synthetic", "scenario_id": "x"})
    with pytest.raises(SchemaViolation, match="propensity"):
        validate_frame("action", a)


# ── leakage guards ──────────────────────────────────────────────────────────
def test_banned_columns_detected():
    f = pd.DataFrame({"distance_km": [1], "review_score": [5], "my_label_copy": [1]})
    with pytest.raises(leakage.LeakageError):
        leakage.assert_features_clean("olist_late_delivery_at_handoff", f)
    leakage.assert_features_clean("olist_late_delivery_at_handoff", f[["distance_km"]])


def test_visible_events_respects_prediction_instant():
    ev = pd.DataFrame({"ts": pd.to_datetime(["2024-01-01 10:00", "2024-01-01 12:00", None, None]), "day_index": [0, 0, 0, 3]})
    out = leakage.visible_events(ev, as_of_ts=pd.Timestamp("2024-01-01 11:00"), as_of_day=1)
    assert list(out.index) == [0, 2]  # untimed same-prediction-day events (idx 3 is day 3) excluded; day 0 < 1 included
    with pytest.raises(ValueError):
        leakage.visible_events(ev, as_of_ts=pd.Timestamp("2024-01-01"))  # untimed rows but no as_of_day


def test_label_proxy_guard_catches_a_renamed_label():
    rng = np.random.default_rng(0)
    y = (rng.random(2000) < 0.1).astype(int)
    honest = pd.DataFrame({"noise": rng.normal(size=2000), "weak": y * 0.3 + rng.normal(size=2000)})
    leakage.assert_no_label_proxy(honest, y)
    with pytest.raises(leakage.LeakageError, match="label in disguise"):
        leakage.assert_no_label_proxy(honest.assign(value=y), y)  # the exact Olist merge-collision failure mode


def test_past_stat_never_sees_its_own_or_future_outcomes():
    from dallal.ml.features import past_stat

    k = pd.Series(["a"] * 4)
    as_of = pd.Series([10, 20, 30, 40])
    avail = pd.Series([15, 25, 35, 45])  # each outcome resolves 5 units after its own prediction
    v = pd.Series([1.0, 0.0, 1.0, 1.0])
    m, c = past_stat(k, as_of, avail, v, prior=0.5, prior_n=1.0)
    assert list(c) == [0, 1, 2, 3]  # row i sees exactly the outcomes resolved before its as_of
    expected = [(0 + 0.5) / 1, (1 + 0.5) / 2, (1 + 0 + 0.5) / 3, (1 + 0 + 1 + 0.5) / 4]
    assert list(m) == pytest.approx(expected)
    # flipping a row's OWN or a LATER outcome must not change its feature
    v2 = v.copy()
    v2[2] = 0.0
    m2, _ = past_stat(k, as_of, avail, v2, prior=0.5, prior_n=1.0)
    assert m2[2] == m[2] and m2[0] == m[0] and m2[1] == m[1]


def test_history_rate_uses_only_the_past():
    df = pd.DataFrame({"zone": ["a"] * 4, "day": [1, 2, 3, 4], "y": [1, 1, 0, 1]})
    r = leakage.history_rate(df, "zone", "y", "day", as_of_day=3, prior=0.0, prior_n=0.0)
    assert r["a"] == 1.0  # days 1,2 only; the day-4 positive and day-3 negative are invisible


# ── splits ──────────────────────────────────────────────────────────────────
def test_time_split_is_chronological_with_embargo():
    df = pd.DataFrame({"day": np.arange(100), "origin": "observed"})
    s = splits.time_split(df, "day", embargo=3)
    assert df.day.iloc[s.train].max() < df.day.iloc[s.valid].min() - 2
    assert df.day.iloc[s.valid].max() < df.day.iloc[s.test].min() - 2


def test_synthetic_rows_cannot_enter_heldout():
    df = pd.DataFrame({"day": np.arange(100), "origin": "observed"})
    df.loc[95, "origin"] = "synthetic"
    with pytest.raises(splits.SplitError, match="non-observed"):
        splits.time_split(df, "day")


def test_sparse_period_drop():
    df = pd.DataFrame({"m": ["a"] * 5 + ["b"] * 1})
    assert set(splits.drop_sparse_periods(df, "m", 3).m) == {"a"}


# ── real data (skipped when not downloaded/built) ───────────────────────────
real = pytest.mark.skipif(not (PATHS.canonical / "amazon_lmrrc" / "attempt.training.parquet").exists(), reason="canonical data not built")


@real
@pytest.mark.realdata
def test_amazon_repeated_attempts_preserved():
    att = pd.read_parquet(PATHS.canonical / "amazon_lmrrc" / "attempt.training.parquet")
    sh = pd.read_parquet(PATHS.canonical / "amazon_lmrrc" / "shipment.training.parquet", columns=["shipment_id"])
    assert sh.shipment_id.is_unique
    assert (att.groupby("shipment_id").size() > 1).sum() > 1000
    assert "failure_reason" not in att or att["failure_reason"].isna().all(), "Amazon states no failure reason"


@real
@pytest.mark.realdata
def test_real_labels_respect_leakage_rule():
    for rel in ("olist/label.parquet", "amazon_lmrrc/label.training.parquet", "route_deviation/label.parquet"):
        leakage.assert_label_after_features(pd.read_parquet(PATHS.canonical / rel))


@real
@pytest.mark.realdata
def test_lade_has_no_failure_outcomes():
    ev = pd.read_parquet(PATHS.canonical / "lade" / "event.delivery_jl.parquet", columns=["event_type"])
    assert set(ev.event_type) == {"accepted", "delivered"}


@real
@pytest.mark.realdata
def test_synthetic_ocel_is_tagged():
    sh = pd.read_parquet(PATHS.canonical / "ocel_order_management" / "shipment.parquet")
    assert (sh.origin == "synthetic").all() and sh.scenario_id.notna().all()
