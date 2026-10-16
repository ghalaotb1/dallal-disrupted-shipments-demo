"""Decision options, utilities and expected value of information (EVOI) in SAR-equivalent units.

An *option* is something the agent can do now: wait, take a recovery action, or escalate to a human. Given a belief over causes,
each option has an expected utility that accounts for (a) how likely it is to work for each cause, (b) what it costs, (c) how
fast the value of on-time delivery decays with the time it takes to take effect and be approved.

EVOI of an evidence source is the improvement in the best option's expected utility after seeing the evidence, MINUS what it
costs and what the waiting costs (decay of value while the answer arrives). This is the 'decision-focused' criterion used by
recent value-of-information work on clarification (e.g. cost-penalised EVPI, VoI-gated asking) rather than raw entropy gain.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from dallal.agent.belief import CAUSES, Cause
from dallal.recovery.ranking import load_catalogue, predicates

SPEC = Path(__file__).with_name("utility.yaml")
CI = {c: i for i, c in enumerate(CAUSES)}


@lru_cache(maxsize=1)
def params() -> dict[str, Any]:
    return yaml.safe_load(SPEC.read_text())


@dataclass(frozen=True)
class Stakes:
    value: float  # utility of delivering on time
    fail: float  # additional loss if delivery fails
    horizon_min: float  # urgency time-scale: success decays as exp(-delay / horizon)


def stakes(facts: dict[str, Any], minutes_to_promise: float | None) -> Stakes:
    p = params()
    v, mult = p["value"], p["value"]["service_multiplier"].get(facts.get("service_level") or "Standard", 1.0)
    stake = max(facts.get("value") or 0.0, facts.get("cod_amount") or 0.0) * v["stake_factor"]
    slack = p["time"]["default_slack_min"] if minutes_to_promise is None else minutes_to_promise
    return Stakes((v["on_time_sar"] + stake) * mult, (v["fail_cost_sar"] + stake) * mult, max(float(slack), p["time"]["slack_floor_min"]))


@dataclass
class Option:
    name: str  # "wait" | "escalate" | action kind
    kind: str  # wait | escalate | act
    success: np.ndarray  # [C] probability of on-time delivery given the true cause (before time decay)
    cost: float
    delay_min: float
    approval: str = "none"
    automatable: bool = False
    reversible: bool = True
    impact: str = "low"
    title: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def _success_vec(spec: dict[str, Any], facts: dict[str, Any]) -> np.ndarray:
    from dallal.recovery.ranking import repeat_adjusted_suitability

    p = params()
    suit = repeat_adjusted_suitability(spec, facts)
    v = np.full(len(CAUSES), 0.05)
    for c, s in suit.items():
        v[CI[Cause(c)]] = s
    v[CI[Cause.NONE]] = p["healthy_success"]
    return v


def build_options(facts: dict[str, Any], preds: dict[str, bool]) -> list[Option]:
    p, cat = params(), load_catalogue()
    opts: list[Option] = []
    ws = np.array([p["wait_success"][c.value] for c in CAUSES])
    opts.append(Option("wait", "wait", ws, 0.0, 0.0, title="Wait and monitor"))
    from dallal.recovery.ranking import _approval  # noqa: PLC0415

    acts: list[Option] = []
    for kind, spec in cat["actions"].items():
        if any(not preds.get(r, False) for r in spec.get("requires", [])):
            continue
        approval, _ = _approval(spec, facts)
        a = p["approval"][approval]
        acts.append(Option(kind, "act", _success_vec(spec, facts), p["action_cost_sar"][kind] + a["cost_sar"], spec["minutes_to_effect"] + a["delay_min"],
                           approval, bool(spec["automatable"]) and approval == "none", spec["reversible"], spec["impact"], spec["title"],
                           {"tool": spec["tool"], "approval_reason": None}))
    e = p["escalate"]
    best_known = np.max([o.success for o in acts], axis=0) if acts else np.full(len(CAUSES), 0.05)
    es = e["human_reliability"] * best_known
    for c, floor in e["human_floor"].items():
        es[CI[Cause(c)]] = max(es[CI[Cause(c)]], floor)
    es[CI[Cause.NONE]] = p["healthy_success"]
    opts.append(Option("escalate", "escalate", es, e["supervisor_cost_sar"] + e["typical_action_cost_sar"], e["handoff_delay_min"] + e["typical_action_delay_min"],
                       approval="supervisor", title="Escalate to the shift supervisor"))
    return opts + acts


def option_utility(o: Option, p_cause: np.ndarray, s: Stakes, extra_delay_min: float = 0.0) -> float:
    # 'wait' success is already "what happens if nobody intervenes", so waiting longer for information does not decay it again.
    u = 1.0 if o.kind == "wait" else np.exp(-(o.delay_min + extra_delay_min) / s.horizon_min)
    se = o.success * u
    irrev = 0.0 if o.reversible else params()["irreversible_penalty_sar"] * (1.0 - o.success)
    return float(np.dot(p_cause, s.value * se - s.fail * (1.0 - se) - o.cost - irrev))


def best_option(opts: list[Option], p_cause: np.ndarray, s: Stakes, extra_delay_min: float = 0.0) -> tuple[Option, float]:
    scored = [(option_utility(o, p_cause, s, extra_delay_min), o) for o in opts]
    u, o = max(scored, key=lambda t: t[0])
    return o, u


def utility_table(opts: list[Option], p_cause: np.ndarray, s: Stakes) -> list[dict[str, Any]]:
    rows = [{"option": o.name, "eu": round(option_utility(o, p_cause, s), 2), "approval": o.approval, "delay_min": o.delay_min, "cost": o.cost} for o in opts]
    return sorted(rows, key=lambda r: -r["eu"])


def minutes_to_promise(facts: dict[str, Any], now) -> float | None:
    import pandas as pd

    t = facts.get("promised_end_ts")
    if t is None or (isinstance(t, float) and np.isnan(t)):
        return None
    return float((pd.Timestamp(t) - pd.Timestamp(now)).total_seconds() / 60)


__all__ = ["Option", "Stakes", "best_option", "build_options", "minutes_to_promise", "option_utility", "params", "predicates", "stakes", "utility_table"]
