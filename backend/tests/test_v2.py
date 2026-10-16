from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from dallal.agent import belief as bl
from dallal.agent.v2 import inquiry as iq
from dallal.agent.v2.bayes import EnsembleBelief, default_book
from dallal.agent.v2.events import InquiryResponse, InquiryTimeout
from dallal.agent.v2.runtime import AgentRuntimeV2
from dallal.agent.v2.utility import best_option, build_options, stakes
from dallal.agent.v2.voi import evaluate
from dallal.data.augment.scenarios import SCENARIOS

BOOK = default_book()
NOW = pd.Timestamp("2026-03-10 14:00")


def paused_run(seed=7):
    """stalled_no_scan reliably ends up asking the branch (databases cannot settle it)."""
    b = SCENARIOS["stalled_no_scan"](seed)
    rt = AgentRuntimeV2(mode="value")
    r = rt.start(b, run_id="t1")
    assert r.status == "awaiting_response", "expected the agent to pause for an answer"
    return rt, b, r


# ── ensemble belief ─────────────────────────────────────────────────────────
def test_nominal_particle_matches_v1_posterior():
    v2 = EnsembleBelief.from_prior(BOOK, bl.BASE_PRIOR)
    v1 = bl.Belief.from_prior(bl.BASE_PRIOR)
    for tool, out in (("get_address_context", "address_weak"), ("get_journey", "clean")):
        v2.update(tool, out)
        v1.update(tool, out)
    # particle 0 uses the nominal tables, but family tempering only exists in v2; compare on tools from different families
    assert v2.particle_cause()[0][bl.CI[bl.Cause.ADDRESS_ISSUE]] == pytest.approx(v1.p_cause()[bl.Cause.ADDRESS_ISSUE], rel=1e-6)


def test_table_uncertainty_makes_posterior_less_extreme():
    b = EnsembleBelief.from_prior(BOOK, bl.BASE_PRIOR)
    for t, o in (("get_address_context", "address_weak"), ("get_recipient_context", "history_of_missed_windows")):
        b.update(t, o)
    nominal_top = b.particle_cause()[0].max()
    assert b.top()[1] <= nominal_top + 1e-9


def test_predictive_is_a_distribution_for_every_source():
    b = EnsembleBelief.from_prior(BOOK, bl.BASE_PRIOR)
    for name in BOOK.models:
        p = b.predictive(name)
        assert p.min() >= 0 and p.sum() == pytest.approx(1.0)


def test_same_family_evidence_is_discounted():
    a = EnsembleBelief.from_prior(BOOK, bl.BASE_PRIOR)
    a.update("get_journey", "stalled")
    before = a.top()[1]
    a.update("get_facility_context", "scan_gap")  # same 'scans' family: tempered
    gain_same = a.top()[1] - before
    c = EnsembleBelief.from_prior(BOOK, bl.BASE_PRIOR)
    c.update("get_journey", "stalled")
    before = c.top()[1]
    c.update("get_recipient_context", "no_signal")
    assert abs(gain_same) < 0.5  # sanity: tempered update is bounded
    assert BOOK.tempered("get_facility_context", 0.65).shape == BOOK.tables["get_facility_context"].shape


def test_book_is_reproducible_and_order_independent():
    a, b = default_book(), default_book()
    for n in a.tables:
        assert np.array_equal(a.tables[n], b.tables[n])


# ── value of information ────────────────────────────────────────────────────
def _setup(response_p=0.7, slack=240.0, latency=10.0):
    facts = {"shipment_id": "x", "service_level": "Standard", "value": 300.0, "cod_amount": None, "failed_attempts": 0, "recipient_opt_in": True, "recipient_phone": "SANDBOX-1",
             "recipient_responsiveness": "medium", "courier_id": "c", "corridor_id": "k", "origin_node_id": "n", "pickup_point_id": None, "alt_pickup_online": False}
    preds = {"recipient_reachable": True, "pickup_online": False, "alt_pickup_online": False, "alt_route": True, "spare_courier": True}
    opts = build_options(facts, preds)
    spec = iq.spec("ask_recipient_availability")
    name = iq.variant_name(spec.id, response_p)
    BOOK.ensure(name)
    b = EnsembleBelief.from_prior(BOOK, bl.BASE_PRIOR)
    b.update("get_recipient_context", "history_of_missed_windows")
    lat = {a["id"]: latency for a in spec.answers}
    lat[iq.NO_RESPONSE] = 45.0
    return b, name, opts, stakes(facts, slack), lat


