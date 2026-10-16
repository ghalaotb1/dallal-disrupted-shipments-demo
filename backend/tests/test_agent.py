from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from dallal.agent import belief as bl
from dallal.agent.frontend import to_frontend
from dallal.agent.llm import LLMPlanner
from dallal.agent.runtime import AgentRuntime
from dallal.data.augment.scenarios import SCENARIOS
from dallal.data.schema import validate_frame
from dallal.tools.providers import DefaultProviders, RiskScore

rt = AgentRuntime()


def run(name, seed=7, runtime=None):
    return (runtime or rt).investigate(SCENARIOS[name](seed))


# ── belief machinery ────────────────────────────────────────────────────────
def test_observation_models_internally_consistent():
    bl.check_models()


def test_update_moves_belief_toward_supported_cause():
    b = bl.Belief.from_prior(bl.BASE_PRIOR)
    before = b.p_cause()[bl.Cause.ADDRESS_ISSUE]
    b.update("get_address_context", "address_weak")
    assert b.p_cause()[bl.Cause.ADDRESS_ISSUE] > before * 3


def test_information_gain_is_nonnegative_and_zero_for_uninformative_tool():
    b = bl.Belief.from_prior(bl.BASE_PRIOR)
    assert all(b.expected_information_gain(t) >= 0 for t in bl.OBSERVATION_MODELS)
    flat = bl.ObservationModel(("a", "b"), {c: (0.5, 0.5) for c in bl.CAUSES})
    bl.OBSERVATION_MODELS["_flat"] = flat
    try:
        assert b.expected_information_gain("_flat") == pytest.approx(0.0, abs=1e-9)
    finally:
        del bl.OBSERVATION_MODELS["_flat"]


def test_posterior_equals_bayes_by_hand():
    b = bl.Belief.from_prior(bl.BASE_PRIOR)
    prior_addr, prior_none = b.p_cause()[bl.Cause.ADDRESS_ISSUE], b.p_cause()[bl.Cause.NONE]
    b.update("get_address_context", "address_weak")
    L = bl.OBSERVATION_MODELS["get_address_context"].by_cause
    lr = (L[bl.Cause.ADDRESS_ISSUE][1] / sum(L[bl.Cause.ADDRESS_ISSUE])) / (L[bl.Cause.NONE][1] / sum(L[bl.Cause.NONE]))
    post = b.p_cause()
    assert post[bl.Cause.ADDRESS_ISSUE] / post[bl.Cause.NONE] == pytest.approx(prior_addr / prior_none * lr, rel=1e-6)


# ── the three headline cases behave differently ─────────────────────────────
def test_case_A_low_risk_proceeds_to_automation():
    r, st = run("address_risk")
    assert r.decision["type"] == "auto_eligible" and r.decision["action"] == "verify_address"
    assert "rank_recovery_actions" in r.tool_path and "retrieve_policy_constraints" in r.tool_path
    assert "check_incident_context" not in r.tool_path or r.decision["p_systemic"] < 0.1


def test_case_B_shared_root_cause_triggers_incident_reasoning():
    r, st = run("route_blockage")
    assert r.decision["type"] == "incident" and len(r.decision["members"]) >= 3
    assert "check_incident_context" in r.tool_path
    assert "rank_recovery_actions" not in r.tool_path, "incident-level handling must not be duplicated by per-parcel ranking"


def test_incident_scope_is_attributed_to_where_failures_concentrate():
    assert run("route_blockage")[0].decision["scope"] == "corridor"
    assert run("branch_backlog")[0].decision["scope"] == "facility"


def test_case_C_conflicting_evidence_escalates_instead_of_guessing():
    r, st = run("custody_conflict")
    assert r.decision["type"] == "escalate" and r.decision["reason"] == "conflicting_evidence"
    assert r.escalation and "delivered" in r.escalation["question"].lower()
    assert "rank_recovery_actions" not in r.tool_path


