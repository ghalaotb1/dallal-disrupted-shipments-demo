"""Resumable v2 agent runtime.

Loop:  plan (net value of information over tools AND questions) -> execute / ask -> update belief -> ... -> decide.
A question to a person PAUSES the run: the full state is JSON-serialisable (`state_to_json`), the pending inquiry is recorded, and
the run resumes when an answer arrives, the deadline passes (timeout is itself evidence), or a late answer shows up after the run
already finished (the case is reopened). The runtime never fabricates an answer: with no responder and no inbound event it stays
paused.

For experiments a synchronous `responder` (simulator) supplies answers so thousands of episodes can run without a network.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from dallal.agent.belief import CAUSES
from dallal.agent.prior import build_prior
from dallal.agent.state import ToolCall
from dallal.agent.trace import AgentRun, log_step
from dallal.agent.v2 import inquiry as iq
from dallal.agent.v2.bayes import EnsembleBelief, ModelBook, default_book
from dallal.agent.v2.events import InquiryResponse, InquiryTimeout
from dallal.agent.v2.planner import PlannerV2, Step
from dallal.agent.v2.policy import decide
from dallal.agent.v2.state import CaseStateV2, PendingInquiry, state_from_json, state_to_json
from dallal.agent.v2.tools import build_registry_v2, case_options
from dallal.agent.v2.utility import params
from dallal.tools.base import ToolContext
from dallal.tools.providers import DefaultProviders

HARD_CAP = 30
Responder = Callable[[PendingInquiry, CaseStateV2], "InquiryResponse | InquiryTimeout"]


@dataclass
class RunResult:
    run: AgentRun
    state: CaseStateV2
    status: str  # completed | awaiting_response
    pending: PendingInquiry | None = None

    def checkpoint(self) -> dict[str, Any]:
        return state_to_json(self.state)


class AgentRuntimeV2:
    def __init__(self, *, mode: str = "value", book: ModelBook | None = None, tools=None, providers: Any = None, channel: Any = None,
                 responder: Responder | None = None, budget: int = 8, planner: PlannerV2 | None = None):
        self.mode = mode
        self.planner = planner or PlannerV2(mode)
        self.book = book or default_book()
        self.tools = tools or build_registry_v2()
        self.providers = providers or DefaultProviders()
        self.channel = channel
        self.responder = responder
        self.budget = budget

    # ── public API ──
    def start(self, bundle, run_id: str | None = None, lang: str = "ar") -> RunResult:
        run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
        st = CaseStateV2(bundle.subject_id, bundle.trigger, bundle.as_of, budget=self.budget, mode=self.mode)
        st.lang = lang  # type: ignore[attr-defined]
        run = AgentRun(run_id, bundle.subject_id, bundle.scenario_id, None, self.planner.name, bundle.trigger, bundle.as_of.isoformat(), engine="v2")
        return self._advance(bundle, st, run)

    def resume(self, bundle, checkpoint: dict[str, Any], event: InquiryResponse | InquiryTimeout, run_id: str) -> RunResult:
        st = state_from_json(checkpoint, self.book)
        st.mode = checkpoint.get("mode", self.mode)
        run = AgentRun(run_id, bundle.subject_id, bundle.scenario_id, None, self.planner.name, bundle.trigger, bundle.as_of.isoformat(), engine="v2")
        if st.pending is not None and event.inquiry_id == st.pending.inquiry_id:
            self._apply(st, event)
            if st.pending is not None:  # an unreadable reply stays pending for human review; it is NOT evidence
                return self._finish(bundle, st, run, paused=True)
            return self._advance(bundle, st, run)
        # Not the question we are waiting for: either a late answer to an inquiry that already timed out, or a stale/duplicate event.
        return self._late(bundle, st, run, event)

    # ── main loop ──
    def _advance(self, bundle, st: CaseStateV2, run: AgentRun) -> RunResult:
        ctx = ToolContext(bundle, st, self.providers)
        stop_reason, stop_table = "hard cap reached", []
        while len(st.calls) < HARD_CAP:
            opts = stk = None
            if st.facts is not None:
                opts, stk = case_options(st, bundle)
            step = self.planner.next(st, self.tools, opts, stk)
            if step.kind == "stop":
                stop_reason, stop_table = step.reason, step.table
                break
            if step.kind == "tool":
                if step.name not in self.tools or step.name in st.called or not self.tools[step.name].requires(st):
                    run.deviations.append({"requested": step.name, "why": "unknown, repeated or precondition not met"})
                    stop_reason = "planner proposed an invalid tool; stopping to decide"
                    break
                self._call(ctx, st, run, step)
            else:
                self._ask(st, run, step)
                if self.responder is None:
                    return self._finish(bundle, st, run, paused=True)
                self._apply(st, self.responder(st.pending, st))  # type: ignore[arg-type]
        return self._finish(bundle, st, run, paused=False, stop_reason=stop_reason, stop_table=stop_table)

    def _finish(self, bundle, st: CaseStateV2, run: AgentRun, *, paused: bool, stop_reason: str = "", stop_table=None) -> RunResult:
        ctx = ToolContext(bundle, st, self.providers)
        if paused:
            run.status = "awaiting_response"
            run.decision = {"type": "awaiting_response", "policy_version": "policy-v2", "headline": "Waiting for an answer",
                            "rationale": f"Asked {st.pending.target if st.pending else '?'}: {st.pending.question if st.pending else ''}", "p_systemic": round(st.belief.p_systemic(), 3),
                            "top_cause": st.belief.top()[0].value, "posterior": round(st.belief.top()[1], 3), "pending_inquiry": st.pending.inquiry_id if st.pending else None}
        else:
            run.decision = decide(st, bundle)
            if run.decision["type"] == "escalate":
                if st.diagnosis is None and self.tools["analyze_disruption"].requires(st):
                    self._call(ctx, st, run, Step("tool", "analyze_disruption", "escalation requires a reconciled evidence packet", "close"))
                    run.decision = decide(st, bundle)
                if run.decision["type"] == "escalate" and self.tools["escalate_case"].requires(st):
                    self._call(ctx, st, run, Step("tool", "escalate_case", f"policy requires human review ({run.decision.get('reason')})", "close"))
                    run.decision["escalation_id"] = f"esc-{run.run_id}"
            run.decision["stop_reason"] = stop_reason
            run.decision["last_candidate_table"] = stop_table or []
            run.status = "completed"
        run.data_origin = (st.facts or {}).get("origin")
        run.belief_trajectory = [{"after": c.tool, **(c.belief_after or {})} for c in st.calls if c.belief_after]
        run.evidence = [vars(e) for e in st.evidence]
        run.diagnosis, run.actions, run.escalation = st.diagnosis, st.ranked_actions, st.escalation
        run.steps = [self._step_dict(c) for c in st.calls]
        run.inquiries = list(st.inquiries) + ([{"inquiry_id": st.pending.inquiry_id, "spec": st.pending.spec_id, "status": "awaiting_response", "target": st.pending.target,
                                                  "question": st.pending.question, "mode": st.pending.mode, "receipt": st.pending.receipt}] if st.pending else [])
        run.utility_table = st.utility_table
        run.virtual_minutes = round(st.virtual_min, 2)
        return RunResult(run, st, run.status, st.pending)

    # ── tool calls ──
    def _call(self, ctx: ToolContext, st: CaseStateV2, run: AgentRun, step: Step) -> None:
        spec = self.tools[step.name]  # type: ignore[index]
        t0 = time.perf_counter()
        res = spec.fn(ctx, {"shipment_id": st.subject_id})
        ms = (time.perf_counter() - t0) * 1000
        outcome = res.outcome
        if step.name == "predict_risk" and "risk" in res.data:
            outcome = res.data["risk"]["band"]
        if step.name == "get_shipment":
            st.facts = res.data["facts"]
            st.belief = EnsembleBelief.from_prior(self.book, build_prior(st.facts, st.trigger))
        elif outcome is not None and step.name in self.book.models:
            st.belief.update(step.name, outcome)  # type: ignore[union-attr]
            stance, cause = _stance(st, step.name, outcome)
            st.add_evidence(step.name, res.summary, "; ".join(res.facts[:2]), stance, cause)
        lat = params()["tool_latency_min"].get(step.name, params()["tool_latency_min"]["default"])
        st.virtual_min += lat
        call = ToolCall(len(st.calls), step.name, {"shipment_id": st.subject_id}, step.reason, res.status, res.summary, res.facts, outcome,
                        st.belief.snapshot() if st.belief else None, step.table, round(ms, 3), res.provenance)
        call.phase, call.source, call.data, call.t_min = step.phase, "voi", res.data, round(st.virtual_min, 2)  # type: ignore[attr-defined]
        st.calls.append(call)
        log_step(run.run_id, self._step_dict(call))

    # ── inquiries ──
    def _ask(self, st: CaseStateV2, run: AgentRun, step: Step) -> None:
        cand = step.candidate
        s = iq.spec(step.name)  # type: ignore[arg-type]
        facts = st.facts or {}
        lang = getattr(st, "lang", "ar")
        inquiry_id = f"inq-{run.run_id}-{len(st.asked) + 1}"
        ref = {"recipient": facts.get("recipient_phone"), "courier": facts.get("courier_id"), "dispatcher": f"dispatch:{facts.get('corridor_id')}",
               "branch_supervisor": f"branch:{facts.get('origin_node_id')}"}.get(s.target, "unknown")
        pend = PendingInquiry(inquiry_id, s.id, cand.source, s.target, s.scope, lang, iq.render_question(s, facts, lang), iq.answer_labels(s, lang), s.raw["mode"],
                              s.raw.get("template"), round(st.virtual_min, 2), float(s.raw["response"]["timeout_min"]), cand.p_response, str(ref), {}, round(cand.net_voi, 3), False, iq.render_question(s, facts, "en"))
        if self.channel is not None:
            pend.receipt = self.channel.send_inquiry(pend, facts, run_id=run.run_id)
        else:
            pend.receipt = {"mode": "none", "note": "no channel configured; nothing was sent"}
        st.pending = pend
        st.asked.append(s.id)
        call = ToolCall(len(st.calls), f"ask:{s.id}", {"to": s.target, "inquiry_id": inquiry_id}, step.reason, "warn",
                        f"Asked {s.target}: {pend.question}", [f"channel mode: {pend.receipt.get('mode')}", f"expected answer in ~{cand.latency_min:.0f} min ({cand.p_response:.0%} response chance)"],
                        None, st.belief.snapshot() if st.belief else None, step.table, 0.0, {"inquiry_catalogue": "inquiry-catalogue-v1", "delivery_mode": pend.receipt.get("mode")})
        call.phase, call.source, call.data, call.t_min = "investigate", "voi", {"inquiry": vars(pend)}, round(st.virtual_min, 2)  # type: ignore[attr-defined]
        st.calls.append(call)
        log_step(run.run_id, self._step_dict(call))

    def _apply(self, st: CaseStateV2, ev: InquiryResponse | InquiryTimeout) -> None:
        p = st.pending
        assert p is not None and ev.inquiry_id == p.inquiry_id
        call = next(c for c in st.calls if c.tool == f"ask:{p.spec_id}")
        s = iq.spec(p.spec_id)
        if isinstance(ev, InquiryResponse) and ev.answer_id is not None and not ev.needs_review:
            outcome, elapsed = ev.answer_id, max(0.0, ev.elapsed_min)
            label = next(a["en"] for a in s.answers if a["id"] == outcome)
            call.summary, call.status = f"{s.target.title()} answered: {label} (after {elapsed:.0f} min)", "ok"
        elif isinstance(ev, InquiryResponse) and ev.needs_review:
            # An answer exists but could not be interpreted safely: it is NOT used as evidence. Wait for the deadline / a human.
            p.needs_review = True
            st.inquiries.append({"inquiry_id": p.inquiry_id, "spec": p.spec_id, "status": "needs_review", "raw": ev.raw})
            return
        else:
            outcome, elapsed = iq.NO_RESPONSE, p.timeout_min
            call.summary, call.status = f"No answer from {s.target} within {p.timeout_min:.0f} min", "warn"
        call.outcome = outcome
        st.virtual_min = max(st.virtual_min, p.asked_at_min + elapsed)
        st.belief.update(p.variant, outcome)  # type: ignore[union-attr]
        call.belief_after = st.belief.snapshot()  # type: ignore[union-attr]
        stance, cause = _stance(st, p.variant, outcome)
        if outcome != iq.NO_RESPONSE:
            st.add_evidence(call.tool, call.summary, f"inquiry {p.inquiry_id}", stance, cause)
        st.inquiries.append({"inquiry_id": p.inquiry_id, "spec": p.spec_id, "target": p.target, "scope": p.scope, "status": "answered" if outcome != iq.NO_RESPONSE else "timed_out",
                             "outcome": outcome, "elapsed_min": round(elapsed, 2), "question": p.question, "net_voi_at_ask": p.net_voi_at_ask, "mode": p.receipt.get("mode"),
                             "interpretation": getattr(ev, "interpretation", {}), "provider_msg_id": getattr(ev, "provider_msg_id", None)})
        call.t_min = round(st.virtual_min, 2)  # type: ignore[attr-defined]
        st.pending = None

    def _late(self, bundle, st: CaseStateV2, run: AgentRun, ev: InquiryResponse | InquiryTimeout) -> RunResult:
        """An event arrived for an inquiry that is no longer pending.

        * duplicate of an answer already used  -> ignored (idempotent; never double-counted)
        * answer after a TIMEOUT                -> incorporated and the case is re-decided ('answered_late')
        * anything else (unknown id, timeout echo, unreadable answer) -> ignored
        """
        entry = next((i for i in st.inquiries if i["inquiry_id"] == ev.inquiry_id), None)
        waiting = st.pending is not None
        if isinstance(ev, InquiryTimeout) or entry is None or ev.answer_id is None or entry.get("status") != "timed_out":
            return self._finish(bundle, st, run, paused=waiting, stop_reason="event for a closed or unknown inquiry ignored")
        spec = iq.spec(entry["spec"])
        name = iq.variant_name(spec.id, iq.response_prob(spec, st.facts or {}))
        self.book.ensure(name)
        st.belief.update(name, ev.answer_id)  # type: ignore[union-attr]
        st.late.append({"inquiry_id": ev.inquiry_id, "answer_id": ev.answer_id, "note": "the earlier no_response update stays; a small double count is accepted and flagged"})
        entry.update({"status": "answered_late", "outcome": ev.answer_id})
        return self._finish(bundle, st, run, paused=waiting, stop_reason="reopened after a late answer")

    @staticmethod
    def _step_dict(c: ToolCall) -> dict[str, Any]:
        return {"index": c.index, "tool": c.tool, "args": c.args, "why": c.reason, "phase": getattr(c, "phase", None), "chosen_by": getattr(c, "source", None),
                "status": c.status, "summary": c.summary, "facts": c.facts, "outcome": c.outcome, "belief_after": c.belief_after, "candidates": c.planner_table,
                "duration_ms": c.duration_ms, "provenance": c.provenance, "t_min": getattr(c, "t_min", 0.0)}


def _stance(st: CaseStateV2, source: str, outcome: str) -> tuple[str, str | None]:
    """Does this observation support or contradict the cause the agent now believes in? Likelihood ratio vs the rest."""
    st.belief.book.ensure(source)  # type: ignore[union-attr]
    outs = st.belief.book.outcomes(source)  # type: ignore[union-attr]
    L = st.belief.book.models[source].matrix()[outs.index(outcome)]  # type: ignore[union-attr]
    top = st.belief.top()[0]  # type: ignore[union-attr]
    pc = st.belief.p_cause()  # type: ignore[union-attr]
    ci = {c: i for i, c in enumerate(CAUSES)}
    p_top = float(L[ci[top]].mean())
    rest = sum(pc[c] * float(L[ci[c]].mean()) for c in CAUSES if c != top) / max(1e-9, sum(pc[c] for c in CAUSES if c != top))
    lr = p_top / max(rest, 1e-9)
    return ("supports" if lr >= 1.5 else "contradicts" if lr <= 0.67 else "context"), top.value

