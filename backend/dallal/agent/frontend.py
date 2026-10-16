"""Adapter: backend AgentRun -> the `AgentRun` shape in types/domain.ts, so the existing UI can render a real run unchanged.

Tool names the UI does not yet know (`get_recipient_context`, `get_facility_context`, `get_pickup_context`) are mapped to the
nearest existing ToolName; the real name is preserved in `args`. Widening the UI union is a small, optional frontend change.
"""

from __future__ import annotations

from typing import Any

from dallal.agent.trace import AgentRun

UI_TOOL: dict[str, str] = {}  # every backend tool now has a UI name; no aliasing (an aliased trace would misreport what ran)
UI_KIND = {"read": "read", "analysis": "analysis", "action": "action"}
READ = {"get_shipment", "get_journey", "get_address_context", "get_recipient_context", "get_route_context", "get_facility_context",
        "get_pickup_context", "retrieve_policy_constraints"}
UI_STATUS = {"ok": "ok", "warn": "warn", "alert": "alert"}
UI_REASON = {"high_impact": "high_impact", "conflicting_evidence": "conflicting_evidence", "unknown_pattern": "unknown_pattern",
             "insufficient_evidence": "unknown_pattern", "no_eligible_action": "high_impact", "delegation_preferred": "high_impact"}


CAUSE_LABEL = {"address_issue": "Address quality issue", "recipient_unavailable": "Recipient unavailable", "attempt_not_completed": "Attempt not physically completed",
               "route_disruption": "Route disruption", "facility_backlog": "Facility backlog", "pickup_point_unavailable": "Pickup point unavailable",
               "custody_anomaly": "Unexplained custody pattern", "none": "No disruption signal", "unknown": "Unknown pattern"}
BASIS = {"data": "rule", "rule": "rule", "assumption": "assumption", "simulated": "simulated"}


def _ui_diagnosis(run: AgentRun) -> dict[str, Any] | None:
    d = run.diagnosis
    if not d:
        return None
    cause = d["cause"]
    ev = [{"id": e["id"], "label": e["label"], "detail": e["detail"] or "", "stance": e["stance"], "source": e["source_tool"]} for e in run.evidence]
    agree = d["agreement"]
    headline = {"agrees": f"Evidence agrees with the recorded code: {CAUSE_LABEL.get(cause, cause).lower()}", "conflicts": "Evidence conflicts with the recorded code",
                "no_code": f"No code recorded; evidence points to {CAUSE_LABEL.get(cause, cause).lower()}", "inconclusive": "Evidence is inconclusive"}[agree]
    summary = f"Leading cause '{CAUSE_LABEL.get(cause, cause)}' at {d['posterior']:.0%} (margin {d['margin']:.0%}); runner-up {d['runner_up'][0]} {d['runner_up'][1]:.0%}."
    out = {"headline": headline, "summary": summary, "cause": cause, "causeLabel": CAUSE_LABEL.get(cause, cause), "confidence": d["confidence"], "agreement": agree, "evidence": ev}
    if d.get("recorded_code"):
        out["recorded"] = {"code": d["recorded_code"], "label": d["recorded_code"].replace("_", " ").title()}
    return out


def _ui_actions(run: AgentRun) -> list[dict[str, Any]]:
    out = []
    for a in run.actions:
        urgency = "high" if a.get("minutes_to_effect", 99) <= 30 else "medium" if a.get("minutes_to_effect", 99) <= 90 else "low"
        out.append({"id": f"{run.run_id}:{a['kind']}", "kind": a["kind"], "title": a["title"], "reason": a.get("approval_reason") or f"Best fit by {a.get('method', 'expected utility').replace('_', ' ')}",
                    "tool": a.get("tool") or "escalate_case", "rank": a["rank"], "fit": a["fit"], "urgency": urgency, "impact": a["impact"], "reversible": a["reversible"],
                    "approval": a["approval"], **({"approvalReason": a["approval_reason"]} if a.get("approval_reason") else {}), "automatable": a["automatable"],
                    "factors": [{"label": f["label"], "value": f["value"], "basis": BASIS.get(f["basis"], "assumption")} for f in a.get("factors", [])], "score": a["score"]})
    return out


def to_frontend(run: AgentRun, started_at_ms: int = 0, live: dict[str, Any] | None = None) -> dict[str, Any]:
    """Backend run -> the UI's AgentRun. v2 additions: questions to people appear as `ask_inquiry` steps (kind 'inquiry') and a paused run
    has status 'awaiting_response'. Everything the UI needs to render honestly (delivery mode, data origin) is carried in `live`."""
    t = started_at_ms
    steps = []
    inquiries = {i.get("inquiry_id"): i for i in run.inquiries}
    for s in run.steps:
        is_ask = s["tool"].startswith("ask:")
        base = {"id": f"{run.run_id}-s{s['index']}", "tool": "ask_inquiry" if is_ask else UI_TOOL.get(s["tool"], s["tool"]), "args": f'backend_tool="{s["tool"]}"',
                "checking": s["why"], "kind": "inquiry" if is_ask else "read" if s["tool"] in READ else "action" if s["tool"] == "escalate_case" else "analysis",
                "status": UI_STATUS.get(s["status"], "ok"), "summary": s["summary"], "facts": s["facts"][:4], "startedAt": t, "durationMs": int(max(s["duration_ms"], 1))}
        if is_ask:
            iid = (s.get("args") or {}).get("inquiry_id")
            base["inquiryId"] = iid
            base["target"] = (s.get("args") or {}).get("to")
            base["inquiryStatus"] = (inquiries.get(iid) or {}).get("status", "awaiting_response")
        if s.get("belief_after"):
            base["belief"] = s["belief_after"]
        base["backendTool"] = s["tool"]
        steps.append(base)
        t += 1000
    d = run.decision
    if run.status == "awaiting_response":
        outcome = None
    elif d["type"] == "incident":
        outcome = {"type": "incident", "incidentId": f"{d['scope']}:{d['scope_id']}", "headline": d["headline"], "rationale": d["rationale"]}
    elif d["type"] == "escalate":
        outcome = {"type": "escalate", "reason": UI_REASON.get(d.get("reason", ""), "unknown_pattern"), "headline": d["headline"],
                   "rationale": d["rationale"], "question": d.get("question", ""), **({"actionId": f"{run.run_id}:{d['action']}"} if d.get("action") else {})}
    elif d["type"] in ("auto_eligible", "recommend"):
        outcome = {"type": d["type"], "actionId": f"{run.run_id}:{d['action']}", "headline": d["headline"], "rationale": d["rationale"]}
    else:
        outcome = {"type": "resolved", "headline": d.get("headline", "No action needed"), "rationale": d.get("rationale", "")}
    return {"id": run.run_id, "shipmentId": run.subject_id, "mode": "investigation", "trigger": "analyst", "status": "running" if run.status == "awaiting_response" else "completed",
            "backendStatus": run.status, "startedAt": started_at_ms, "finishedAt": None if run.status == "awaiting_response" else t, "steps": steps, "outcome": outcome,
            "diagnosis": _ui_diagnosis(run), "actions": _ui_actions(run),
            "backend": {"engine": run.engine, "planner": run.planner, "model_basis": run.model_basis, "data_origin": run.data_origin, "scenario_id": run.scenario_id,
                        "decision": {k: d.get(k) for k in ("type", "reason", "action", "top_cause", "posterior", "p_systemic", "expected_utility", "decision_stability", "chosen_option")},
                        "utility_table": run.utility_table, "virtual_minutes": run.virtual_minutes, **(live or {})}}