def test_paths_differ_across_cases():
    paths = {n: tuple(run(n)[0].tool_path) for n in ("address_risk", "route_blockage", "custody_conflict")}
    assert len(set(paths.values())) == 3


# ── context dependence (metamorphic) ────────────────────────────────────────
def test_removing_the_custody_conflict_removes_the_escalation_reason():
    base = SCENARIOS["custody_conflict"](7)
    ev = base.tables["event"]
    base.tables["event"] = ev[~((ev.shipment_id == base.subject_id) & (ev.event_type == "delivered"))]
    r, _ = rt.investigate(base)
    assert r.decision.get("reason") != "conflicting_evidence"


def test_better_address_flips_case_A_away_from_address_action():
    b = SCENARIOS["address_risk"](7)
    b.tables["address_context"].loc[:, ["confidence", "past_failures_at_address", "first_delivery_to_address"]] = [0.96, 0, False]
    r, _ = rt.investigate(b)
    assert r.decision["top_cause"] != "address_issue"


# ── safety invariants over a sweep ──────────────────────────────────────────
@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_invariants_hold_for_every_scenario(name):
    for seed in range(5):
        r, st = run(name, seed)
        f, d = st.facts, r.decision
        assert len(r.tool_path) == len(set(r.tool_path)), "tool repeated"
        if d["type"] == "auto_eligible":
            assert (f["failed_attempts"] or 0) <= 2 and (f["value"] or 0) <= 1500 and d["posterior"] >= 0.8
            assert st.diagnosis["agreement"] != "conflicts"
        if d["type"] == "escalate":
            assert r.escalation is not None
        if r.actions:
            assert "retrieve_policy_constraints" in r.tool_path, "autonomy gate skipped"


def test_investigation_budget_never_starves_the_policy_gate():
    r, _ = run("pickup_unavailable", runtime=AgentRuntime(budget=2))
    assert r.decision["type"] in ("recommend", "escalate")
    if r.actions:
        assert "retrieve_policy_constraints" in r.tool_path


def test_agent_cannot_see_events_after_as_of():
    b = SCENARIOS["healthy"](7)
    future = b.tables["event"].iloc[[0]].copy()
    future["event_id"] = "ev:future"
    future["event_type"] = "failed_attempt"
    future["ts"] = b.as_of + pd.Timedelta(hours=2)
    future["shipment_id"] = b.subject_id
    b.tables["event"] = pd.concat([b.tables["event"], future], ignore_index=True)
    r, st = rt.investigate(b)
    assert st.facts["failed_attempts"] == 0 and r.decision["type"] == "resolved"


# ── recovery honesty ────────────────────────────────────────────────────────
def test_ranking_makes_no_causal_claim_and_is_policy_bounded():
    r, st = run("repeated_failures")
    assert all(a["causal_claim"] is False and a["method"] == "evidence_weighted_policy_ranking" for a in r.actions)
    assert r.decision["action"] == "redirect_pickup", "after repeated failures, moving the parcel beats asking again"
    assert r.decision["type"] == "recommend"  # >2 prior failures: a human takes over


def test_high_value_conflict_is_escalated_not_automated():
    r, _ = run("courier_no_show")
    assert r.decision["type"] == "escalate" and r.decision["reason"] == "conflicting_evidence"


# ── provider swap: the agent does not change when the risk model does ───────
def test_risk_model_is_swappable_without_touching_the_agent():
    class AlarmistModel:
        def score(self, world, sid, facts):
            return RiskScore(0.95, [{"family": "route", "label": "stub model says route", "weight": 0.9}], "stub-v0", "trained:stub")

    prov = DefaultProviders(risk=AlarmistModel())
    r, st = AgentRuntime(providers=prov).investigate(SCENARIOS["healthy"](7))
    step = next(s for s in r.steps if s["tool"] == "predict_risk")
    assert step["outcome"] == "driver_route" and step["provenance"]["model_id"] == "stub-v0"


