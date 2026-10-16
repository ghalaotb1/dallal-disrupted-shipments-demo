"""The Dallal tool set. Names match ToolName in types/domain.ts where one exists; `get_recipient_context`,
`get_facility_context` and `get_pickup_context` are backend additions (the frontend adapter maps them to the nearest
existing tool until the UI union is widened).

Information tools return a discrete `outcome` that updates the agent's belief. Analysis tools reconcile and rank. The
LLM never computes any number here; it only chooses which tool to call next and explains the result.
"""

from __future__ import annotations

from typing import Any

from dallal.agent.belief import CODE_TO_CAUSE, Cause
from dallal.agent.state import CaseState
from dallal.recovery import ranking
from dallal.tools import signals as sg
from dallal.tools.base import ToolContext, ToolRegistry, ToolResult, ToolSpec

SHIPMENT_ARG = {"type": "object", "properties": {"shipment_id": {"type": "string"}}, "required": ["shipment_id"]}
NO_ARGS = {"type": "object", "properties": {}}


def _prov(ctx: ToolContext, **extra: Any) -> dict[str, Any]:
    f = ctx.state.facts or {}
    return {"data_origin": f.get("origin"), "scenario_id": f.get("scenario_id"), **extra}


# ── read ──────────────────────────────────────────────────────────────────────────────────────────────────────────────
def get_shipment(ctx: ToolContext, args: dict) -> ToolResult:
    facts = sg.shipment_facts(ctx.world, args.get("shipment_id") or ctx.state.subject_id)
    pay = f"COD SAR {facts['cod_amount']:,.0f}" if facts["cod_amount"] else "Prepaid"
    lines = [f"{facts['service_level']} · {pay}" + (f" · value SAR {facts['value']:,.0f}" if facts["value"] else ""),
             f"recorded exception: {facts['recorded_code']}" if facts["recorded_code"] else "no exception recorded",
             f"{facts['failed_attempts']} failed attempt(s) so far"]
    return ToolResult("ok", f"{facts['shipment_id']} loaded", lines, data={"facts": facts},
                      provenance={"data_origin": facts["origin"], "scenario_id": facts["scenario_id"]})


def get_journey(ctx: ToolContext, args: dict) -> ToolResult:
    j = sg.journey_signals(ctx.world, ctx.state.subject_id)
    if j["sequence_conflict"]:
        out, status, summ = "sequence_conflict", "alert", "Conflicting custody scans"
        facts = [j["conflict_detail"]]
    elif j["stalled"]:
        out, status, summ = "stalled", "warn", f"No scan for {j['hours_since_scan']:.1f} h"
        facts = [f"last scan {j['hours_since_scan']:.1f} h before decision time (stall threshold {sg.STALL_HOURS:.0f} h)"]
    elif j["failed_attempts"]:
        out, status, summ = "failed_attempt_logged", "warn", f"{j['failed_attempts']} failed attempt(s) logged"
        facts = [f"{e['ts']:%H:%M} failed attempt ({e['raw_code']})" for e in j["failed_events"][-3:]]
    else:
        out, status, summ, facts = "clean", "ok", f"{j['n_events']} events, no failures", ["scan sequence follows the expected order"]
    return ToolResult(status, summ, facts, outcome=out, data={"journey": j}, provenance=_prov(ctx))


def get_address_context(ctx: ToolContext, args: dict) -> ToolResult:
    a = sg.address_signals(ctx.world, ctx.state.subject_id)
    if not a["available"]:
        return ToolResult("warn", "No address validation on file", ["address context unavailable; treated as not weak"], outcome="address_ok", provenance=_prov(ctx))
    facts = [f"confidence {a['confidence']:.2f}" if a["confidence"] is not None else "confidence n/a",
             f"{a['past_failures']} address-related failure(s) at this address",
             "first delivery to this address" if a["first_delivery"] else "address has delivery history"]
    return ToolResult("alert" if a["weak"] else "ok", "Address weak" if a["weak"] else "Address looks sound", facts,
                      outcome="address_weak" if a["weak"] else "address_ok", data={"address": a}, provenance=_prov(ctx))


