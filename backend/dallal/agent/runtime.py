"""Agent runtime: a stateful loop of plan -> validate -> call tool -> update belief -> repeat, then a policy decision.

The LLM (if any) only fills the planner slot. Everything that carries authority — tool preconditions, budget, belief update,
closing gates, autonomy policy, ledger — lives here and in deterministic modules, so every run is reproducible and auditable.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from dallal.agent import policy
from dallal.agent.belief import CAUSES, OBSERVATION_MODELS, Belief
from dallal.agent.ledger import Ledger
from dallal.agent.planner import EvidenceDrivenPlanner, Planner, PlannerStep
from dallal.agent.prior import build_prior
from dallal.agent.state import CaseState, ToolCall
from dallal.agent.trace import AgentRun, log_step
from dallal.tools.base import ToolContext, ToolRegistry
from dallal.tools.builtin import build_registry
from dallal.tools.bundle import Bundle
from dallal.tools.providers import DefaultProviders


def _stance(state: CaseState, tool: str, outcome: str) -> tuple[str, str | None]:
    """Does this observation support or contradict the cause the agent now believes in? Likelihood ratio vs the rest."""
    model = OBSERVATION_MODELS[tool]
    L = model.matrix()[model.outcomes.index(outcome)]  # [c, s]
    top = state.top_cause()[0]
    pc = state.belief.p_cause()  # type: ignore[union-attr]
    ci = {c: i for i, c in enumerate(CAUSES)}
    p_top = float(L[ci[top]].mean())
    rest = sum(pc[c] * float(L[ci[c]].mean()) for c in CAUSES if c != top) / max(1e-9, sum(pc[c] for c in CAUSES if c != top))
    lr = p_top / max(rest, 1e-9)
    return ("supports" if lr >= 1.5 else "contradicts" if lr <= 0.67 else "context"), top.value


class AgentRuntime:
    HARD_CAP = 25  # absolute ceiling on tool calls per run, independent of the investigation budget

    def __init__(self, planner: Planner | None = None, tools: ToolRegistry | None = None, providers: Any = None, budget: int = 8):
        self.planner = planner or EvidenceDrivenPlanner()
        self.tools = tools or build_registry()
        self.providers = providers or DefaultProviders()
        self.budget = budget

    # ── one investigation ──
    def investigate(self, bundle: Bundle, run_id: str | None = None) -> tuple[AgentRun, CaseState]:
        run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
        state = CaseState(bundle.subject_id, bundle.trigger, bundle.as_of, budget=self.budget)
        run = AgentRun(run_id, bundle.subject_id, bundle.scenario_id, None, getattr(self.planner, "name", "planner"), bundle.trigger, bundle.as_of.isoformat())
        ctx = ToolContext(bundle, state, self.providers)

        while len(state.calls) < self.HARD_CAP:
            step = self._validate(self.planner.next(state, self.tools), state, run)
            if step.tool is None:
                stop_reason, stop_table = step.reason, step.table
                break
            self._call(ctx, state, run, step)
        else:
            stop_reason, stop_table = f"hard cap of {self.HARD_CAP} tool calls reached", []

        run.decision = policy.decide(state)
        if run.decision["type"] == "escalate":
            # A human needs a coherent hand-off packet: reconcile the evidence first if that has not happened yet.
            if state.diagnosis is None and self.tools["analyze_disruption"].requires(state):
                self._call(ctx, state, run, PlannerStep("analyze_disruption", "escalation requires a reconciled evidence packet", "close", "gate"))
                run.decision = policy.decide(state)
            if run.decision["type"] == "escalate" and self.tools["escalate_case"].requires(state):
                reason = run.decision.get("reason")
                self._call(ctx, state, run, PlannerStep("escalate_case", f"policy requires human review ({reason})", "close", "gate"))
                run.decision["escalation_id"] = f"esc-{run_id}"
        run.decision["stop_reason"] = stop_reason
        run.decision["last_candidate_table"] = stop_table
        run.data_origin = (state.facts or {}).get("origin")
        run.belief_trajectory = [{"after": c.tool, **(c.belief_after or {})} for c in state.calls if c.belief_after]
        run.evidence = [vars(e) for e in state.evidence]
        run.diagnosis, run.actions, run.escalation = state.diagnosis, state.ranked_actions, state.escalation
        run.steps = [self._step_dict(c) for c in state.calls]
        return run, state

    def _validate(self, step: PlannerStep, state: CaseState, run: AgentRun) -> PlannerStep:
        """Runtime-enforced safety: unknown / repeated / precondition-failing tool choices are rejected, not trusted."""
        if step.tool is None:
            return step
        if step.tool not in self.tools or step.tool in state.called or not self.tools[step.tool].requires(state):
            run.deviations.append({"requested": step.tool, "why": "unknown, repeated or precondition not met", "after_calls": len(state.calls)})
            return EvidenceDrivenPlanner().next(state, self.tools)
        return step

    def _call(self, ctx: ToolContext, state: CaseState, run: AgentRun, step: PlannerStep) -> None:
        spec = self.tools[step.tool]  # type: ignore[index]
        t0 = time.perf_counter()
        res = spec.fn(ctx, {"shipment_id": state.subject_id})
        ms = (time.perf_counter() - t0) * 1000
        if step.tool == "get_shipment":
            state.facts = res.data["facts"]
            state.belief = Belief.from_prior(build_prior(state.facts, state.trigger))
        elif res.outcome is not None and step.tool in OBSERVATION_MODELS:
            state.belief.update(step.tool, res.outcome)  # type: ignore[union-attr]
            stance, cause = _stance(state, step.tool, res.outcome)
            state.add_evidence(step.tool, res.summary, "; ".join(res.facts[:2]), stance, cause)
        call = ToolCall(len(state.calls), step.tool, {"shipment_id": state.subject_id}, step.reason, res.status, res.summary, res.facts,
                        res.outcome, state.belief.snapshot() if state.belief else None, step.table, round(ms, 3), res.provenance)
        call.phase = step.phase  # type: ignore[attr-defined]
        call.source = step.source  # type: ignore[attr-defined]
        call.data = res.data  # type: ignore[attr-defined]
        state.calls.append(call)
        log_step(run.run_id, self._step_dict(call))

    @staticmethod
    def _step_dict(c: ToolCall) -> dict[str, Any]:
        return {"index": c.index, "tool": c.tool, "args": c.args, "why": c.reason, "phase": getattr(c, "phase", None), "chosen_by": getattr(c, "source", None),
                "status": c.status, "summary": c.summary, "facts": c.facts, "outcome": c.outcome, "belief_after": c.belief_after,
                "candidates": c.planner_table, "duration_ms": c.duration_ms, "provenance": c.provenance}

    # ── execution of a permitted action (separate, logged step) ──
    def execute(self, run: AgentRun, state: CaseState, bundle: Bundle, *, approved_by: str | None = None) -> Ledger:
        d = run.decision
        ledger = Ledger(origin=(state.facts or {}).get("origin") or "synthetic", scenario_id=bundle.scenario_id)
        did = ledger.log_decision(run.run_id, state.subject_id, d["type"], bundle.as_of, {"belief": state.belief.snapshot(), "diagnosis": state.diagnosis,  # type: ignore[union-attr]
                                                                                              "tool_path": run.tool_path}, d["policy_version"])
        act = state.ranked_actions[0] if state.ranked_actions else None
        allowed = d["type"] == "auto_eligible" or (d["type"] in ("recommend", "escalate") and approved_by)
        if act and d["type"] in ("auto_eligible", "recommend", "escalate") and d.get("action"):
            executed = bool(allowed)
            if executed:
                self.providers.executor.execute(act["tool"], state.subject_id, {"action": act["kind"], "approved_by": approved_by or "policy:auto"})
            aid = ledger.log_action(run.run_id, state.subject_id, act["kind"], bundle.as_of, executed=executed, approval=act["approval"],
                                    assignment="agent" if d["type"] == "auto_eligible" else "human" if approved_by else "agent",
                                    params={"approved_by": approved_by}, snapshot=did)
            ledger.log_pending_outcome(aid, did, bundle.as_of)
        return ledger
