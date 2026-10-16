"""Planners choose the next tool. Two implementations share one interface:

* EvidenceDrivenPlanner (default, offline, deterministic): chooses information tools by exact expected information gain
  per unit cost under the agent's belief, then follows policy gates to close the case. The path EMERGES from what the
  tools return — there is no per-case script and no fixed order.
* LLMPlanner (dallal.agent.llm): an LLM picks the tool via function calling. It sees the same belief, the same eligible
  tools and the EVOI table as advice; the runtime still enforces preconditions and mandatory closing gates, so the LLM
  cannot skip a safety step or invent a tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from dallal.agent.belief import TOOL_COST, Cause
from dallal.agent.state import CaseState
from dallal.recovery.ranking import load_catalogue
from dallal.tools.base import ToolRegistry

EIG_PER_COST_MIN = 0.01  # numerical floor: a tool must buy at least some certainty
HANDOFF_EIG_PER_COST_MIN = 0.05  # while headed to a human, keep gathering evidence worth at least this much per cost unit
DECISION_CHANGE_MIN = 0.10  # ...AND have at least this chance of changing what the agent would do (decision-theoretic stop)


@dataclass
class PlannerStep:
    tool: str | None  # None => stop
    reason: str
    phase: str  # bootstrap | investigate | close | stop
    source: str = "evoi"  # evoi | gate | llm
    table: list[dict] = field(default_factory=list)  # candidate tools with EIG, for the audit trace


class Planner(Protocol):
    name: str

    def next(self, state: CaseState, tools: ToolRegistry) -> PlannerStep: ...


def actionable(state: CaseState) -> bool:
    """Is the leading cause strong and distinct enough to act on (vs. escalate)?"""
    lim = load_catalogue()["limits"]
    top, p, margin = state.top_cause()
    diag = state.diagnosis or {}
    return (top not in (Cause.UNKNOWN, Cause.CUSTODY_ANOMALY, Cause.NONE) and p >= lim["diagnose_min_posterior"]
            and margin >= lim["decisive_margin_min"] and diag.get("agreement") != "inconclusive")


class EvidenceDrivenPlanner:
    name = "evidence-driven-evoi-v1"

    def eig_table(self, state: CaseState, tools: ToolRegistry) -> list[dict]:
        rows = []
        for spec in tools.eligible(state, informative_only=True):
            eig = state.belief.expected_information_gain(spec.name)  # type: ignore[union-attr]
            cost = TOOL_COST.get(spec.name, spec.cost)
            pchg = state.belief.p_decision_change(spec.name)  # type: ignore[union-attr]
            rows.append({"tool": spec.name, "eig_bits": round(eig, 4), "cost": cost, "eig_per_cost": round(eig / cost, 4),
                         "p_decision_change": round(pchg, 4)})
        rows.sort(key=lambda r: -r["eig_per_cost"])
        return rows

    def closing_step(self, state: CaseState, tools: ToolRegistry) -> PlannerStep:
        called = state.called
        top, p, _ = state.top_cause()
        if state.incident is not None:
            return PlannerStep(None, "incident confirmed — handle at incident level; individual diagnosis would duplicate it", "stop", "gate")
        if top == Cause.NONE and p >= 0.8:
            return PlannerStep(None, f"shipment healthy with {p:.0%} confidence — keep monitoring", "stop", "gate")
        if "analyze_disruption" not in called:
            return PlannerStep("analyze_disruption", "reconcile the recorded exception with the gathered evidence before deciding", "close", "gate")
        if actionable(state):
            if "rank_recovery_actions" not in called:
                return PlannerStep("rank_recovery_actions", f"cause '{top.value}' is distinct ({p:.0%}); rank actions that fit it", "close", "gate")
            if state.ranked_actions and "retrieve_policy_constraints" not in called:
                return PlannerStep("retrieve_policy_constraints", "check approval and autonomy bounds for the top action", "close", "gate")
        return PlannerStep(None, "diagnosis complete" if actionable(state) else "evidence cannot name a distinct cause — hand to a human", "stop", "gate")

    def next(self, state: CaseState, tools: ToolRegistry) -> PlannerStep:
        if state.facts is None:
            return PlannerStep("get_shipment", "bootstrap: shipment facts are needed to form a prior", "bootstrap", "gate")
        table = self.eig_table(state, tools)
        if state.info_calls() >= state.budget:
            # The budget bounds INVESTIGATION only. Closing gates (reconcile -> rank -> policy) must always be able to run,
            # otherwise a long investigation could silently skip the autonomy check.
            step = self.closing_step(state, tools)
            step.reason = f"investigation budget ({state.budget}) reached; " + step.reason
            step.table = table
            return step
        if state.belief.decision_class()[1] == "escalate":  # type: ignore[union-attr]
            # The case is headed to a human. Decision-change is moot, but the hand-off packet should be as informative as is
            # cheap: keep gathering while a tool still buys real certainty.
            useful = [r for r in table if r["eig_per_cost"] >= HANDOFF_EIG_PER_COST_MIN]
        else:
            useful = [r for r in table if r["eig_per_cost"] >= EIG_PER_COST_MIN and r["p_decision_change"] >= DECISION_CHANGE_MIN]
        if useful:
            best = useful[0]
            return PlannerStep(best["tool"], f"largest information gain per cost ({best['eig_bits']:.2f} bits, cost {best['cost']}); "
                                             f"{best['p_decision_change']:.0%} chance it changes the decision", "investigate", "evoi", table)
        step = self.closing_step(state, tools)
        step.table = table
        return step
