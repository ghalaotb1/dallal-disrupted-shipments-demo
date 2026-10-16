"""v2 decision policy: choose the option with the highest expected utility, then apply bounded-autonomy gates (policy-v2).

The decision type vocabulary is unchanged (incident / resolved / auto_eligible / recommend / escalate) so the trace format, the
frontend adapter and the ledger keep working. What changes is HOW the decision is reached: by expected utility under the full
belief (including table uncertainty), with the autonomy gate evaluated in the pessimistic tail rather than at the mean.
"""

from __future__ import annotations

from typing import Any

from dallal.agent.belief import Cause
from dallal.agent.v2.state import CaseStateV2
from dallal.agent.v2.tools import autonomy_check, case_options
from dallal.agent.v2.utility import best_option, utility_table
from dallal.recovery.ranking import load_catalogue
from dallal.tools.builtin import open_question

POLICY_VERSION = "policy-v2"


def particle_agreement(state: CaseStateV2, opts, stk, best_name: str) -> float:
    pk = state.belief.particle_cause()
    w = state.belief.weights()
    return float(sum(w[k] for k in range(pk.shape[0]) if best_option(opts, pk[k], stk)[0].name == best_name))


def model_risk(state: CaseStateV2) -> dict[str, Any] | None:
    """The trained model's result for this case if (and only if) a trained model actually scored it; None when the heuristic or an abstention was all there was."""
    for c in state.calls:
        if c.tool == "predict_risk":
            r = (getattr(c, "data", None) or {}).get("risk") or {}
            return r if r.get("source") == "model" else None
    return None