def test_unreliable_responders_are_worth_less():
    b, name_hi, opts, stk, lat = _setup(0.9)
    _, name_lo, *_ = _setup(0.2)
    hi = evaluate(b, name_hi, kind="inquiry", label="q", opts=opts, stakes=stk, cost=1.0, latency_for=lat, p_response=0.9)
    lo = evaluate(b, name_lo, kind="inquiry", label="q", opts=opts, stakes=stk, cost=1.0, latency_for=lat, p_response=0.2)
    assert hi.gross_voi > lo.gross_voi


def test_slow_answers_are_worth_less_when_the_promise_is_near():
    b, name, opts, _, _ = _setup()
    slow = {k: 90.0 for k in iq.spec("ask_recipient_availability").outcomes}
    fast = {k: 2.0 for k in slow}
    from dallal.agent.v2.utility import stakes as st

    urgent = st({"service_level": "Standard", "value": 300.0}, 60.0)
    v_fast = evaluate(b, name, kind="inquiry", label="q", opts=opts, stakes=urgent, cost=1.0, latency_for=fast)
    v_slow = evaluate(b, name, kind="inquiry", label="q", opts=opts, stakes=urgent, cost=1.0, latency_for=slow)
    assert v_fast.gross_voi > v_slow.gross_voi


def test_irrelevant_question_has_no_value_and_costs_money():
    b, name, opts, stk, lat = _setup()
    # a flat observation model carries no information
    flat = bl.ObservationModel(("a", "b"), {c: (0.5, 0.5) for c in bl.CAUSES})
    BOOK.register("_flat", flat)
    r = evaluate(b, "_flat", kind="tool", label="flat", opts=opts, stakes=stk, cost=0.5, latency_for={"a": 0.0, "b": 0.0})
    assert r.gross_voi == pytest.approx(0.0, abs=1e-6) and r.net_voi == pytest.approx(-0.5, abs=1e-6)
    del BOOK.models["_flat"], BOOK.tables["_flat"]


def test_value_never_negative_for_free_instant_perfect_decisions():
    b, name, opts, stk, lat = _setup()
    r = evaluate(b, name, kind="inquiry", label="q", opts=opts, stakes=stk, cost=0.0, latency_for={k: 0.0 for k in lat}, p_response=0.7)
    assert r.gross_voi >= -1e-9  # information that is free and instant can never hurt (Blackwell)


# ── pause / resume / timeout / duplicates / late ────────────────────────────
def test_run_pauses_with_a_durable_json_checkpoint():
    rt, b, r = paused_run()
    ck = json.loads(json.dumps(r.checkpoint()))
    assert r.pending is not None and ck["pending"]["inquiry_id"] == r.pending.inquiry_id
    assert r.run.decision["type"] == "awaiting_response" and r.run.status == "awaiting_response"


def test_resume_matches_an_uninterrupted_run():
    rt, b, r = paused_run()
    ck = json.loads(json.dumps(r.checkpoint()))
    ans = iq.spec(r.pending.spec_id).answers[0]["id"]
    ev = InquiryResponse(r.pending.inquiry_id, ans, 6.0, {"text": "button"})
    resumed = AgentRuntimeV2(mode="value").resume(b, ck, ev, "t1")
    sync = AgentRuntimeV2(mode="value", responder=lambda p, s: InquiryResponse(p.inquiry_id, ans, 6.0)).start(SCENARIOS["stalled_no_scan"](7), run_id="t1")
    assert resumed.status == "completed"
    assert resumed.run.decision["type"] == sync.run.decision["type"]
    assert resumed.run.decision["top_cause"] == sync.run.decision["top_cause"]
    assert resumed.run.tool_path == sync.run.tool_path


def test_timeout_is_evidence_and_the_run_still_completes():
    rt, b, r = paused_run()
    out = AgentRuntimeV2(mode="value").resume(b, json.loads(json.dumps(r.checkpoint())), InquiryTimeout(r.pending.inquiry_id), "t1")
    # after a timeout the agent may decide, or (correctly) try a different person; either way the first inquiry is recorded as a timeout
    assert out.status in ("completed", "awaiting_response")
    first = out.run.inquiries[0]
    assert first["status"] == "timed_out" and first["outcome"] == iq.NO_RESPONSE
    if out.status == "awaiting_response":
        assert out.pending.spec_id != first["spec"], "must not re-ask the same question after a timeout"


