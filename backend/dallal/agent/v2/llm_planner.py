"""LLM investigation planner (Qwen via Ollama native tool calling) with hard guard-rails.

What the model may do: choose the NEXT investigation step - an eligible database tool, an eligible question to a person, or
`finish_investigation`. What it may not do (enforced structurally, not by prompt):
  * invent evidence: tool results come from the runtime; the model only sees them;
  * invent probabilities: the beliefs it reads are the Bayesian posterior computed by `EnsembleBelief`;
  * grant permissions or choose the final action: closing (diagnosis -> expected-utility ranking -> policy gates) is always the
    deterministic pipeline, so autonomy limits and approvals cannot be argued away;
  * call anything not in the menu: an unknown / ineligible / repeated name, malformed arguments or no tool call at all is logged
    as a failure and the decision-theoretic planner's step is used instead.
Modes: `pure` (the model sees the evidence and belief only) and `hybrid` (it also sees the EVOI advisor table and may follow or
override it). Both are compared against the EVOI planner in the simulator; see dallal/eval/llm_planner_bench.py.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from dallal.agent.v2 import inquiry as iq
from dallal.agent.v2.planner import PlannerV2, Step
from dallal.agent.v2.state import CaseStateV2
from dallal.agent.v2.utility import Option, Stakes
from dallal.llm import ollama
from dallal.tools.base import ToolRegistry

SYSTEM = (
    "You are the investigation planner of Dallal, an agent that handles disrupted last-mile parcels for a postal operator. "
    "Choose exactly ONE next step by calling one function. Database tools are free and instant. Functions starting with ask_ send a WhatsApp "
    "message to a person: they cost effort, take minutes to hours, and may get no reply, so use them only for facts no database can give and only if "
    "the answer could change the best recovery action. Call finish_investigation when more evidence would not change what you would recommend. "
    "Never assume facts that are not in the evidence list. Keep the rationale under 25 words."
)

FINISH = "finish_investigation"
ChatFn = Callable[..., ollama.ChatResult]


def _fn(name: str, description: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description,
                                             "parameters": {"type": "object", "properties": {"rationale": {"type": "string", "description": "why this step, in under 25 words"}}, "required": ["rationale"]}}}


class LLMPlanner(PlannerV2):
    def __init__(self, model: str, mode: str = "hybrid", chat: ChatFn | None = None):
        super().__init__("value")
        assert mode in ("pure", "hybrid")
        self.model, self.llm_mode = model, mode
        self.name = f"llm-{mode}:{model}"
        self._chat = chat or ollama.chat
        self.log: list[dict[str, Any]] = []

    # ── prompt ──
    def _evidence_lines(self, st: CaseStateV2) -> list[str]:
        lines = []
        for c in st.calls:
            if c.tool in ("get_shipment",) or c.outcome is None:
                continue
            lines.append(f"- {c.tool}: {c.summary}" + (f" [{'; '.join(c.facts[:2])}]" if c.facts else ""))
        for i in st.inquiries:
            lines.append(f"- asked {i['target']} ({i['spec']}): {i['status']}" + (f", outcome={i.get('outcome')}" if i.get("outcome") else ""))
        return lines or ["- (none yet)"]

    def _prompt(self, st: CaseStateV2, stk: Stakes, menu_tools, menu_inq, table: list[dict[str, Any]], base: Step) -> str:
        f = st.facts or {}
        causes = sorted(st.belief.p_cause().items(), key=lambda kv: -kv[1])[:4]
        parts = [
            f"Case: shipment {st.subject_id}, trigger {st.trigger.get('kind', st.trigger)}. Service {f.get('service_level')}, {f.get('payment_type')}, value {f.get('value', 0):.0f} SAR, "
            f"minutes of slack to the promise ~{stk.horizon_min:.0f}, recorded exception {f.get('recorded_code')}, failed attempts {f.get('failed_attempts')}.",
            "Evidence so far:", *self._evidence_lines(st),
            "Current belief about the cause (computed, do not change): " + ", ".join(f"{c.value} {p:.0%}" for c, p in causes) + f"; chance this is part of a wider incident {st.belief.p_systemic():.0%}.",
            f"Questions already sent: {len(st.asked)} of 2 allowed.",
        ]
        if self.llm_mode == "hybrid":
            parts.append("Decision-theory advisor (expected net value of information in SAR-equivalents, higher is better; a source below ~0.4 is not worth its cost):")
            for r in table[:6]:
                parts.append(f"- {r['source']}: net {r['net_voi']:+.2f}, chance it changes the best action {r['p_decision_change']:.0%}" + (f", reply chance {r['p_response']:.0%}, ~{r['latency_min']:.0f} min" if r["kind"] == "inquiry" else ""))
            parts.append(f"The advisor would now: {'finish the investigation' if base.kind == 'stop' or base.phase in ('close', 'stop') else base.name}. You may follow or override it.")
        parts.append("Choose the next step.")
        return "\n".join(parts)

    def _tools_spec(self, tools: ToolRegistry, menu_tools, menu_inq, facts: dict[str, Any]) -> list[dict[str, Any]]:
        out = [_fn(t.name, t.description) for t in menu_tools]
        for c in menu_inq:
            s = iq.spec(c.label)
            out.append(_fn(c.label, f"Ask the {s.target} on WhatsApp: \"{iq.render_question(s, facts, 'en')}\" (answers: {', '.join(a['en'] for a in s.answers)}). Slow; may get no reply."))
        out.append(_fn(FINISH, "Stop gathering evidence and move on to diagnosis and the recommended action."))
        return out

    # ── decision ──
    def next(self, state: CaseStateV2, tools: ToolRegistry, opts: list[Option] | None, stk: Stakes | None) -> Step:
        base = super().next(state, tools, opts, stk)
        in_closing = "analyze_disruption" in state.called
        if state.facts is None or in_closing or state.pending is not None or base.phase in ("bootstrap",) or (base.kind == "stop" and state.incident is not None):
            return base
        assert opts is not None and stk is not None
        tool_c, inq_c = self.candidates(state, tools, opts, stk, allow_inquiries=True)
        if not tool_c and not inq_c:
            return base
        menu_tools = [tools[c.label] for c in tool_c]
        spec = self._tools_spec(tools, menu_tools, inq_c, state.facts)
        names = {s["function"]["name"] for s in spec}
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": self._prompt(state, stk, menu_tools, inq_c, base.table, base)}]
        base_name = FINISH if (base.kind == "stop" or base.phase in ("close", "stop")) else base.name
        rec: dict[str, Any] = {"model": self.model, "mode": self.llm_mode, "base_choice": base_name, "menu": sorted(names)}
        try:
            res = self._chat(self.model, msgs, tools=spec)
        except ollama.LLMError as e:
            rec.update(valid=False, failure="llm_error", detail=str(e), chosen=None, latency_s=0.0)
            self.log.append(rec)
            return base
        rec.update(latency_s=res.latency_s, prompt_tokens=res.prompt_tokens, output_tokens=res.output_tokens)
        if not res.tool_calls:
            rec.update(valid=False, failure="no_tool_call", chosen=None, text=res.content[:120])
            self.log.append(rec)
            return base
        call = res.tool_calls[0]
        name = call["name"]
        args = call.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if name not in names:
            rec.update(valid=False, failure="not_in_menu", chosen=name)
            self.log.append(rec)
            return base
        why = str(args.get("rationale", ""))[:200] or "(no rationale given)"
        rec.update(valid=True, chosen=name, agrees=name == base_name, rationale=why)
        self.log.append(rec)
        reason = f"LLM planner ({self.model}, {self.llm_mode}): {why}"
        if name == FINISH:
            step = self.closing(state, tools)
            step.reason = f"{reason} -> {step.reason}"
            step.table = base.table
            return step
        cand = next((c for c in tool_c + inq_c if c.label == name), None)
        return Step("ask" if cand is not None and cand.kind == "inquiry" else "tool", name, reason, "investigate", cand, base.table)