def decide(state: CaseStateV2, world: Any) -> dict[str, Any]:
    b = state.belief
    top, p, margin = b.top()
    ps = b.p_systemic()
    opts, stk = case_options(state, world)
    pcv = b.p_cause_vec()
    best, eu = best_option(opts, pcv, stk)
    table = utility_table(opts, pcv, stk)
    stab = particle_agreement(state, opts, stk, best.name)
    state.utility_table, state.stability = table, stab
    n_support = sum(1 for e in state.evidence if e.stance == "supports" and e.cause == top.value)
    base = {"policy_version": POLICY_VERSION, "n_support": n_support, "p_unknown": round(float(b.p_cause().get(Cause.UNKNOWN, 0.0)), 4), "p_systemic": round(ps, 3), "top_cause": top.value, "posterior": round(p, 3), "expected_utility": round(eu, 2),
            "chosen_option": best.name, "decision_stability": round(stab, 3), "utility_table": table[:6], "minutes_elapsed": round(state.virtual_min, 1)}

    if state.incident is not None:
        inc = state.incident
        return {**base, "type": "incident", "headline": f"Handle as incident on {inc['scope']} {inc['scope_id']}",
                "rationale": f"{inc['observed']} related failures in 30 min vs baseline {inc['baseline_mean']:.1f} (z={inc['z']:.1f}); {len(inc['exposed'])} more shipments exposed. "
                             "One coordinated response beats case-by-case fixes.", "members": inc["members"], "exposed": inc["exposed"], "scope": inc["scope"], "scope_id": inc["scope_id"]}

    d = state.diagnosis or {}
    lim = load_catalogue()["limits"]
    if best.kind == "wait":
        why = f"Expected utility is highest when waiting ({eu:.1f} SAR-eq); no intervention is worth its cost and delay."
        mr = model_risk(state)
        if mr and mr.get("band") in ("elevated", "high") and state.trigger.get("kind") in ("slow_task_watch", "risk_screen", "route_plan_screen"):
            return {**base, "type": "resolved", "watch": True, "risk_flag": {"band": mr["band"], "probability": mr.get("probability"), "model": (mr.get("meta") or {}).get("target")},
                    "headline": f"At risk per trained model ({mr['band']}) - monitor closely; no recoverable cause is evidenced yet",
                    "rationale": f"{mr['drivers'][0]['label']}. {why} The model ranks risk on its source population; it does not name a cause, so no action is taken."}
        return {**base, "type": "resolved", "headline": "No action needed" if top == Cause.NONE else "Monitor - no intervention justified", "rationale": why}

    if best.kind == "escalate" and top not in (Cause.UNKNOWN, Cause.CUSTODY_ANOMALY) and p >= lim["diagnose_min_posterior"]:
        acts = [r for r in table if r["option"] not in ("escalate", "wait")]
        alt = f"; best automated/approvable alternative is '{acts[0]['option']}' at {acts[0]['eu']:.1f}" if acts else "; no eligible alternative action"
        return {**base, "type": "escalate", "reason": "delegation_preferred", "headline": "Escalate - delegating to the supervisor has the highest expected utility",
                "rationale": f"Cause '{top.value}' is named ({p:.0%}) but expected utility is highest ({eu:.1f} SAR-eq) when a supervisor decides{alt}.",
                "question": f"Which recovery action should be taken for {state.subject_id} ({top.value})?"}
    if best.kind == "escalate":
        if top == Cause.CUSTODY_ANOMALY:
            reason = "conflicting_evidence"
        elif top == Cause.UNKNOWN or (d.get("agreement") == "inconclusive" and p < 0.55):
            reason = "unknown_pattern"
        else:
            reason = "insufficient_evidence"
        why = {"conflicting_evidence": f"Evidence contradicts itself (custody anomaly {p:.0%}); no recovery action is safe until a person establishes what happened.",
               "unknown_pattern": f"No known disruption pattern fits: '{top.value}' holds {p:.0%} (margin {margin:.0%}).",
               "insufficient_evidence": f"Evidence cannot separate '{top.value}' ({p:.0%}) from the alternatives; the agent will not guess."}[reason]
        return {**base, "type": "escalate", "reason": reason, "headline": "Escalate - the agent will not guess a cause", "rationale": why, "question": open_question(state)}

    act = state.ranked_actions[0] if state.ranked_actions else None
    opt = next((o for o in opts if o.name == best.name), best)
    ok, failed, robust = autonomy_check(state, opt, d.get("agreement", "inconclusive"))
    common = {**base, "action": opt.name, "action_title": opt.title, "approval": opt.approval, "gates": failed, "robust_effectiveness": round(robust, 3)}
    if ok:
        return {**common, "type": "auto_eligible", "headline": f"Eligible for automated action: {opt.title}",
                "rationale": f"Best option by expected utility ({eu:.1f} SAR-eq); effective in the pessimistic tail with {robust:.0%} (>= {params_min():.0%}); within value, attempt and reversibility bounds."}
    value = (state.facts or {}).get("value") or 0
    if d.get("agreement") == "conflicts" and value > lim["auto_value_max_sar"]:
        return {**common, "type": "escalate", "reason": "conflicting_evidence", "headline": "Escalate - recorded code contradicts the evidence on a high-value parcel",
                "rationale": f"Recorded '{d.get('recorded_code')}' vs evidence for '{top.value}' ({p:.0%}); value SAR {value:,.0f} exceeds the SAR {lim['auto_value_max_sar']:,} autonomy bound.",
                "question": f"Is the recorded '{d.get('recorded_code')}' correct, or does the evidence for '{top.value}' stand? (proposed: {opt.title})"}
    if opt.approval == "supervisor":
        return {**common, "type": "escalate", "reason": "high_impact", "headline": f"Escalate - supervisor must approve: {opt.title}",
                "rationale": f"Best option ({opt.title}) needs supervisor approval.", "question": f"Approve '{opt.title}' for {state.subject_id}?"}
    note = " Recorded code conflicts with the evidence." if d.get("agreement") == "conflicts" else ""
    return {**common, "type": "recommend", "headline": f"Recommended: {opt.title}",
            "rationale": f"{top.value} at {p:.0%}; best option by expected utility. {(act or {}).get('approval_reason') or '; '.join(failed)}.{note}"}


def params_min() -> float:
    from dallal.agent.v2.utility import params

    return params()["autonomy"]["robust_effectiveness_min"]


