"""v2 tool layer: reuses the v1 evidence tools (database reads) and replaces the three decision tools with utility-based ones."""

from __future__ import annotations

from typing import Any

import numpy as np

from dallal.agent.belief import CAUSES, Cause
from dallal.agent.v2.utility import (
    CI,
    Option,
    build_options,
    minutes_to_promise,
    params,
    stakes,
    utility_table,
)
from dallal.recovery import ranking
from dallal.tools import signals as sg
from dallal.tools.base import ToolContext, ToolRegistry, ToolResult, ToolSpec
from dallal.tools.builtin import build_registry


def action_predicates(world: Any, facts: dict[str, Any]) -> dict[str, bool]:
    if hasattr(world, "action_predicates"):
        return world.action_predicates(facts)
    return ranking.predicates(facts, sg.recipient_signals(world, facts["shipment_id"]), sg.pickup_signals(world, facts))


def case_options(state, world) -> tuple[list[Option], Any]:
    """Options and stakes for the current moment (urgency shrinks as virtual time passes)."""
    facts = state.facts or {}
    if getattr(state, "_preds", None) is None:
        state._preds = action_predicates(world, facts)  # type: ignore[attr-defined]
    opts = build_options(facts, state._preds)  # type: ignore[attr-defined]
    base = minutes_to_promise(facts, state.as_of)
    return opts, stakes(facts, None if base is None else base - state.virtual_min)


def success_given_particles(state, option: Option) -> np.ndarray:
    """[K] per-particle probability that `option` works (table uncertainty -> a distribution, not a point)."""
    pk = state.belief.particle_cause()  # [K,C]
    return pk @ option.success


def autonomy_check(state, option: Option, agreement: str) -> tuple[bool, list[str], float]:
    a, lim = params()["autonomy"], ranking.load_catalogue()["limits"]
    facts = state.facts or {}
    robust = state.belief.weighted_quantile(success_given_particles(state, option), a["robust_effectiveness_quantile"])
    checks = [
        ("action is automatable and needs no approval", option.automatable),
        (f"robust effectiveness >= {a['robust_effectiveness_min']:.0%} (pessimistic tail over table uncertainty)", robust >= a["robust_effectiveness_min"]),
        ("action is reversible or low impact", option.reversible or option.impact == "low"),
        (f"parcel value <= SAR {lim['auto_value_max_sar']:,}", (facts.get("value") or 0) <= lim["auto_value_max_sar"]),
        (f"<= {lim['auto_max_prior_failures']} prior failed attempts", (facts.get("failed_attempts") or 0) <= lim["auto_max_prior_failures"]),
        ("recorded code does not conflict with the evidence", agreement != "conflicts"),
    ]
    failed = [n for n, ok in checks if not ok]
    return not failed, failed, robust


def _rank_v2(ctx: ToolContext, args: dict) -> ToolResult:
    st = ctx.state
    opts, stk = case_options(st, ctx.world)
    pcv = st.belief.p_cause_vec()
    table = utility_table(opts, pcv, stk)
    by_name = {o.name: o for o in opts}
    ranked = []
    for row in table:
        o = by_name[row["option"]]
        if o.kind != "act":
            continue
        eff = float(pcv @ o.success)
        ranked.append({"kind": o.name, "title": o.title, "tool": o.meta.get("tool"), "score": row["eu"], "fit": "strong" if eff >= 0.6 else "moderate" if eff >= 0.35 else "weak",
                       "reversible": o.reversible, "impact": o.impact, "approval": o.approval, "approval_reason": None if o.approval == "none" else f"{o.impact}-impact action needs {o.approval} approval",
                       "automatable": o.automatable, "minutes_to_effect": o.delay_min,
                       "factors": [{"label": "Expected effectiveness", "value": f"{eff:.2f}", "basis": "rule"}, {"label": "Cost (SAR-eq)", "value": f"{o.cost:.1f}", "basis": "assumption"},
                                   {"label": "Time-to-effect incl. approval (min)", "value": f"{o.delay_min:.0f}", "basis": "assumption"}],
                       "method": "expected_utility_ranking", "causal_claim": False})
    for i, a in enumerate(ranked[:5], 1):
        a["rank"] = i
    st.ranked_actions, st.utility_table = ranked[:5], table
    if not ranked:
        return ToolResult("warn", "No eligible recovery action", [], data={"actions": []}, provenance={"method": "expected_utility_ranking", "causal_claim": False})
    return ToolResult("ok", f"Top action by expected utility: {ranked[0]['title']}", [f"#{a['rank']} {a['title']} (EU {a['score']:.1f}, approval {a['approval']})" for a in ranked[:3]],
                      data={"actions": ranked[:5], "utility_table": table[:6]}, provenance={"method": "expected_utility_ranking", "causal_claim": False, "policy": "utility-v1"})


def _policy_v2(ctx: ToolContext, args: dict) -> ToolResult:
    st = ctx.state
    top = st.ranked_actions[0]
    opts, _ = case_options(st, ctx.world)
    opt = next(o for o in opts if o.name == top["kind"])
    ok, failed, robust = autonomy_check(st, opt, (st.diagnosis or {}).get("agreement", "inconclusive"))
    st.policy = {"action": top["kind"], "approval": top["approval"], "approval_reason": top["approval_reason"], "auto_eligible": ok, "failed_checks": failed, "robust_effectiveness": round(robust, 3)}
    if ok:
        return ToolResult("ok", "Automated action permitted", [f"robust effectiveness {robust:.0%} in the pessimistic tail", "all autonomy bounds satisfied"], data={"policy": st.policy},
                          provenance={"policy": "policy-v2"})
    return ToolResult("warn", f"Human approval required ({top['approval']})" if top["approval"] != "none" else "Automation not permitted", list(dict.fromkeys([*( [top["approval_reason"]] if top["approval_reason"] else [] ), *failed[:3]])),
                      data={"policy": st.policy}, provenance={"policy": "policy-v2"})


def build_registry_v2() -> ToolRegistry:
    base = build_registry()
    specs = []
    for s in base.all():
        if s.name == "rank_recovery_actions":
            s = ToolSpec(s.name, "Rank eligible recovery actions by expected utility under the current belief (not a causal estimate).", s.kind, s.input_schema, _rank_v2, s.cost, False, s.requires, s.requires_doc)
        elif s.name == "retrieve_policy_constraints":
            s = ToolSpec(s.name, "Check approval and autonomy bounds (robust to likelihood-table uncertainty) for the top action.", s.kind, s.input_schema, _policy_v2, s.cost, False, s.requires, s.requires_doc)
        specs.append(s)
    return ToolRegistry(specs)


__all__ = ["CAUSES", "CI", "Cause", "autonomy_check", "build_registry_v2", "case_options", "success_given_particles"]