def get_recipient_context(ctx: ToolContext, args: dict) -> ToolResult:
    r = sg.recipient_signals(ctx.world, ctx.state.subject_id)
    if r["window_conflict"]:
        out, status, summ, facts = "window_conflict", "alert", "Recorded 'unavailable' inside the confirmed window", [r["conflict_detail"]]
    elif r["missed"]:
        out, status, summ = "history_of_missed_windows", "warn", f"{r['missed_windows']} missed window(s)"
        facts = [f"responsiveness {r['responsiveness']}", f"preferred channel {r['channel']}"]
    else:
        out, status, summ, facts = "no_signal", "ok", "No recipient-side problem signal", [f"responsiveness {r.get('responsiveness')}", f"preferred channel {r.get('channel')}"]
    return ToolResult(status, summ, facts, outcome=out, data={"recipient": r}, provenance=_prov(ctx))


def get_route_context(ctx: ToolContext, args: dict) -> ToolResult:
    r = sg.route_signals(ctx.world, ctx.state.subject_id, ctx.state.facts or {})
    facts = []
    if r["corridor_ratio"] is not None:
        facts.append(f"corridor {r['corridor_speed']:.0f} km/h vs {r['corridor_typical']:.0f} typical ({r['corridor_ratio']:.0%})")
    if r["has_telemetry"]:
        facts.append(f"vehicle stationary {r['stationary_min']:.0f} min")
    if r["geo_mismatch"]:
        out, status, summ = "attempt_geo_mismatch", "alert", f"Failed attempt logged {r['mismatch_m']:.0f} m from the address"
        facts.insert(0, "courier GPS places the attempt away from the delivery address")
    elif r["corridor_ratio"] is not None and r["corridor_ratio"] < sg.BLOCKED_RATIO and r["stationary_min"] >= sg.STATIONARY_MIN_FLAG:
        out, status, summ = "blocked_stationary", "alert", "Vehicle held in a corridor slowdown"
    elif r["corridor_ratio"] is not None and r["corridor_ratio"] < sg.SLOW_RATIO:
        out, status, summ = "corridor_slow", "warn", "Corridor slower than typical"
    else:
        out, status, summ = "normal", "ok", "Route and telemetry normal"
        facts = facts or ["no corridor or vehicle anomaly"]
    return ToolResult(status, summ, facts, outcome=out, data={"route": r}, provenance=_prov(ctx))


def get_facility_context(ctx: ToolContext, args: dict) -> ToolResult:
    f = sg.facility_signals(ctx.world, ctx.state.facts or {})
    if not f["available"]:
        return ToolResult("ok", "No facility state on file", ["treated as normal"], outcome="normal", provenance=_prov(ctx))
    if f["backlog"]:
        out, status, summ = "backlog", "alert", f"Branch backlog {f['backlog_parcels']} parcels"
        facts = [f"baseline {f['baseline']:.0f} parcels"]
    elif f["scan_gap"]:
        out, status, summ = "scan_gap", "warn", f"No branch scan for {f['gap_hours']:.1f} h"
        facts = [f"scan gap threshold {sg.STALL_HOURS:.0f} h"]
    else:
        out, status, summ, facts = "normal", "ok", "Branch operating normally", [f"backlog {f['backlog_parcels']} parcels"]
    return ToolResult(status, summ, facts, outcome=out, data={"facility": f}, provenance=_prov(ctx))


def get_pickup_context(ctx: ToolContext, args: dict) -> ToolResult:
    p = sg.pickup_signals(ctx.world, ctx.state.facts or {})
    out = "offline" if p["offline"] else "online"
    return ToolResult("alert" if p["offline"] else "ok", f"Pickup point {p['status']}", [f"node {p['node_id']}"], outcome=out,
                      data={"pickup": p}, provenance=_prov(ctx))


