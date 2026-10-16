"""First recovery layer: evidence-weighted, policy-bounded action ranking.

SCIENTIFIC STATUS (read this before quoting any number from here)
-----------------------------------------------------------------
This is NOT a learned or causal recovery policy. No public data link last-mile actions to outcomes. The score is

    score(a) = sum_c  P(cause=c | evidence) * suitability(a, c)  -  friction(a)

with `suitability` and `friction` set by domain rules (recovery/actions.yaml). It ranks actions by how well they fit the
*diagnosed* cause, never by an estimated probability of success or uplift. Outputs carry `causal_claim=False`.
The ledger (dallal.agent.ledger) records everything a future causal learner needs: the context the chooser saw, the
assignment mechanism, the logged propensity (if randomised) and the observed outcome.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from dallal.agent.belief import Cause

SPEC = Path(__file__).with_name("actions.yaml")
APPROVAL_ORDER = {"none": 0, "analyst": 1, "supervisor": 2}


@lru_cache(maxsize=1)
def load_catalogue() -> dict[str, Any]:
    return yaml.safe_load(SPEC.read_text())


def predicates(facts: dict[str, Any], recipient: dict[str, Any], pickup: dict[str, Any]) -> dict[str, bool]:
    return {
        "recipient_reachable": bool(recipient.get("available")) and recipient.get("responsiveness") != "none",
        "pickup_online": bool(pickup.get("available")) and not pickup.get("offline"),
        "alt_pickup_online": bool(facts.get("alt_pickup_online")),
        "alt_route": bool(facts.get("alt_route_available")),
        "spare_courier": bool(facts.get("spare_courier_available")),
    }


def _approval(spec: dict[str, Any], facts: dict[str, Any]) -> tuple[str, str | None]:
    level, reason = spec.get("approval", "none"), None
    esc = spec.get("escalate_if") or {}
    cod, val = facts.get("cod_amount") or 0.0, facts.get("value") or 0.0
    if cod >= esc.get("cod_amount_gte", float("inf")):
        level, reason = "supervisor", f"COD SAR {cod:,.0f} exceeds the SAR {esc['cod_amount_gte']:,} analyst limit"
    elif val >= esc.get("value_gte", float("inf")):
        level, reason = "supervisor", f"parcel value SAR {val:,.0f} exceeds the SAR {esc['value_gte']:,} analyst limit"
    elif level == "analyst":
        reason = f"{spec['impact']}-impact action needs analyst approval"
    return level, reason


def repeat_adjusted_suitability(spec: dict[str, Any], facts: dict[str, Any]) -> dict[str, float]:
    """Suitability by cause after the repeat-failure rule (after N failures, re-contact is worth less and redirection more)."""
    cat = load_catalogue()
    suit = dict(spec["suitability"])
    kind = next((k for k, v in cat["actions"].items() if v is spec), None)
    rep = REPEAT_ADJUST.get(kind)
    if rep and (facts.get("failed_attempts") or 0) >= cat["limits"]["repeat_failure_threshold"]:
        suit = {c: min(1.0, v * rep) for c, v in suit.items()}
    return suit


REPEAT_ADJUST = {"verify_address": 0.6, "contact_recipient": 0.5, "offer_window": 0.5, "redirect_pickup": 1.5, "redirect_locker": 1.3}


def rank_actions(p_cause: dict[Cause, float], facts: dict[str, Any], preds: dict[str, bool], *, top_k: int = 5) -> list[dict[str, Any]]:
    cat = load_catalogue()
    actionable = {c: p for c, p in p_cause.items() if c not in (Cause.NONE, Cause.UNKNOWN)}
    mass = sum(actionable.values()) or 1.0
    rep_adj = REPEAT_ADJUST  # after repeated failures, re-contact is worth less and moving the parcel is worth more
    out = []
    for kind, spec in cat["actions"].items():
        unmet = [r for r in spec.get("requires", []) if not preds.get(r, False)]
        suit = dict(spec["suitability"])
        rep = rep_adj.get(kind)
        if rep and (facts.get("failed_attempts") or 0) >= cat["limits"]["repeat_failure_threshold"]:
            suit = {c: min(1.0, v * rep) for c, v in suit.items()}
        fit = sum((actionable.get(Cause(c), 0.0) / mass) * s for c, s in suit.items())
        if fit < cat["limits"]["min_action_fit"] or unmet:
            continue
        score = fit - 0.15 * spec["friction"]
        approval, why = _approval(spec, facts)
        out.append({
            "kind": kind, "title": spec["title"], "tool": spec["tool"], "score": round(score, 4),
            "fit": "strong" if fit >= 0.6 else "moderate" if fit >= 0.35 else "weak",
            "reversible": spec["reversible"], "impact": spec["impact"], "approval": approval, "approval_reason": why,
            "automatable": bool(spec["automatable"]) and approval == "none", "minutes_to_effect": spec["minutes_to_effect"],
            "factors": [
                {"label": "Expected cause-fit", "value": f"{fit:.2f}", "basis": "rule"},
                {"label": "Recipient/ops friction", "value": f"-{0.15 * spec['friction']:.3f}", "basis": "assumption"},
                *({"label": f"Precondition {r}", "value": "met", "basis": "data"} for r in spec.get("requires", [])),
            ],
            "method": "evidence_weighted_policy_ranking", "causal_claim": False,
        })
    out.sort(key=lambda a: -a["score"])
    for i, a in enumerate(out, 1):
        a["rank"] = i
    return out[:top_k]


def auto_eligibility(action: dict[str, Any], *, posterior: float, facts: dict[str, Any], agreement: str) -> tuple[bool, list[str]]:
    """Bounded autonomy: ALL conditions must hold for the agent to be permitted to act without a human."""
    lim = load_catalogue()["limits"]
    checks = [
        ("action is automatable and needs no approval", action["automatable"]),
        (f"diagnosis confidence >= {lim['auto_confidence_min']:.0%}", posterior >= lim["auto_confidence_min"]),
        ("action is reversible or low impact", action["reversible"] or action["impact"] == "low"),
        (f"parcel value <= SAR {lim['auto_value_max_sar']:,}", (facts.get("value") or 0) <= lim["auto_value_max_sar"]),
        (f"<= {lim['auto_max_prior_failures']} prior failed attempts", (facts.get("failed_attempts") or 0) <= lim["auto_max_prior_failures"]),
        ("recorded code does not conflict with evidence", agreement != "conflicts"),
    ]
    failed = [name for name, ok in checks if not ok]
    return not failed, failed
