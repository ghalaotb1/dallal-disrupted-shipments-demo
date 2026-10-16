"""Adapter: backend AgentRun -> the `AgentRun` shape in types/domain.ts, so the existing UI can render a real run unchanged.

Tool names the UI does not yet know (`get_recipient_context`, `get_facility_context`, `get_pickup_context`) are mapped to the
nearest existing ToolName; the real name is preserved in `args`. Widening the UI union is a small, optional frontend change.
"""

from __future__ import annotations

from typing import Any

from dallal.agent.trace import AgentRun

UI_TOOL = {"get_recipient_context": "get_address_context", "get_facility_context": "get_route_context", "get_pickup_context": "get_route_context"}
UI_KIND = {"read": "read", "analysis": "analysis", "action": "action"}
READ = {"get_shipment", "get_journey", "get_address_context", "get_recipient_context", "get_route_context", "get_facility_context",
        "get_pickup_context", "retrieve_policy_constraints"}
UI_STATUS = {"ok": "ok", "warn": "warn", "alert": "alert"}
UI_REASON = {"high_impact": "high_impact", "conflicting_evidence": "conflicting_evidence", "unknown_pattern": "unknown_pattern",
             "insufficient_evidence": "unknown_pattern", "no_eligible_action": "high_impact", "delegation_preferred": "high_impact"}


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
                   "rationale": d["rationale"], "question": d.get("question", ""), **({"actionId": d["action"]} if d.get("action") else {})}
    elif d["type"] in ("auto_eligible", "recommend"):
        outcome = {"type": d["type"], "actionId": d["action"], "headline": d["headline"], "rationale": d["rationale"]}
    else:
        outcome = {"type": "resolved", "headline": d.get("headline", "No action needed"), "rationale": d.get("rationale", "")}
    return {"id": run.run_id, "shipmentId": run.subject_id, "mode": "investigation", "trigger": "analyst", "status": "running" if run.status == "awaiting_response" else "completed",
            "backendStatus": run.status, "startedAt": started_at_ms, "finishedAt": None if run.status == "awaiting_response" else t, "steps": steps, "outcome": outcome,
            "diagnosis": run.diagnosis, "actions": run.actions,
            "backend": {"engine": run.engine, "planner": run.planner, "model_basis": run.model_basis, "data_origin": run.data_origin, "scenario_id": run.scenario_id,
                        "decision": {k: d.get(k) for k in ("type", "reason", "action", "top_cause", "posterior", "p_systemic", "expected_utility", "decision_stability", "chosen_option")},
                        "utility_table": run.utility_table, "virtual_minutes": run.virtual_minutes, **(live or {})}}
