"""Coordinated recovery plans: lifecycle, shared-evidence inquiry, approval and execution.

A plan covers every affected/exposed shipment of ONE incident. Evidence is bought once at the incident level (one question to the dispatcher),
and its answer re-shapes the plan for all parcels. Approval is also collective: a supervisor approves or rejects the plan as a whole
(group reroute / spare dispatch / pickup redirects affect several recipients and shared capacity).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import pandas as pd

from dallal.agent.ledger import Ledger
from dallal.agent.v2 import inquiry as iq
from dallal.agent.v2.events import InquiryResponse, InquiryTimeout
from dallal.agent.v2.state import PendingInquiry
from dallal.agent.v2.utility import params
from dallal.channels import whatsapp as wa
from dallal.recovery import network as N

OPTION_TEXT = {"wait": "Hold on the current route and wait for the blockage to clear", "reroute": "Reroute the van via the alternative corridor", "defer": "Defer to the next delivery wave with notice"}


def problem_from_snapshot(snap: dict[str, Any]) -> N.Problem:
    res = snap.get("resources", {})
    alt = res.get("alt", {})
    parcels = [N.Parcel(p["id"], p["van"], float(p["value"]), float(p["slackMin"]), float(p["remainingMin"]), p.get("service", "Standard"), bool(p.get("exposed", False)),
                        bool(p.get("pickupOk", True)), bool(p.get("reachable", True))) for p in snap["parcels"]]
    return N.Problem(parcels, [N.Spare(s["id"], float(s["etaMin"]), int(s["capacity"]), float(s.get("fixedCost", 40))) for s in res.get("spares", [])],
                     [N.PickupPoint(k["id"], float(k["travelMin"]), int(k["capacity"]), bool(k.get("online", True))) for k in res.get("pickups", [])],
                     bool(alt.get("available", True)), float(alt.get("extraMin", 40)), short_min=float(snap.get("shortMin", 15)), long_min=float(snap.get("longMin", 100)))


def describe_option(o: str, pr: N.Problem) -> str:
    if o.startswith("spare:"):
        return f"Reassign to spare courier {o.split(':')[1]}"
    if o.startswith("pickup:"):
        return f"Redirect to pickup point {o.split(':')[1]}"
    return OPTION_TEXT[o]


class PlanOps:
    def __init__(self, svc: Any):
        self.svc = svc
        self.store = svc.store

    # ── create ──
    def create(self, snap: dict[str, Any], lang: str = "ar") -> dict[str, Any]:
        plan_id = f"plan-{uuid.uuid4().hex[:8]}"
        pr = problem_from_snapshot(snap)
        p_long = float(snap.get("belief", {}).get("pLong", 0.35))
        spec = iq.spec("ask_corridor_status")
        p_resp, lat, cost = iq.response_prob(spec, {}), iq.expected_latency_min(spec), iq.cost_sar(spec, {})
        voi = N.cluster_inquiry_value(pr, p_long, p_response=p_resp, latency_min=lat, cost_sar=cost)
        contactable = bool(snap.get("dispatcherContactable", True))
        ask = contactable and voi["net"] >= params()["autonomy"]["min_net_voi_sar"]
        plan = {"plan_id": plan_id, "incident": {"id": snap.get("incidentId"), "scope": snap.get("scope"), "scope_id": snap.get("scopeId")}, "now": snap.get("now"), "lang": lang,
                "problem": snap, "p_long_prior": p_long, "p_long": p_long, "evidence": {"asked": ask, "voi": {k: v for k, v in voi.items() if k != "by_answer"}, "by_answer": voi["by_answer"],
                                                                                          "p_response": p_resp, "expected_latency_min": lat, "contactable": contactable,
                                                                                          "reason": ("value of one shared question is positive" if ask else "decision would not change enough to justify asking (or no dispatcher contact)")},
                "status": "awaiting_evidence" if ask else "ready", "commit_now": voi["committed_now"] if ask else {}}
        self._refresh(plan, pr, p_long)
        self.store.save_plan(plan_id, snap.get("scopeId") or "incident", plan["status"], plan)
        self.store.emit("plan_created", snap.get("scopeId"), plan_id, {"incident_id": snap.get("incidentId"), "plan_id": plan_id, "status": plan["status"], "parcels": len(pr.parcels), "asks_dispatcher": ask, "net_voi": round(voi["net"], 2)})
        if ask:
            self._ask(plan_id, snap, spec, p_resp, voi["net"], lang)
        return self.view(plan_id)

    def _refresh(self, plan: dict[str, Any], pr: N.Problem, p_long: float) -> None:
        """Re-solve for the current belief and attach the coordinated-vs-independent comparison (messages included)."""
        committed = plan.get("commit_now") or {}
        sol = N.solve(pr, p_long)
        cmp = N.compare(pr, p_long)
        n = len(pr.parcels)
        ind_msgs = n if not plan["evidence"]["asked"] else n + n  # each independent agent notifies its recipient and (if it asks) buys the same answer separately
        plan["solution"] = {"assignments": sol.assignments, "reroute_vans": sol.reroute_vans, "spares_used": sol.spares_used, "objective": round(sol.objective, 2), "solve_ms": round(sol.solve_ms, 1),
                            "per_parcel": {pid: {"option": o, "text": describe_option(o, pr), "expected_utility": round(sol.utilities[pid], 1)} for pid, o in sol.assignments.items()},
                            "committed_now": committed}
        plan["comparison"] = {"coordinated_utility": round(cmp["coordinated"]["utility"], 1), "independent_utility": round(cmp["independent"]["utility"], 1), "gain": round(cmp["utility_gain"], 1),
                              "independent_capacity_requests_over_cap": cmp["independent"]["capacity_requests_over_cap"], "independent_conflicting_van_decisions": cmp["independent"]["conflicting_van_decisions"],
                              "messages_coordinated": n + (1 if plan["evidence"]["asked"] else 0), "messages_independent_equivalent": ind_msgs, "assumption": "scored at the belief-weighted blockage duration"}
        plan["approval"] = {"required": "supervisor", "why": "group reroute / spare dispatch / pickup redirects affect several recipients and shared capacity"}

    def _ask(self, plan_id: str, snap: dict[str, Any], spec: iq.InquirySpec, p_resp: float, net: float, lang: str) -> None:
        corridor = snap.get("scopeId") or ""
        facts = {"corridor_id": corridor}
        inquiry_id = f"inq-{plan_id}-1"
        pend = PendingInquiry(inquiry_id, spec.id, iq.variant_name(spec.id, p_resp), spec.target, spec.scope, lang, iq.render_question(spec, facts, lang), iq.answer_labels(spec, lang), spec.raw["mode"],
                              spec.raw.get("template"), 0.0, float(spec.raw["response"]["timeout_min"]), p_resp, f"dispatch:{corridor}", {}, round(net, 3), False, iq.render_question(spec, facts, "en"))
        pend.receipt = self.svc._guard_send(pend, facts)
        now = time.time()
        self.store.save_inquiry(inquiry_id=inquiry_id, run_id=plan_id, spec_id=spec.id, target=spec.target, scope=spec.scope, recipient_hash=wa.hash_ref(pend.recipient_ref), recipient_ref=pend.recipient_ref,
                                delivery_mode=pend.receipt.get("mode"), status="awaiting", asked_real=now, deadline_real=now + (self.svc.hold_expiry_s if pend.receipt.get("status") == "held_for_approval" else pend.timeout_min * 60.0 / self.svc.time_scale), answered_real=None, outcome=None,
                                question=pend.question, answers_json=pend.answers, payload_json={"receipt": pend.receipt, "net_voi_at_ask": net, "p_response": p_resp, "mode": pend.mode, "template": pend.template,
                                                                                                  "question_en": pend.question_en, "timeout_min": pend.timeout_min}, subject_id=snap.get("scopeId"))
        self.store.emit("inquiry_held" if pend.receipt.get("status") == "held_for_approval" else "inquiry_sent", snap.get("scopeId"), plan_id, {"inquiry_id": inquiry_id, "target": spec.target, "spec": spec.id, "question": pend.question, "receipt": pend.receipt,
                                                                       "timeout_min": pend.timeout_min, "net_voi": round(net, 2), "scope": "incident"})
        if pend.receipt.get("status") == "refused":
            self.store.update_inquiry(inquiry_id, status="send_refused")
            self.resume(plan_id, InquiryTimeout(inquiry_id, "send_refused"))

    # ── resume on answer / timeout ──
    def resume(self, plan_id: str, ev: InquiryResponse | InquiryTimeout) -> dict[str, Any]:
        rec = self.store.get_plan(plan_id)
        plan = rec["plan"]
        pr = problem_from_snapshot(plan["problem"])
        if plan["status"] != "awaiting_evidence":
            return self.view(plan_id)
        p_long = plan["p_long_prior"]
        if isinstance(ev, InquiryResponse) and ev.answer_id:
            p_long = N.posterior_long(p_long, ev.answer_id)
            plan["evidence"]["answer"] = {"id": ev.answer_id, "elapsed_min": round(ev.elapsed_min, 1), "posterior_long": round(p_long, 3)}
        else:
            plan["evidence"]["answer"] = {"id": None, "note": "no usable answer - planning on the prior"}
        plan["p_long"], plan["status"] = p_long, "ready"
        self._refresh(plan, pr, p_long)
        self.store.save_plan(plan_id, rec["scope"], "ready", plan)
        self.store.emit("plan_ready", rec["scope"], plan_id, {"incident_id": plan["incident"]["id"], "plan_id": plan_id, "answer": plan["evidence"]["answer"], "objective": plan["solution"]["objective"], "p_long": round(p_long, 3)})
        return self.view(plan_id)

    # ── approval and execution ──
    def decide(self, plan_id: str, decision: str, by: str, role: str, note: str = "") -> dict[str, Any]:
        rec = self.store.get_plan(plan_id)
        if rec is None:
            raise KeyError(plan_id)
        plan = rec["plan"]
        if plan["status"] not in ("ready", "awaiting_evidence"):
            raise ValueError(f"plan is {plan['status']}")
        if role != "supervisor":
            raise PermissionError("a coordinated plan needs supervisor approval")
        if decision == "reject":
            plan["status"] = "rejected"
            self.store.save_plan(plan_id, rec["scope"], "rejected", plan, decided_by=by)
            self.store.emit("plan_rejected", rec["scope"], plan_id, {"incident_id": plan["incident"]["id"], "plan_id": plan_id, "by": by, "note": note})
            return self.view(plan_id)
        if plan["status"] == "awaiting_evidence":
            raise ValueError("the shared question has not been answered yet; approve after the plan is ready (or let it time out)")
        led = Ledger(origin="demo", scenario_id=f"plan:{plan_id}")
        ts = pd.Timestamp.now()
        did = led.log_decision(plan_id, plan["incident"]["scope_id"] or plan_id, "recommend", ts, {"plan": plan["solution"]["objective"], "p_long": plan["p_long"]}, "policy-v2", decided_by="supervisor")
        executed = []
        for pid, o in plan["solution"]["assignments"].items():
            kind = {"wait": "retry_delivery", "reroute": "reroute", "defer": "retry_delivery"}.get(o, "reassign_courier" if o.startswith("spare") else "redirect_pickup")
            aid = led.log_action(f"{plan_id}-{pid}", pid, kind, ts, executed=True, approval="supervisor", assignment="human", params={"plan_id": plan_id, "option": o, "approved_by": by}, snapshot=did)
            led.log_pending_outcome(aid, did, ts)
            executed.append({"parcel": pid, "action_id": aid, "option": o})
        for name, rows in (("decision", led.decisions), ("action", led.actions), ("outcome", led.outcomes)):
            for r in rows:
                self.store.ledger_add(name, r)
        plan["status"], plan["executed"] = "executed_simulated", executed
        self.store.save_plan(plan_id, rec["scope"], "executed_simulated", plan, decided_by=by)
        self.store.emit("plan_executed", rec["scope"], plan_id, {"incident_id": plan["incident"]["id"], "plan_id": plan_id, "by": by, "parcels": len(executed), "mode": "simulated", "external_effect": False})
        return self.view(plan_id)

    def view(self, plan_id: str) -> dict[str, Any]:
        rec = self.store.get_plan(plan_id)
        if rec is None:
            raise KeyError(plan_id)
        plan = json.loads(json.dumps(rec["plan"], default=str))
        plan["status"] = rec["status"]
        plan["inquiries"] = [self.svc._inquiry_view(i) for i in self.store.inquiries_for(run_id=plan_id)]
        plan["live"] = {"backend": True, "whatsapp_mode": self.svc.provider.mode, "scored_with": "expert-assumption utilities (utility-v1)"}
        return plan