# ── ledger / learning contract ──────────────────────────────────────────────
def test_ledger_rows_validate_and_outcomes_are_never_fabricated():
    b = SCENARIOS["address_risk"](7)
    r, st = rt.investigate(b)
    led = rt.execute(r, st, b)
    frames = led.frames()
    for t, df in frames.items():
        validate_frame(t, df)
    assert (frames["outcome"]["kind"] == "pending").all() and frames["outcome"]["observed_ts"].isna().all()
    assert len(frames["action"]) == 1 and frames["action"]["executed_ts"].notna().all()
    assert (frames["action"]["origin"] == "synthetic").all()


def test_escalated_case_is_not_executed_without_approval():
    b = SCENARIOS["custody_conflict"](7)
    r, st = rt.investigate(b)
    led = rt.execute(r, st, b)
    assert led.frames()["action"].empty


# ── LLM planner (offline, fake client) ──────────────────────────────────────
class FakeClient:
    def __init__(self, picks):
        self.picks, self.calls = list(picks), 0
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls += 1
        name = self.picks.pop(0) if self.picks else "finish"
        blk = SimpleNamespace(type="tool_use", name=name, input={"why": "done"} if name == "finish" else {})
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="because"), blk])


def test_llm_planner_choices_are_honoured_but_gates_are_not_skippable():
    client = FakeClient(["get_address_context", "get_journey", "finish", "finish", "finish", "finish"])
    r, st = AgentRuntime(planner=LLMPlanner(client=client)).investigate(SCENARIOS["address_risk"](7))
    assert r.tool_path[:3] == ["get_shipment", "get_address_context", "get_journey"]
    assert r.decision["type"] in ("auto_eligible", "recommend", "escalate")
    if r.actions:
        assert "retrieve_policy_constraints" in r.tool_path


def test_llm_cannot_call_ineligible_or_repeated_tools():
    client = FakeClient(["rank_recovery_actions", "get_pickup_context", "get_journey", "get_journey"])
    planner = LLMPlanner(client=client)
    r, _ = AgentRuntime(planner=planner).investigate(SCENARIOS["healthy"](7))
    assert r.tool_path.count("get_journey") == 1  # a repeated request is rejected, not executed twice
    assert "get_pickup_context" not in r.tool_path  # healthy shipment has no pickup point
    assert "rank_recovery_actions" not in r.tool_path[:3]  # closing tools cannot be pulled forward by the LLM
    assert r.deviations or planner.deviations, "rejected LLM choices must be recorded for audit"


def test_llm_planner_requires_key_when_no_client(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        LLMPlanner()


# ── frontend compatibility ──────────────────────────────────────────────────
def test_frontend_adapter_matches_ui_contract():
    r, _ = run("route_blockage")
    ui = to_frontend(r)
    assert {"id", "shipmentId", "mode", "steps", "outcome", "status"} <= ui.keys()
    assert ui["outcome"]["type"] == "incident"
    allowed = {"get_shipment", "get_journey", "get_address_context", "get_route_context", "predict_risk", "analyze_disruption",
               "check_incident_context", "rank_recovery_actions", "retrieve_policy_constraints", "contact_recipient",
               "reschedule_delivery", "redirect_to_pickup", "escalate_case", "get_recipient_context", "get_facility_context", "get_pickup_context", "ask_inquiry"}  # = types/domain.ts ToolName
    assert all(s["tool"] in allowed for s in ui["steps"])
    json.dumps(ui)


# ── scenario generator ──────────────────────────────────────────────────────
@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_is_valid_tagged_synthetic_and_deterministic(name):
    a, b = SCENARIOS[name](3), SCENARIOS[name](3)
    for t, df in a.tables.items():
        assert (df["origin"] == "synthetic").all() and df["scenario_id"].notna().all()
        pd.testing.assert_frame_equal(df.reset_index(drop=True), b.tables[t].reset_index(drop=True))
    c = SCENARIOS[name](4)
    assert a.scenario_id != c.scenario_id
