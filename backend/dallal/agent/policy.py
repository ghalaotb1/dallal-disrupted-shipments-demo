"""Bounded-autonomy decision policy (policy-v1). Deterministic: the LLM cannot override it.

Outcomes: incident | resolved | auto_eligible | recommend | escalate. "auto_eligible" means the policy PERMITS the agent to
act; execution is a separate, logged step. Escalation is the default whenever evidence is insufficient, conflicting or the
action is high-impact: Dallal prefers asking a human to guessing.
"""

from __future__ import annotations

from typing import Any

from dallal.agent.belief import Cause
from dallal.agent.planner import actionable
from dallal.agent.state import CaseState
from dallal.recovery.ranking import load_catalogue
from dallal.tools.builtin import open_question

POLICY_VERSION = "policy-v1"


def decide(state: CaseState) -> dict[str, Any]:
    top, p, margin = state.top_cause()
    ps = state.belief.p_systemic()  # type: ignore[union-attr]
    base: dict[str, Any] = {"policy_version": POLICY_VERSION, "p_systemic": round(ps, 3), "top_cause": top.value, "posterior": round(p, 3)}

    if state.incident is not None:
        inc = state.incident
        return {**base, "type": "incident", "headline": f"Handle as incident on {inc['scope']} {inc['scope_id']}",
                "rationale": f"{inc['observed']} related failures in {30} min vs baseline {inc['baseline_mean']:.1f} (z={inc['z']:.1f}); "
                             f"{len(inc['exposed'])} more shipments exposed. One incident response is faster and safer than case-by-case fixes.",
                "members": inc["members"], "exposed": inc["exposed"], "scope": inc["scope"], "scope_id": inc["scope_id"]}

    if top == Cause.NONE and p >= 0.8:
        return {**base, "type": "resolved", "headline": "No action needed", "rationale": f"Shipment looks healthy ({p:.0%}); monitoring continues."}

    d = state.diagnosis or {}
    if not actionable(state):
        if top == Cause.CUSTODY_ANOMALY:
            reason = "conflicting_evidence"
        elif top == Cause.UNKNOWN or (d.get("agreement") == "inconclusive" and p < 0.55):
            reason = "unknown_pattern"
        else:
            reason = "insufficient_evidence"
        if reason == "conflicting_evidence":
            why = (f"Evidence contradicts itself: the scans point to a custody anomaly ({p:.0%}), so no recovery action is safe until a person "
                   "establishes what actually happened to the parcel.")
        elif reason == "unknown_pattern":
            why = f"No known disruption pattern fits: the leading hypothesis '{top.value}' holds {p:.0%} with margin {margin:.0%}, below the bar to act."
        else:
            why = f"Evidence cannot separate '{top.value}' ({p:.0%}) from the alternatives (margin {margin:.0%}); the agent will not guess."
        return {**base, "type": "escalate", "reason": reason, "headline": "Escalate — the agent will not guess a cause", "rationale": why,
                "question": open_question(state)}

    if not state.ranked_actions or state.policy is None:
        return {**base, "type": "escalate", "reason": "no_eligible_action", "headline": "Escalate — no eligible recovery action",
                "rationale": f"Cause '{top.value}' is clear ({p:.0%}) but no action's preconditions are met.", "question": open_question(state)}

    act, pol = state.ranked_actions[0], state.policy
    common = {**base, "action": act["kind"], "action_title": act["title"], "approval": act["approval"], "gates": pol["failed_checks"]}
    lim = load_catalogue()["limits"]
    if pol["auto_eligible"]:
        return {**common, "type": "auto_eligible", "headline": f"Eligible for automated action: {act['title']}",
                "rationale": f"{top.value} at {p:.0%} (≥ {lim['auto_confidence_min']:.0%}); action is reversible/low-impact and within value and attempt limits."}
    if d.get("agreement") == "conflicts" and ((state.facts or {}).get("value") or 0) > lim["auto_value_max_sar"]:
        # A human-recorded code that the evidence contradicts, on a parcel above the auto-value bound: a person must settle
        # which record is right before anything is done to the parcel.
        return {**common, "type": "escalate", "reason": "conflicting_evidence", "headline": "Escalate — recorded code contradicts the evidence on a high-value parcel",
                "rationale": f"Recorded '{d.get('recorded_code')}' vs evidence for '{top.value}' ({p:.0%}); value SAR {(state.facts or {}).get('value'):,.0f} "
                             f"is above the SAR {lim['auto_value_max_sar']:,} autonomy bound.",
                "question": f"Is the recorded '{d.get('recorded_code')}' correct, or does the evidence for '{top.value}' stand? (proposed: {act['title']})"}
    if act["approval"] == "supervisor":
        return {**common, "type": "escalate", "reason": "high_impact", "headline": f"Escalate — supervisor must approve: {act['title']}",
                "rationale": f"Top action needs supervisor approval ({act['approval_reason']}).", "question": f"Approve '{act['title']}' for {state.subject_id}?"}
    note = " Recorded code conflicts with the evidence." if d.get("agreement") == "conflicts" else ""
    return {**common, "type": "recommend", "headline": f"Recommended: {act['title']}",
            "rationale": f"{top.value} at {p:.0%}. {act['approval_reason'] or '; '.join(pol['failed_checks'])}.{note}"}
