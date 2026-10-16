"""LLM planner guard-rails, with a scripted stand-in for the model (no Ollama needed)."""

from __future__ import annotations

import numpy as np

from dallal.agent.v2 import inquiry as iq
from dallal.agent.v2.llm_planner import FINISH, LLMPlanner
from dallal.agent.v2.runtime import AgentRuntimeV2
from dallal.agent.v2.tools import build_registry_v2
from dallal.llm import ollama
from dallal.sim.world import SimEnv, TrueModel, draw_episode, sim_registry


def _run(chat, seed=3):
    ep = draw_episode(np.random.default_rng(seed), systemic=False, seed=seed)
    env = SimEnv(ep, TrueModel(), np.random.default_rng(seed + 10_000), engine="v2")
    planner = LLMPlanner("stub", "hybrid", chat=chat)
    responder = lambda pend, st: env.answer(pend, iq.spec(pend.spec_id), pend.p_response)  # noqa: E731
    rr = AgentRuntimeV2(mode="value", tools=sim_registry(build_registry_v2(), "v2"), responder=responder, planner=planner).start(env)
    return rr, planner


def _res(name=None, **kw):
    calls = [] if name is None else [{"name": name, "arguments": {"rationale": "because"}}]
    return ollama.ChatResult(kw.get("content", ""), calls, 0.1, 100, 10)


def test_premature_finish_cannot_unlock_autonomy():
    """Finishing with no evidence gathered: the deterministic closing refuses (preconditions) and the case is escalated, never auto-executed."""
    rr, pl = _run(lambda *a, **k: _res(FINISH))
    assert [s["tool"] for s in rr.run.steps] == ["get_shipment"] and pl.log[0]["chosen"] == FINISH
    assert rr.run.decision["type"] != "auto_eligible"


def test_finish_after_gathering_goes_through_deterministic_closing():
    def chat(model, msgs, tools=None, **k):
        names = [t["function"]["name"] for t in tools]
        return _res(next((n for n in names if n.startswith("get_")), FINISH))

    closed = 0
    for seed in range(1, 9):
        rr, _ = _run(chat, seed)
        tools = [s["tool"] for s in rr.run.steps]
        if "rank_recovery_actions" in tools:  # healthy / resolved episodes legitimately stop before ranking
            closed += 1
            assert "retrieve_policy_constraints" in tools
            assert tools.index("rank_recovery_actions") > max(i for i, t in enumerate(tools) if t.startswith("get_"))
    assert closed >= 2


def test_unknown_tool_name_is_rejected_and_the_advisor_step_is_used():
    rr, pl = _run(lambda *a, **k: _res("delete_all_shipments"))
    assert pl.log and all(r["failure"] == "not_in_menu" and not r["valid"] for r in pl.log)
    assert rr.run.decision is not None  # run still completed via the fallback planner


def test_no_tool_call_and_backend_errors_fall_back():
    rr, pl = _run(lambda *a, **k: _res(None, content="I think we should just call the courier."))
    assert {r["failure"] for r in pl.log} == {"no_tool_call"} and rr.run.decision is not None

    def boom(*a, **k):
        raise ollama.LLMError("down")

    rr2, pl2 = _run(boom)
    assert {r["failure"] for r in pl2.log} == {"llm_error"} and rr2.run.decision is not None


def test_valid_choice_is_executed_and_logged_with_rationale():
    seen = {}

    def chat(model, msgs, tools=None, **k):
        names = [t["function"]["name"] for t in tools]
        seen.setdefault("first_menu", names)
        pick = next((n for n in names if n.startswith("get_")), FINISH)
        return _res(pick)

    rr, pl = _run(chat)
    assert FINISH in seen["first_menu"] and any(r["valid"] and r["chosen"] != FINISH for r in pl.log)
    assert any("LLM planner (stub, hybrid)" in (s.get("why") or "") for s in rr.run.steps)
