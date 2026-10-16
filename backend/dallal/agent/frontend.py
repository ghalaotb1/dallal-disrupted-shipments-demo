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
             "insufficient_evidence": "unknown_pattern", "no_eligible_action": "high_impact"}


def to_frontend(run: AgentRun, started_at_ms: int = 0) -> dict[str, Any]:
    t = started_at_ms
    steps = []
    for s in run.steps:
        steps.append({
            "id": f"{run.run_id}-s{s['index']}", "tool": UI_TOOL.get(s["tool"], s["tool"]), "args": f'backend_tool="{s["tool"]}"',
            "checking": s["why"], "kind": "read" if s["tool"] in READ else "action" if s["tool"] == "escalate_case" else "analysis",
            "status": UI_STATUS.get(s["status"], "ok"), "summary": s["summary"], "facts": s["facts"][:4], "startedAt": t,
            "durationMs": int(max(s["duration_ms"], 1)),
        })
        t += 1000
    d = run.decision
    if d["type"] == "incident":
        outcome = {"type": "incident", "incidentId": f"{d['scope']}:{d['scope_id']}", "headline": d["headline"], "rationale": d["rationale"]}
    elif d["type"] == "escalate":
        outcome = {"type": "escalate", "reason": UI_REASON.get(d.get("reason", ""), "unknown_pattern"), "headline": d["headline"],
                   "rationale": d["rationale"], "question": d.get("question", ""), **({"actionId": d["action"]} if d.get("action") else {})}
    elif d["type"] in ("auto_eligible", "recommend"):
        outcome = {"type": d["type"], "actionId": d["action"], "headline": d["headline"], "rationale": d["rationale"]}
    else:
        outcome = {"type": "resolved", "headline": d["headline"], "rationale": d["rationale"]}
    return {"id": run.run_id, "shipmentId": run.subject_id, "mode": "investigation", "trigger": "auto", "status": "completed",
            "startedAt": started_at_ms, "finishedAt": t, "steps": steps, "outcome": outcome,
            "backend": {"planner": run.planner, "model_basis": run.model_basis, "data_origin": run.data_origin, "scenario_id": run.scenario_id}}