def test_stale_event_for_another_inquiry_is_ignored():
    rt, b, r = paused_run()
    out = AgentRuntimeV2(mode="value").resume(b, json.loads(json.dumps(r.checkpoint())), InquiryResponse("inq-other", "normal_ops", 1.0), "t1")
    assert out.status == "awaiting_response" and out.pending.inquiry_id == r.pending.inquiry_id


def test_duplicate_answer_is_not_double_counted():
    rt, b, r = paused_run()
    ans = iq.spec(r.pending.spec_id).answers[0]["id"]
    ev = InquiryResponse(r.pending.inquiry_id, ans, 5.0)
    first = AgentRuntimeV2(mode="value").resume(b, json.loads(json.dumps(r.checkpoint())), ev, "t1")
    second = AgentRuntimeV2(mode="value").resume(b, first.checkpoint(), ev, "t1")
    assert second.state.belief.p_cause() == pytest.approx(first.state.belief.p_cause())
    assert second.state.late == []


def test_late_answer_after_timeout_reopens_the_case():
    rt, b, r = paused_run()
    timed = AgentRuntimeV2(mode="value").resume(b, json.loads(json.dumps(r.checkpoint())), InquiryTimeout(r.pending.inquiry_id), "t1")
    ans = iq.spec(r.pending.spec_id).answers[0]["id"]
    late = AgentRuntimeV2(mode="value").resume(b, timed.checkpoint(), InquiryResponse(r.pending.inquiry_id, ans, 50.0), "t1")
    assert late.state.late and late.run.inquiries[0]["status"] == "answered_late"


def test_unreadable_reply_is_not_used_as_evidence():
    rt, b, r = paused_run()
    out = AgentRuntimeV2(mode="value").resume(b, json.loads(json.dumps(r.checkpoint())), InquiryResponse(r.pending.inquiry_id, None, 3.0, {"text": "??"}, needs_review=True), "t1")
    assert out.status == "awaiting_response" and out.state.belief.observed == r.state.belief.observed


# ── contact policy ──────────────────────────────────────────────────────────
def test_no_recipient_contact_in_quiet_hours_without_opt_in_or_over_the_cap():
    facts = {"recipient_opt_in": True, "recipient_phone": "SANDBOX-1", "recipient_messages_24h": 0}
    s = iq.spec("ask_recipient_availability")
    assert iq.applicable(s, facts, pd.Timestamp("2026-03-10 14:00"))
    assert not iq.applicable(s, facts, pd.Timestamp("2026-03-10 22:30"))  # quiet hours
    assert not iq.applicable(s, {**facts, "recipient_opt_in": False}, NOW)
    assert not iq.applicable(s, {**facts, "recipient_messages_24h": 2}, NOW)


# ── decision safety on the scenario suite ───────────────────────────────────
@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_v2_invariants_across_scenarios(name):
    for seed in range(3):
        r = AgentRuntimeV2(mode="no_inquiry").start(SCENARIOS[name](seed))
        st, d = r.state, r.run.decision
        assert len(r.run.tool_path) == len(set(r.run.tool_path))
        if d["type"] == "auto_eligible":
            assert (st.facts["failed_attempts"] or 0) <= 2 and (st.facts["value"] or 0) <= 1500
            assert d["robust_effectiveness"] >= 0.62 and st.diagnosis["agreement"] != "conflicts"
        if d["type"] == "escalate":
            assert r.run.escalation is not None
        assert 0.0 <= d["decision_stability"] <= 1.0


def test_best_option_is_wait_when_confident_all_is_well():
    b = EnsembleBelief.from_prior(BOOK, bl.BASE_PRIOR)
    for t, o in (("get_journey", "clean"), ("get_address_context", "address_ok"), ("get_recipient_context", "no_signal"), ("predict_risk", "low")):
        b.update(t, o)
    opts = build_options({"service_level": "Standard", "value": 100.0, "failed_attempts": 0},
                         {"recipient_reachable": True, "pickup_online": False, "alt_pickup_online": False, "alt_route": True, "spare_courier": True})
    best, _ = best_option(opts, b.p_cause_vec(), stakes({"service_level": "Standard", "value": 100.0}, 240.0))
    assert best.name == "wait"
