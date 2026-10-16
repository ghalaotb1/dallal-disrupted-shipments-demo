"""Prior over root causes once the shipment facts are known. All multipliers are expert assumptions (MODEL_BASIS)."""

from __future__ import annotations

from typing import Any

from dallal.agent.belief import BASE_PRIOR, CODE_TO_CAUSE, RECORDED_CODE_BOOST, Cause

# Why the agent was invoked is itself weak evidence about whether something is wrong.
TRIGGER_NONE_FACTOR = {"scheduled_scan": 1.0, "analyst_request": 0.8, "risk_alert": 0.4, "exception_recorded": 0.1}


def build_prior(facts: dict[str, Any], trigger: dict[str, Any]) -> dict[Cause, float]:
    p = dict(BASE_PRIOR)
    code = facts.get("recorded_code")
    if code:
        cause = CODE_TO_CAUSE.get(code)
        p[Cause.NONE] *= 0.15
        if cause:
            p[cause] *= RECORDED_CODE_BOOST
        else:
            p[Cause.UNKNOWN] *= 3.0  # a code we have no mapping for is itself unusual
    elif facts.get("failed_attempts"):
        p[Cause.NONE] *= 0.2
    p[Cause.NONE] *= TRIGGER_NONE_FACTOR.get(trigger.get("kind", "scheduled_scan"), 1.0)
    if not facts.get("pickup_point_id"):
        p[Cause.PICKUP_POINT_UNAVAILABLE] = 0.002  # cannot be the cause if no pickup point is assigned
    total = sum(p.values())
    return {c: v / total for c, v in p.items()}