# ── analysis ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def predict_risk(ctx: ToolContext, args: dict) -> ToolResult:
    rs = ctx.providers.risk.score(ctx.world, ctx.state.subject_id, ctx.state.facts or {})
    if rs.score < 0.35:
        out = "low"
    else:
        fam = next((d["family"] for d in rs.drivers if d["family"] != "code"), None)
        out = {"address": "driver_address", "recipient": "driver_recipient", "route": "driver_route", "facility": "driver_facility",
               "custody": "driver_custody", "pickup": "driver_pickup"}.get(fam, "generic_high")
    level = "critical" if rs.score >= 0.8 else "high" if rs.score >= 0.55 else "elevated" if rs.score >= 0.35 else "low"
    return ToolResult("alert" if rs.score >= 0.55 else "warn" if rs.score >= 0.35 else "ok", f"Risk {rs.score:.2f} ({level}) — {rs.basis}",
                      [f"↑ {d['label']}" for d in rs.drivers[:3]] or ["no risk drivers"], outcome=out,
                      data={"risk": {"score": rs.score, "level": level, "drivers": rs.drivers}},
                      provenance=_prov(ctx, model_id=rs.model_id, model_basis=rs.basis))


def check_incident_context(ctx: ToolContext, args: dict) -> ToolResult:
    inc = sg.incident_signals(ctx.world, ctx.state.subject_id, ctx.state.facts or {})
    if inc["triggered"]:
        out, status, summ = "incident_confirmed", "alert", f"{inc['observed']} related failures on {inc['scope']} {inc['scope_id']}"
        ctx.state.incident = inc
    elif inc["subthreshold"]:
        out, status, summ = "subthreshold_cluster", "warn", f"{inc['observed']} related failure(s) — below incident threshold"
    else:
        out, status, summ = "no_cluster", "ok", "No related failures"
    facts = []
    if inc["scope"]:
        facts.append(f"{inc['observed']} in last {sg.INCIDENT_WINDOW_MIN} min vs baseline {inc['baseline_mean']:.1f}±{inc['baseline_std']:.1f} · z={inc['z']:.1f} (threshold {sg.INCIDENT_Z:.0f})")
        if inc["triggered"]:
            facts.append(f"members: {', '.join(inc['members'][:6])}" + (f" · {len(inc['exposed'])} exposed" if inc["exposed"] else ""))
    return ToolResult(status, summ, facts, outcome=out, data={"incident": inc}, provenance=_prov(ctx, detector="rolling-window z-score"))


def analyze_disruption(ctx: ToolContext, args: dict) -> ToolResult:
    st = ctx.state
    top, p, margin = st.top_cause()
    code = (st.facts or {}).get("recorded_code")
    recorded = CODE_TO_CAUSE.get(code) if code else None
    pc = st.belief.p_cause()  # type: ignore[union-attr]
    lim = ranking.load_catalogue()["limits"]
    if recorded is None:
        agreement = "no_code" if p >= lim["diagnose_min_posterior"] and top not in (Cause.UNKNOWN,) else "inconclusive"
    elif recorded == top and p >= lim["diagnose_min_posterior"]:
        agreement = "agrees"
    elif recorded != top and pc[recorded] < 0.15 and p >= lim["diagnose_min_posterior"] and top not in (Cause.UNKNOWN, Cause.CUSTODY_ANOMALY):
        agreement = "conflicts"
    else:
        agreement = "inconclusive"
    if top in (Cause.UNKNOWN, Cause.CUSTODY_ANOMALY) and p < 0.8:
        agreement = "inconclusive"
    conf = "high" if p >= 0.8 else "medium" if p >= lim["diagnose_min_posterior"] else "low"
    st.diagnosis = {"cause": top.value, "posterior": round(p, 4), "margin": round(margin, 4), "confidence": conf, "agreement": agreement,
                    "recorded_code": code, "recorded_cause": None if recorded is None else recorded.value,
                    "p_recorded_cause": None if recorded is None else round(pc[recorded], 4),
                    "runner_up": sorted(((c.value, round(v, 3)) for c, v in pc.items() if c != top), key=lambda kv: -kv[1])[0]}
    facts = [f"most likely cause: {top.value} (posterior {p:.2f}, margin {margin:.2f})"]
    if recorded is not None:
        facts.append(f"recorded {code} → {recorded.value}; evidence gives it {pc[recorded]:.2f}")
    status = "alert" if agreement in ("conflicts", "inconclusive") else "ok"
    return ToolResult(status, f"Evidence {agreement.replace('_', ' ')} — {conf} confidence", facts, data={"diagnosis": st.diagnosis},
                      provenance=_prov(ctx, model_basis="belief posterior (expert-assumption observation models)"))


