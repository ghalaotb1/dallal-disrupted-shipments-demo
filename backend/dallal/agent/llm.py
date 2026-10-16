"""LLM planner: an Anthropic tool-use model chooses the next tool; the runtime keeps authority.

What the LLM decides: WHICH eligible tool to call next (or to stop). What it cannot do: call a tool whose precondition fails,
repeat a tool, skip a mandatory closing gate, change a number, or override the autonomy policy. Any such attempt is recorded
as a deviation and replaced by the evidence-driven planner's step. The LLM is shown the same belief and EVOI table the
default planner uses, so it can follow or deliberately depart from the expected-information-gain advice (departures are
visible in the trace).

No API key is needed for the default planner; this class activates only when ANTHROPIC_API_KEY is set (or a client is injected,
which is how the unit tests run it offline).
"""

from __future__ import annotations

import json
import os
from typing import Any

from dallal.agent.planner import EvidenceDrivenPlanner, PlannerStep
from dallal.agent.state import CaseState
from dallal.config import ANTHROPIC_API_KEY_ENV, DEFAULT_LLM_MODEL
from dallal.tools.base import ToolRegistry

SYSTEM = """You are the planning component of Dallal, a logistics operations agent that investigates a disrupted or at-risk parcel.
You choose the next tool to call. You do not compute facts: all numbers come from tools. Prefer tools that best separate the
leading hypotheses; stop gathering once the decision would not change. If evidence conflicts or no cause is distinct, a human
must decide - do not push for a guess. Call exactly one tool per turn, or call `finish` when no tool is worth its cost."""

FINISH = {"name": "finish", "description": "Stop investigating; hand the state to the decision policy.",
          "input_schema": {"type": "object", "properties": {"why": {"type": "string"}}, "required": ["why"]}}


class LLMPlanner:
    def __init__(self, client: Any | None = None, model: str = DEFAULT_LLM_MODEL):
        self.name = f"llm:{model}+evoi-gates"
        self.model = model
        self.fallback = EvidenceDrivenPlanner()
        if client is None:
            key = os.environ.get(ANTHROPIC_API_KEY_ENV)
            if not key:
                raise RuntimeError(f"{ANTHROPIC_API_KEY_ENV} is not set; use the default EvidenceDrivenPlanner or inject a client")
            import anthropic

            client = anthropic.Anthropic(api_key=key)
        self.client = client
        self.deviations: list[dict[str, Any]] = []

    @staticmethod
    def _summary(state: CaseState, advice: PlannerStep) -> str:
        b = state.belief
        return json.dumps({
            "subject": state.subject_id, "trigger": state.trigger, "facts": state.facts,
            "belief": b.snapshot() if b else None, "tools_called": [{"tool": c.tool, "outcome": c.outcome, "summary": c.summary} for c in state.calls],
            "evoi_candidates": advice.table[:6], "advice": {"tool": advice.tool, "why": advice.reason, "phase": advice.phase},
        }, default=str)

    def next(self, state: CaseState, tools: ToolRegistry) -> PlannerStep:
        advice = self.fallback.next(state, tools)
        if advice.phase in ("bootstrap", "close") or advice.source == "gate":
            return advice  # mandatory gates are not negotiable
        eligible = [t for t in tools.eligible(state, informative_only=True)]
        if not eligible:
            return advice
        resp = self.client.messages.create(
            model=self.model, max_tokens=400, system=SYSTEM, tool_choice={"type": "any"},
            tools=[t.to_anthropic() for t in eligible] + [FINISH],
            messages=[{"role": "user", "content": self._summary(state, advice)}],
        )
        pick = next((blk for blk in resp.content if getattr(blk, "type", "") == "tool_use"), None)
        reason = next((blk.text for blk in resp.content if getattr(blk, "type", "") == "text"), "")
        if pick is None:
            self.deviations.append({"after": len(state.calls), "llm": None, "why": "no tool_use block"})
            return advice
        if pick.name == "finish":
            if advice.tool is not None and advice.phase == "investigate":
                # The LLM wants to stop although a tool still has real decision value: the gate stands, the disagreement is audited.
                self.deviations.append({"after": len(state.calls), "llm": "finish", "overridden_by": advice.tool, "why": "tool still has decision value"})
                return advice
            return PlannerStep(None, f"LLM: {pick.input.get('why', 'done')}", "stop", "llm", advice.table)
        if pick.name not in {t.name for t in eligible}:
            self.deviations.append({"after": len(state.calls), "llm": pick.name, "why": "not an eligible information tool"})
            return advice
        return PlannerStep(pick.name, f"LLM choice. {reason}".strip(), "investigate", "llm", advice.table)
