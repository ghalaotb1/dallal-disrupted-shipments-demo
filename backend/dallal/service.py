"""OpsService: the single owner of Dallal's operational state.

Everything the UI shows comes from here, so every screen sees one consistent state: runs and their traces, inquiries and their
WhatsApp delivery states, coordinated plans, approvals, executions and recorded outcomes. Every state change appends an event to
the audit timeline (the UI subscribes to it).

HONESTY: every message record carries its delivery mode. In sandbox mode nothing leaves the process and `real_delivery` is
False; in cloud mode `accepted` means Meta accepted the request, and later states are set only from Meta's status webhooks.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict
from typing import Any

import pandas as pd

from dallal.agent.ledger import Ledger
from dallal.agent.v2 import inquiry as iq
from dallal.agent.v2.bayes import default_book
from dallal.agent.v2.events import InquiryResponse, InquiryTimeout
from dallal.agent.v2.runtime import AgentRuntimeV2, RunResult
from dallal.channels import templates as tpl
from dallal.channels import whatsapp as wa
from dallal.channels.channel import WhatsAppChannel
from dallal.channels.interpret import interpret
from dallal.plans import PlanOps
from dallal.store import Store
from dallal.tools.bundle import Bundle
from dallal.tools.providers import DefaultProviders

STANDING = ("dispatch:", "branch:", "dallal-demo:courier", "sim:courier")  # operational contacts with a standing session (assumption, flagged in meta)


class OpsService:
    def __init__(self, store: Store | None = None, provider: Any = None, time_scale: float | None = None, mode: str = "value"):
        self.store = store or Store(os.environ.get("DALLAL_DB", ":memory:"))
        self.provider = provider or wa.SandboxProvider()
        self.time_scale = float(time_scale if time_scale is not None else os.environ.get("DALLAL_TIME_SCALE", "1"))
        self.mode = mode
        self.book = default_book()
        self.providers = DefaultProviders()
        self.channel = WhatsAppChannel(self.provider, on_sent=self._on_sent)
        self.plans = PlanOps(self)
        self.locks: dict[str, threading.Lock] = {}
        self._glock = threading.Lock()

    # ── helpers ──
    def _lock(self, run_id: str) -> threading.Lock:
        with self._glock:
            return self.locks.setdefault(run_id, threading.Lock())

    def _guard_send(self, pending: Any, facts: dict[str, Any]) -> dict[str, Any]:
        return _Guard(self.channel, self.store).send_inquiry(pending, facts)

    def _runtime(self) -> AgentRuntimeV2:
        return AgentRuntimeV2(mode=self.mode, book=self.book, providers=self.providers, channel=_Guard(self.channel, self.store))

    def meta(self) -> dict[str, Any]:
        return {"service": "dallal-backend", "engine": "v2", "decision_mode": self.mode, "whatsapp_mode": self.provider.mode, "real_delivery_possible": self.provider.mode == "cloud",
                "time_scale": self.time_scale, "policy": "policy-v2", "utility": "utility-v1", "inquiry_catalogue": "inquiry-catalogue-v1", "model_basis": "expert_assumption_v1",
                "assumptions": ["standing operational sessions for couriers/dispatch/branch (no template needed)", "all probabilities, latencies and costs are expert assumptions"],
                "notice": "Sandbox messages are NOT sent to any phone." if self.provider.mode == "sandbox" else "Cloud mode: 'accepted' means Meta accepted the request; delivery is confirmed only by status webhooks."}

    def _on_sent(self, pending: Any, receipt: dict[str, Any], payload: dict[str, Any] | None) -> None:
        if payload is not None and receipt.get("status") != "refused":
            self.store.add_message(pending.inquiry_id, "out", "whatsapp", receipt.get("wamid"), receipt["mode"], receipt["status"], payload.get("type", "?"), {"payload": payload, "receipt": receipt,
                                   "rendered": self._render(payload, pending)})

    def _render(self, payload: dict[str, Any], pending: Any) -> dict[str, Any]:
        t = payload.get("type")
        if t == "template":
            name = payload["template"]["name"]
            lang = payload["template"]["language"]["code"]
            params = [p["text"] for c in payload["template"]["components"] if c["type"] == "body" for p in c["parameters"]]
            btn = [{"id": c["parameters"][0]["payload"], "title": next((a["title"] for a in pending.answers if c["parameters"][0]["payload"].endswith("|" + a["id"])), "")} for c in payload["template"]["components"] if c["type"] == "button"]
            return {"text": tpl.render(name, "ar" if lang == "ar" else "en_US", params), "buttons": btn, "template": name, "language": lang}
        if t == "interactive":
            i = payload["interactive"]
            rows = [{"id": b["reply"]["id"], "title": b["reply"]["title"]} for b in i.get("action", {}).get("buttons", [])] or \
                   [{"id": r["id"], "title": r["title"]} for s in i.get("action", {}).get("sections", []) for r in s["rows"]]
            return {"text": i["body"]["text"], "buttons": rows, "list": i["type"] == "list"}
        return {"text": payload.get("text", {}).get("body", ""), "buttons": []}

    # ── runs ──
    def investigate(self, bundle: Bundle, lang: str = "ar") -> dict[str, Any]:
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        with self._lock(run_id):
            self.store.emit("run_started", bundle.subject_id, run_id, {"scenario": bundle.scenario_id, "trigger": bundle.trigger})
            res = self._runtime().start(bundle, run_id, lang)
            return self._persist(res, bundle, new=True)

    def _persist(self, res: RunResult, bundle: Bundle, new: bool = False) -> dict[str, Any]:
        run = res.run
        rd = _run_dict(run)
        self.store.save_run(run.run_id, run.subject_id, res.status, "v2", run.scenario_id, run.data_origin, json.dumps(bundle.to_dict(), default=str) if new else None, res.checkpoint(), rd)
        known = {i["inquiry_id"] for i in self.store.inquiries_for(run_id=run.run_id)}
        if res.pending is not None and res.pending.inquiry_id not in known:
            p = res.pending
            now = time.time()
            self.store.save_inquiry(inquiry_id=p.inquiry_id, run_id=run.run_id, spec_id=p.spec_id, target=p.target, scope=p.scope, recipient_hash=wa.hash_ref(p.recipient_ref),
                                    recipient_ref=p.recipient_ref, delivery_mode=p.receipt.get("mode"), status="awaiting", asked_real=now, deadline_real=now + p.timeout_min * 60.0 / self.time_scale,
                                    answered_real=None, outcome=None, question=p.question, answers_json=p.answers, payload_json={"receipt": p.receipt, "net_voi_at_ask": p.net_voi_at_ask,
                                    "p_response": p.p_response, "mode": p.mode, "template": p.template, "question_en": p.question_en}, subject_id=run.subject_id)
            self.store.emit("inquiry_sent", run.subject_id, run.run_id, {"inquiry_id": p.inquiry_id, "target": p.target, "spec": p.spec_id, "question": p.question, "receipt": p.receipt,
                                                                         "timeout_min": p.timeout_min, "net_voi": p.net_voi_at_ask})
        self.store.emit("run_" + res.status, run.subject_id, run.run_id, {"decision": run.decision.get("type"), "headline": run.decision.get("headline"), "top_cause": run.decision.get("top_cause"),
                                                                        "tool_path": run.tool_path})
        if res.status == "completed":
            self.store.emit("decision", run.subject_id, run.run_id, {k: run.decision.get(k) for k in ("type", "reason", "action", "headline", "rationale", "top_cause", "posterior", "chosen_option", "decision_stability")})
            self._log_decision(run, bundle)
        # A send that was refused (opt-out, allow-list, window rules) must not leave the run waiting for an answer that cannot come.
        if res.pending is not None and res.pending.receipt.get("status") == "refused":
            self.store.update_inquiry(res.pending.inquiry_id, status="send_refused")
            self.store.emit("inquiry_refused", run.subject_id, run.run_id, {"inquiry_id": res.pending.inquiry_id, "error": res.pending.receipt.get("error")})
            return self._continue(run.run_id, InquiryTimeout(res.pending.inquiry_id, "send_refused"), bundle)
        return self.view_run(run.run_id)

    def _log_decision(self, run: Any, bundle: Bundle) -> None:
        led = Ledger(origin=run.data_origin or "synthetic", scenario_id=run.scenario_id)
        led.log_decision(run.run_id, run.subject_id, run.decision["type"], bundle.as_of, {"tool_path": run.tool_path, "inquiries": [i.get("inquiry_id") for i in run.inquiries]}, run.decision.get("policy_version", "policy-v2"))
        for r in led.decisions:
            self.store.ledger_add("decision", r)

    def _continue(self, run_id: str, ev: InquiryResponse | InquiryTimeout, bundle: Bundle | None = None) -> dict[str, Any]:
        if run_id.startswith("plan-"):
            return self.plans.resume(run_id, ev)  # a shared incident-level question resumes the PLAN, not a single-shipment run
        rec = self.store.get_run(run_id)
        bundle = bundle or Bundle.from_dict(json.loads(rec["bundle_json"]))
        res = self._runtime().resume(bundle, rec["checkpoint"], ev, run_id)
        return self._persist(res, bundle)

    def view_run(self, run_id: str) -> dict[str, Any]:
        rec = self.store.get_run(run_id)
        if rec is None:
            raise KeyError(run_id)
        run = rec["run"]
        run["inquiries_live"] = [self._inquiry_view(i) for i in self.store.inquiries_for(run_id=run_id)]
        run["status"] = rec["status"]
        run["live"] = {"backend": True, "engine": "v2", "data_origin": rec["origin"], "whatsapp_mode": self.provider.mode}
        return run

    def _inquiry_view(self, i: dict[str, Any]) -> dict[str, Any]:
        payload = json.loads(i["payload_json"]) if i["payload_json"] else {}
        msgs = self.store.messages_for(i["inquiry_id"])
        return {"inquiry_id": i["inquiry_id"], "run_id": i["run_id"], "subject_id": i["subject_id"], "spec": i["spec_id"], "target": i["target"], "scope": i["scope"], "status": i["status"],
                "delivery_mode": i["delivery_mode"], "question": i["question"], "question_en": payload.get("question_en", ""), "answers": json.loads(i["answers_json"]) if i["answers_json"] else [], "outcome": i["outcome"],
                "asked_real": i["asked_real"], "deadline_real": i["deadline_real"], "answered_real": i["answered_real"], "net_voi": payload.get("net_voi_at_ask"), "p_response": payload.get("p_response"),
                "recipient_hash": i["recipient_hash"], "real_delivery": any(m["status"] in ("delivered", "read") and m["mode"] == "cloud" for m in msgs),
                "messages": [{"direction": m["direction"], "status": m["status"], "kind": m["kind"], "mode": m["mode"], "wamid": m["wamid"], "text": (m["body"].get("rendered") or {}).get("text") or m["body"].get("text"),
                              "buttons": (m["body"].get("rendered") or {}).get("buttons", []), "at": m["created_at"], "interpretation": m["body"].get("interpretation")} for m in msgs]}

    # ── inbound ──
    def handle_webhook(self, payload: dict[str, Any], source: str = "whatsapp") -> dict[str, Any]:
        msgs, stats = wa.parse_webhook(payload)
        out = {"messages": 0, "statuses": 0, "duplicates": 0, "unmatched": 0, "resumed": []}
        for s in stats:
            if self.store.seen_event(f"status:{s.wamid}:{s.status}", "status"):
                out["duplicates"] += 1
                continue
            rows = self.store.set_message_status(s.wamid, s.status if self.provider.mode == "cloud" else "sandbox_" + s.status)
            out["statuses"] += 1
            if rows:
                inq = self.store.get_inquiry(rows[0]["inquiry_id"])
                self.store.emit("message_status", inq["subject_id"] if inq else None, inq["run_id"] if inq else None, {"wamid": s.wamid, "status": s.status, "errors": s.errors, "mode": rows[0]["mode"],
                                                                                                                        "inquiry_id": rows[0]["inquiry_id"]})
        for m in msgs:
            if self.store.seen_event(f"msg:{m.wamid}", "message"):
                out["duplicates"] += 1
                continue
            out["messages"] += 1
            inq = self._correlate(m)
            if inq is None:
                out["unmatched"] += 1
                self.store.emit("inbound_unmatched", None, None, {"kind": m.kind, "sender_hash": wa.hash_ref(m.sender)})
                continue
            if self.provider.mode == "sandbox":
                self.provider.open_window(inq["recipient_ref"])
            r = self._on_inbound(m, inq)
            out["resumed"].append({"run_id": r.get("run_id") or r.get("plan_id"), "status": r.get("status"), "inquiry_id": inq["inquiry_id"]})
        return out

    def _correlate(self, m: wa.Inbound) -> dict[str, Any] | None:
        if m.context_id:
            for row in self.store.q("SELECT inquiry_id FROM messages WHERE direction='out' AND wamid=?", (m.context_id,)):
                inq = self.store.get_inquiry(row["inquiry_id"])
                if inq and inq["status"] == "awaiting":
                    return inq
        for key in (m.button_payload, m.choice_id):  # our own payload convention carries the inquiry id
            if key and "|" in key:
                inq = self.store.get_inquiry(key.split("|", 1)[0])
                if inq:
                    return inq
        pend = self.store.pending_for_recipient(m.sender)
        return pend[0] if pend else None

    def _on_inbound(self, m: wa.Inbound, inq: dict[str, Any]) -> dict[str, Any]:
        run_id = inq["run_id"]
        with self._lock(run_id):
            rec = self.store.get_run(run_id)
            facts = ((rec["checkpoint"] or {}).get("facts") or {}) if rec else {}
            spec = iq.spec(inq["spec_id"])
            it = interpret(m, spec, inq["inquiry_id"], facts)
            body = {"kind": m.kind, "text": m.text if m.kind == "text" else None, "button_text": m.button_text, "choice_title": m.choice_title, "lat": m.lat, "lng": m.lng, "media_id": m.media_id,
                    "interpretation": asdict(it)}
            self.store.add_message(inq["inquiry_id"], "in", "whatsapp", m.wamid, self.provider.mode, "received", m.kind, body)
            self.store.emit("reply_received", inq["subject_id"], run_id, {"inquiry_id": inq["inquiry_id"], "target": inq["target"], "kind": m.kind, "answer": it.answer_id, "confidence": it.confidence, "method": it.method,
                                                                         "needs_review": it.needs_review, "mode": self.provider.mode})
            if it.opt_out:
                self.store.opt_out(inq["recipient_hash"])
                self.store.update_inquiry(inq["inquiry_id"], status="opted_out")
                self.store.emit("recipient_opted_out", inq["subject_id"], run_id, {"recipient_hash": inq["recipient_hash"]})
                return self._continue(run_id, InquiryTimeout(inq["inquiry_id"], "recipient_opted_out"))
            elapsed = max(0.0, (time.time() - inq["asked_real"]) / 60.0 * self.time_scale)
            ev = InquiryResponse(inq["inquiry_id"], it.answer_id, elapsed, {"kind": m.kind, "method": it.method}, asdict(it), m.wamid, it.needs_review)
            if it.needs_review:
                self.store.update_inquiry(inq["inquiry_id"], payload_json={**json.loads(inq["payload_json"] or "{}"), "needs_review": True, "review": body})
                self.store.emit("needs_human_review", inq["subject_id"], run_id, {"inquiry_id": inq["inquiry_id"], "reason": it.details})
                return self.view_run(run_id)
            self.store.update_inquiry(inq["inquiry_id"], status="answered", answered_real=time.time(), outcome=it.answer_id)
            return self._continue(run_id, ev)

    def resolve_review(self, inquiry_id: str, answer_id: str | None, reviewer: str) -> dict[str, Any]:
        """A human maps an uninterpretable reply to an answer (or declares it unusable). Recorded with the reviewer's identity."""
        inq = self.store.get_inquiry(inquiry_id)
        if inq is None or inq["status"] != "awaiting":
            raise KeyError(inquiry_id)
        valid = {a["id"] for a in iq.spec(inq["spec_id"]).answers}
        if answer_id is not None and answer_id not in valid:
            raise ValueError(f"{answer_id} is not an answer of {inq['spec_id']}")
        with self._lock(inq["run_id"]):
            self.store.emit("review_resolved", inq["subject_id"], inq["run_id"], {"inquiry_id": inquiry_id, "answer": answer_id, "reviewer": reviewer})
            if answer_id is None:
                self.store.update_inquiry(inquiry_id, status="timed_out", outcome=iq.NO_RESPONSE)
                return self._continue(inq["run_id"], InquiryTimeout(inquiry_id, "unusable_reply"))
            elapsed = max(0.0, (time.time() - inq["asked_real"]) / 60.0 * self.time_scale)
            self.store.update_inquiry(inquiry_id, status="answered", answered_real=time.time(), outcome=answer_id)
            return self._continue(inq["run_id"], InquiryResponse(inquiry_id, answer_id, elapsed, {"method": "human_review", "reviewer": reviewer}, {"method": "human_review"}))

    # ── timeouts ──
    def tick(self, now: float | None = None) -> list[str]:
        """Apply the timeout for every overdue inquiry. Called by a background loop; also callable explicitly by tests/UI."""
        done = []
        for inq in self.store.overdue(now or time.time()):
            self.expire(inq["inquiry_id"])
            done.append(inq["inquiry_id"])
        return done

    def expire(self, inquiry_id: str) -> dict[str, Any]:
        inq = self.store.get_inquiry(inquiry_id)
        if inq is None or inq["status"] != "awaiting":
            raise KeyError(inquiry_id)
        with self._lock(inq["run_id"]):
            self.store.update_inquiry(inquiry_id, status="timed_out", outcome=iq.NO_RESPONSE)
            self.store.emit("inquiry_timed_out", inq["subject_id"], inq["run_id"], {"inquiry_id": inquiry_id})
            return self._continue(inq["run_id"], InquiryTimeout(inquiry_id))

    # ── sandbox recipient device ──
    def sandbox_conversations(self) -> list[dict[str, Any]]:
        out = []
        for i in self.store.inquiries_for():
            if i["delivery_mode"] != "sandbox":
                continue
            v = self._inquiry_view(i)
            out.append(v)
        return out

    def sandbox_reply(self, inquiry_id: str, kind: str, *, answer_id: str | None = None, text: str | None = None, lat: float | None = None, lng: float | None = None, wamid: str | None = None) -> dict[str, Any]:
        """Build a Meta-shaped webhook for what a recipient's phone would send, and push it through the REAL webhook path."""
        if self.provider.mode != "sandbox":
            raise RuntimeError("sandbox replies are only available in sandbox mode")
        inq = self.store.get_inquiry(inquiry_id)
        if inq is None:
            raise KeyError(inquiry_id)
        outs = [m for m in self.store.messages_for(inquiry_id) if m["direction"] == "out"]
        ctx = outs[-1]["wamid"] if outs else None
        ts = str(int(time.time()))
        msg: dict[str, Any] = {"from": inq["recipient_ref"], "id": wamid or "wamid.SBXIN" + uuid.uuid4().hex[:20].upper(), "timestamp": ts, **({"context": {"from": "sandbox", "id": ctx}} if ctx else {})}
        if kind == "button":
            ans = next(a for a in json.loads(inq["answers_json"]) if a["id"] == answer_id)
            payload_kind = (outs[-1]["body"].get("payload") or {}).get("type") if outs else "template"
            if payload_kind == "interactive":
                msg.update({"type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": f"{inquiry_id}|{answer_id}", "title": ans["title"]}}})
            else:
                msg.update({"type": "button", "button": {"payload": f"{inquiry_id}|{answer_id}", "text": ans["title"]}})
        elif kind == "text":
            msg.update({"type": "text", "text": {"body": text or ""}})
        elif kind == "location":
            msg.update({"type": "location", "location": {"latitude": lat, "longitude": lng}})
        elif kind == "image":
            msg.update({"type": "image", "image": {"id": "sandbox-media-" + uuid.uuid4().hex[:8], "mime_type": "image/jpeg"}})
        else:
            raise ValueError(kind)
        payload = {"object": "whatsapp_business_account", "entry": [{"id": "SANDBOX", "changes": [{"field": "messages", "value": {"messaging_product": "whatsapp", "messages": [msg]}}]}]}
        return self.handle_webhook(payload, source="sandbox")

    def sandbox_advance(self, wamid: str, status: str) -> dict[str, Any]:
        """Advance a sandbox message through sent/delivered/read by emitting a Meta-shaped status webhook (still NOT a real delivery)."""
        payload = {"object": "whatsapp_business_account", "entry": [{"id": "SANDBOX", "changes": [{"field": "messages", "value": {"messaging_product": "whatsapp",
                   "statuses": [{"id": wamid, "status": status, "timestamp": str(int(time.time())), "recipient_id": "sandbox"}]}}]}]}
        return self.handle_webhook(payload, source="sandbox")

    # ── execution, approvals, outcomes ──
    def execute(self, run_id: str, approved_by: str | None = None, role: str | None = None, action: str | None = None) -> dict[str, Any]:
        rec = self.store.get_run(run_id)
        if rec is None:
            raise KeyError(run_id)
        d = rec["run"]["decision"]
        act = action or d.get("action")
        kind = d.get("type")
        if not act:
            raise ValueError("this decision has no action to execute")
        need = "none" if kind == "auto_eligible" else ("supervisor" if (kind == "escalate" or d.get("approval") == "supervisor") else "analyst")
        rank = {"none": 0, "analyst": 1, "supervisor": 2}
        if rank[need] > 0 and rank.get(role or "none", 0) < rank[need]:
            raise PermissionError(f"executing '{act}' needs {need} approval (got {role or 'none'})")
        from dallal.recovery.ranking import load_catalogue

        spec = load_catalogue()["actions"][act]
        res = self.providers.executor.execute(spec["tool"], rec["subject_id"], {"action": act, "approved_by": approved_by or "policy:auto", "role": role or "policy"})
        led = Ledger(origin=rec["origin"] or "synthetic", scenario_id=rec["scenario_id"])
        ts = pd.Timestamp.now()
        did = led.log_decision(run_id + "-exec", rec["subject_id"], kind, ts, {"executed_action": act}, "policy-v2", decided_by="agent" if kind == "auto_eligible" else role or "analyst")
        aid = led.log_action(run_id + "-exec", rec["subject_id"], act, ts, executed=True, approval=need, assignment="agent" if kind == "auto_eligible" else "human", params={"approved_by": approved_by}, snapshot=did)
        led.log_pending_outcome(aid, did, ts)
        for name, rows in (("decision", led.decisions), ("action", led.actions), ("outcome", led.outcomes)):
            for r in rows:
                self.store.ledger_add(name, r)
        self.store.emit("action_executed", rec["subject_id"], run_id, {"action_id": aid, "action": act, "approved_by": approved_by or "policy:auto", "role": role or "policy", "mode": "simulated",
                                                                      "detail": res.detail, "external_effect": False})
        return {"action_id": aid, "action": act, "status": "executed_simulated", "detail": res.detail, "external_effect": False, "outcome": "pending"}

    def record_outcome(self, action_id: str, kind: str, source: str, note: str = "") -> dict[str, Any]:
        """Outcomes are never produced by the agent. They are reported by an operator / a sandbox recipient / a downstream system."""
        if source in ("agent", "policy"):
            raise PermissionError("the agent cannot report its own outcomes")
        from dallal.data.schema import OutcomeKind

        OutcomeKind(kind)  # validates
        row = {"outcome_id": f"out:{action_id}:{kind}", "action_id": action_id, "decision_id": None, "observed_ts": pd.Timestamp.now(), "kind": kind, "delay_minutes": None, "cost_sar": None,
               "origin": "synthetic", "source_id": "dallal-ops", "source_record_id": source, "adapter_version": "ops-1.0", "scenario_id": "live-demo", "generator_seed": None, "reported_by": source, "note": note}
        self.store.ledger_add("outcome", row)
        self.store.emit("outcome_recorded", None, None, {"action_id": action_id, "kind": kind, "reported_by": source, "note": note})
        return row


class _Guard:
    """Channel wrapper enforcing recipient opt-out before anything is sent."""

    def __init__(self, ch: WhatsAppChannel, store: Store):
        self.ch, self.store = ch, store

    def send_inquiry(self, pending: Any, facts: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
        if self.ch.provider.mode == "sandbox" and pending.target != "recipient":
            self.ch.provider.standing_sessions.add(str(pending.recipient_ref))  # operational contacts: standing session (assumption, listed in /meta)
        if self.store.is_opted_out(wa.hash_ref(pending.recipient_ref)):
            rd = {"mode": self.ch.provider.mode, "status": "refused", "real_delivery": False, "wamid": None, "error": {"message": "recipient opted out", "code": None}}
            self.ch.on_sent(pending, rd, None)
            return rd
        return self.ch.send_inquiry(pending, facts, run_id)


def _run_dict(run: Any) -> dict[str, Any]:
    from dallal.agent.trace import _default

    return json.loads(json.dumps(run.to_dict(), default=_default))