def rank_recovery_actions(ctx: ToolContext, args: dict) -> ToolResult:
    st = ctx.state
    facts = st.facts or {}
    rec = sg.recipient_signals(ctx.world, st.subject_id)
    pk = sg.pickup_signals(ctx.world, facts)
    preds = ranking.predicates(facts, rec, pk)
    ranked = ranking.rank_actions(st.belief.p_cause(), facts, preds)  # type: ignore[union-attr]
    st.ranked_actions = ranked
    if not ranked:
        return ToolResult("warn", "No eligible recovery action", [f"unmet preconditions: {[k for k, v in preds.items() if not v]}"],
                          data={"actions": [], "predicates": preds}, provenance=_prov(ctx, method="evidence_weighted_policy_ranking", causal_claim=False))
    return ToolResult("ok", f"Top action: {ranked[0]['title']}",
                      [f"#{a['rank']} {a['title']} (fit {a['fit']}, approval {a['approval']})" for a in ranked[:3]],
                      data={"actions": ranked, "predicates": preds},
                      provenance=_prov(ctx, method="evidence_weighted_policy_ranking", causal_claim=False, policy="recovery-policy-v1"))


def retrieve_policy_constraints(ctx: ToolContext, args: dict) -> ToolResult:
    st = ctx.state
    top = st.ranked_actions[0]
    d = st.diagnosis or {}
    ok, failed = ranking.auto_eligibility(top, posterior=d.get("posterior", 0.0), facts=st.facts or {}, agreement=d.get("agreement", "inconclusive"))
    st.policy = {"action": top["kind"], "approval": top["approval"], "approval_reason": top["approval_reason"], "auto_eligible": ok,
                 "failed_checks": failed}
    if ok:
        return ToolResult("ok", "Automated action permitted", ["all autonomy bounds satisfied"], data={"policy": st.policy}, provenance=_prov(ctx, policy="recovery-policy-v1"))
    reason = top["approval_reason"] or "; ".join(failed)
    return ToolResult("warn", f"Human approval required ({top['approval']})" if top["approval"] != "none" else "Automation not permitted",
                      [reason, *failed[:2]], data={"policy": st.policy}, provenance=_prov(ctx, policy="recovery-policy-v1"))


def escalate_case(ctx: ToolContext, args: dict) -> ToolResult:
    st = ctx.state
    facts = st.facts or {}
    d = st.diagnosis or {}
    top, p, _ = st.top_cause()
    question = open_question(st)
    sla = facts.get("promised_end_ts")
    priority = "P1" if (facts.get("cod_amount") or 0) >= 2000 or (facts.get("value") or 0) >= 3000 else "P2"
    st.escalation = {"to": "shift_supervisor", "priority": priority, "reason": args.get("reason", "unspecified"), "question": question,
                     "evidence": [f"{e.label}: {e.detail}" for e in st.evidence[:6]], "leading_hypotheses": st.belief.snapshot()["top"],  # type: ignore[union-attr]
                     "options": args.get("options", []), "diagnosis": d, "sla": None if sla is None else str(sla)}
    ctx.providers.executor.execute("escalate_case", st.subject_id, {"priority": priority, "question": question})
    return ToolResult("ok", f"Escalated to shift supervisor ({priority})", [question], data={"escalation": st.escalation},
                      provenance=_prov(ctx, side_effect="simulated"))


