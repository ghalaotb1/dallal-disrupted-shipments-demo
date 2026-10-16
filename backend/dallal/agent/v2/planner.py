"""v2 planner: picks the evidence source with the best NET value of information, or stops and decides.

Modes (for honest ablation in the experiments):
  value        decision-focused: net EVOI in SAR-equivalents with delay decay, response risk, communication cost   <- the proposal
  infogain     asks/looks whenever expected entropy reduction is high; ignores utility, delay and cost            <- common baseline
  no_inquiry   as `value` but restricted to database tools (no questions to people)                               <- ablation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dallal.agent.belief import Cause
from dallal.agent.v2.state import CaseStateV2
from dallal.agent.v2.utility import Option, Stakes, params
from dallal.agent.v2.voi import Candidate, inquiry_candidates, set_voi, tool_candidates
from dallal.recovery.ranking import load_catalogue
from dallal.tools.base import ToolRegistry

INFOGAIN_MIN_BITS = 0.15
SCREEN_TRIGGERS = {"slow_task_watch", "risk_screen", "route_plan_screen"}  # proactive screening: the risk model is consulted first, before any reactive reasoning
MAX_INQUIRIES = 2


@dataclass
class Step:
    kind: str  # tool | ask | stop
    name: str | None
    reason: str
    phase: str
    candidate: Candidate | None = None
    table: list[dict[str, Any]] = field(default_factory=list)


def actionable(state: CaseStateV2) -> bool:
    lim = load_catalogue()["limits"]
    top, p, margin = state.belief.top()
    diag = state.diagnosis or {}
    return (top not in (Cause.UNKNOWN, Cause.CUSTODY_ANOMALY, Cause.NONE) and p >= lim["diagnose_min_posterior"]
            and margin >= lim["decisive_margin_min"] and diag.get("agreement") != "inconclusive")


class PlannerV2:
    def __init__(self, mode: str = "value", *, tools_first: bool = True, lookahead: bool = True):
        assert mode in ("value", "infogain", "no_inquiry")
        self.mode, self.tools_first, self.lookahead = mode, tools_first, lookahead  # the two flags exist for ablation studies
        self.name = f"v2-{mode}" + ("" if tools_first else "-joint") + ("" if lookahead else "-nolook")

    def candidates(self, state: CaseStateV2, tools: ToolRegistry, opts: list[Option], stk: Stakes, *, allow_inquiries: bool = True) -> tuple[list[Candidate], list[Candidate]]:
        """Every evidence source currently eligible, scored. Shared with planners that choose differently (e.g. the LLM planner)."""
        tool_c: list[Candidate] = []
        inq_c: list[Candidate] = []
        if state.info_calls() < state.budget:
            names = [s.name for s in tools.eligible(state, informative_only=True)]
            tool_c = tool_candidates(state.belief, names, opts, stk)
        if allow_inquiries and self.mode != "no_inquiry" and len(state.asked) < MAX_INQUIRIES and state.pending is None:
            inq_c = inquiry_candidates(state.belief, state.facts, state.now, set(state.asked), opts, stk)
        return tool_c, inq_c

    def next(self, state: CaseStateV2, tools: ToolRegistry, opts: list[Option] | None, stk: Stakes | None) -> Step:
        if state.facts is None:
            return Step("tool", "get_shipment", "bootstrap: shipment facts are needed to form a prior", "bootstrap")
        assert opts is not None and stk is not None
        if state.trigger.get("kind") in SCREEN_TRIGGERS and "predict_risk" not in state.called and "predict_risk" in tools:
            return Step("tool", "predict_risk", "screening trigger: consult the risk model first (a trained model scores the case, or abstains and says why)", "screen")
        tool_c, inq_c = self.candidates(state, tools, opts, stk)
        table = [c.as_row() for c in sorted(tool_c + inq_c, key=lambda c: -c.net_voi)][:8]

        # "Ask only for what you cannot look up": free, instant database evidence is exhausted BEFORE any question to a person is
        # considered (they are not mutually exclusive, and a question's value must be judged at the belief AFTER the lookups).
        if self.mode == "infogain" or (not self.tools_first and self.mode != "no_inquiry"):
            pick = self._pick(tool_c + inq_c)
        else:
            pick = self._pick(tool_c)
        lookahead = None
        if pick is None and self.mode != "infogain" and tool_c and self.lookahead:
            gross, cost = set_voi(state.belief, [c.label for c in tool_c], opts, stk)
            if gross - cost >= params()["autonomy"]["min_net_voi_sar"]:
                # No single tool flips the decision, but together they do: take the most informative-per-cost one first.
                pick = max(tool_c, key=lambda c: c.eig_bits / max(c.cost, 0.05))
                lookahead = (gross, cost)
        if pick is None and self.mode != "infogain" and self.tools_first:
            pick = self._pick(inq_c)
        if pick is not None:
            why = (f"net value of information {pick.net_voi:+.2f} SAR-eq (gross {pick.gross_voi:.2f}, cost {pick.cost:.2f}); {pick.p_decision_change:.0%} chance it changes the best option"
                   if self.mode != "infogain" else f"largest expected information gain: {pick.eig_bits:.2f} bits")
            if lookahead:
                why = f"no single tool changes the best option, but the remaining {len(tool_c)} cheap tools together are worth {lookahead[0] - lookahead[1]:+.2f} SAR-eq (set look-ahead); most informative per cost first"
            if pick.kind == "inquiry":
                why += f"; databases are exhausted, so ask {pick.target}: answer expected in ~{pick.latency_min:.0f} min with {pick.p_response:.0%} response chance"
            return Step("ask" if pick.kind == "inquiry" else "tool", pick.label, why, "investigate", pick, table)
        step = self.closing(state, tools)
        step.table = table
        return step

    def _pick(self, cands: list[Candidate]) -> Candidate | None:
        if not cands:
            return None
        if self.mode == "infogain":
            best = max(cands, key=lambda c: c.eig_bits)
            return best if best.eig_bits >= INFOGAIN_MIN_BITS else None
        best = max(cands, key=lambda c: c.net_voi)
        return best if best.net_voi >= params()["autonomy"]["min_net_voi_sar"] else None

    def closing(self, state: CaseStateV2, tools: ToolRegistry) -> Step:
        called = state.called
        top, p, _ = state.belief.top()
        if state.incident is not None:
            return Step("stop", None, "incident confirmed - handle at incident level; per-parcel diagnosis would duplicate it", "stop")
        if top == Cause.NONE and p >= 0.85:
            return Step("stop", None, f"shipment healthy with {p:.0%} confidence - keep monitoring", "stop")
        if "analyze_disruption" not in called:
            return Step("tool", "analyze_disruption", "reconcile the recorded exception with the gathered evidence before deciding", "close")
        # Expected utility (not a posterior threshold) decides what to do: rank the options, then check the autonomy gates on the best one.
        if "rank_recovery_actions" not in called:
            return Step("tool", "rank_recovery_actions", f"leading cause '{top.value}' ({p:.0%}); rank options by expected utility under the full belief", "close")
        if state.ranked_actions and "retrieve_policy_constraints" not in called:
            return Step("tool", "retrieve_policy_constraints", "check approval and autonomy bounds on the best action", "close")
        return Step("stop", None, "decision ready", "stop")