def open_question(st: CaseState) -> str:
    """The one question a human must answer, derived from the competing hypotheses (never free-form invention)."""
    pc = sorted(st.belief.p_cause().items(), key=lambda kv: -kv[1])  # type: ignore[union-attr]
    (a, pa), (b, pb) = pc[0], pc[1]
    d = st.diagnosis or {}
    if Cause.CUSTODY_ANOMALY in (a, b):
        return "Was the parcel handed to the recipient, or was the 'delivered' scan made in error?"
    if d.get("agreement") == "conflicts" and d.get("recorded_code"):
        return f"Recorded '{d['recorded_code']}' conflicts with the evidence ({a.value}, {pa:.0%}); which is correct?"
    return f"Evidence does not separate '{a.value}' ({pa:.0%}) from '{b.value}' ({pb:.0%}); which applies?"


# ── registry ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def build_registry() -> ToolRegistry:
    has_facts = lambda s: s.facts is not None  # noqa: E731
    return ToolRegistry([
        ToolSpec("get_shipment", "Load the shipment record: service level, payment, value, recorded exception, attempts.", "read", SHIPMENT_ARG, get_shipment, cost=0.5),
        ToolSpec("get_journey", "Read scans and attempts; detect failures, stalls and conflicting custody sequences.", "read", NO_ARGS, get_journey, 1.0, True, has_facts, "shipment loaded"),
        ToolSpec("get_address_context", "Address validation confidence and delivery history at this address.", "read", NO_ARGS, get_address_context, 1.0, True, has_facts, "shipment loaded"),
        ToolSpec("get_recipient_context", "Recipient contact history, confirmed windows and missed windows.", "read", NO_ARGS, get_recipient_context, 1.0, True, has_facts, "shipment loaded"),
        ToolSpec("get_route_context", "Courier GPS, corridor speed vs typical, and whether failed attempts were made at the address.", "read", NO_ARGS, get_route_context, 1.5, True,
                 lambda s: has_facts(s) and bool((s.facts or {}).get("corridor_id") or (s.facts or {}).get("courier_id")), "shipment has a corridor or courier"),
        ToolSpec("get_facility_context", "Origin branch backlog and last-scan gap.", "read", NO_ARGS, get_facility_context, 1.0, True,
                 lambda s: has_facts(s) and bool((s.facts or {}).get("origin_node_id")), "shipment has an origin branch"),
        ToolSpec("get_pickup_context", "Status of the assigned pickup point or locker.", "read", NO_ARGS, get_pickup_context, 0.5, True,
                 lambda s: has_facts(s) and bool((s.facts or {}).get("pickup_point_id")), "shipment has a pickup point"),
        ToolSpec("predict_risk", "Failure-risk score with its main drivers (model-backed; heuristic until a trained model is registered).", "analysis", NO_ARGS, predict_risk, 0.5, True, has_facts, "shipment loaded"),
        ToolSpec("check_incident_context", "Look for related failures across shipments on the same corridor/branch against a rolling baseline.", "analysis", NO_ARGS, check_incident_context, 1.5, True, has_facts, "shipment loaded"),
        ToolSpec("analyze_disruption", "Reconcile the recorded exception code with the accumulated evidence; report agreement/conflict.", "analysis", NO_ARGS, analyze_disruption, 0.5, False,
                 lambda s: s.belief is not None and len(s.outcomes()) >= 1, "at least one evidence tool has run"),
        ToolSpec("rank_recovery_actions", "Rank eligible recovery actions for the diagnosed cause (policy ranking, not a causal estimate).", "analysis", NO_ARGS, rank_recovery_actions, 0.5, False,
                 lambda s: s.diagnosis is not None, "analyze_disruption has run"),
        ToolSpec("retrieve_policy_constraints", "Check approval level and autonomy bounds for the top-ranked action.", "analysis", NO_ARGS, retrieve_policy_constraints, 0.3, False,
                 lambda s: bool(s.ranked_actions), "actions have been ranked"),
        ToolSpec("escalate_case", "Open a human escalation with the unresolved question and the evidence gathered.", "action",
                 {"type": "object", "properties": {"reason": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}}}},
                 escalate_case, 0.3, False, lambda s: s.diagnosis is not None, "analyze_disruption has run", side_effect="simulated"),
    ])
