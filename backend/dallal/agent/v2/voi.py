"""Value-of-information engine: should the agent look something up, ask someone, act now, or escalate?

For every candidate evidence source e (a database tool or a question to a person) we compute, by exact enumeration over its
outcomes and including the uncertainty in the likelihood tables (ensemble belief):

    EVOI_net(e) =  sum_o P(o) * max_a EU_o(a | extra delay of e)   -   max_a EU(a)   -   cost(e)

where EU is expected utility in SAR-equivalent units (utility.py). The three things the user asked a question to be judged on
fall out of this directly:
  * decision impact   - gain only counts if the answer can change the best option;
  * urgency / delay   - answers arrive after `latency`, and on-time value decays with delay, so a slow question is worth less
                         when the promise is near (and not at all if acting now is nearly as good);
  * response risk     - the 'no_response' outcome is part of the enumeration: with probability 1-p_resp the agent pays the cost
                         and the timeout delay and learns (almost) nothing.
Communication cost, recipient friction and message fatigue enter as `cost(e)`.

Limitations (stated, not hidden): one-step lookahead (a question whose value only appears after a second question is
undervalued); utilities and response models are expert assumptions; actions are not executed in parallel with waiting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from dallal.agent.v2 import inquiry as iq
from dallal.agent.v2.bayes import EnsembleBelief
from dallal.agent.v2.utility import Option, Stakes, best_option, params


@dataclass
class Candidate:
    source: str  # tool name or inquiry variant name
    kind: str  # tool | inquiry
    label: str  # tool name or inquiry id
    gross_voi: float
    cost: float
    net_voi: float
    eig_bits: float
    p_decision_change: float
    p_response: float = 1.0
    latency_min: float = 0.0
    target: str | None = None
    scope: str | None = None
    outcome_probs: dict[str, float] = field(default_factory=dict)

    def as_row(self) -> dict[str, Any]:
        return {"source": self.label, "kind": self.kind, "net_voi": round(self.net_voi, 3), "gross_voi": round(self.gross_voi, 3), "cost": round(self.cost, 3),
                "eig_bits": round(self.eig_bits, 4), "p_decision_change": round(self.p_decision_change, 3),
                "p_response": round(self.p_response, 3), "latency_min": round(self.latency_min, 1), "target": self.target}


def _entropy(p: np.ndarray) -> float:
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum())


def evaluate(belief: EnsembleBelief, source: str, *, kind: str, label: str, opts: list[Option], stakes: Stakes, cost: float, latency_for: dict[str, float],
             p_response: float = 1.0, target: str | None = None, scope: str | None = None) -> Candidate:
    """Exact net EVOI of consulting `source` (outcome-dependent latency via `latency_for`)."""
    p_o = belief.predictive(source)
    outs = belief.book.outcomes(source)
    best_now, eu_now = best_option(opts, belief.p_cause_vec(), stakes)
    h0 = belief.entropy()
    exp_u = exp_h = chg = 0.0
    for o, name in enumerate(outs):
        if p_o[o] <= 1e-12:
            continue
        post = belief.after(source, name)
        bo, u = best_option(opts, post.p_cause_vec(), stakes, extra_delay_min=latency_for[name])
        exp_u += p_o[o] * u
        exp_h += p_o[o] * post.entropy()
        chg += p_o[o] * (bo.name != best_now.name)
    gross = exp_u - eu_now
    return Candidate(source, kind, label, float(gross), float(cost), float(gross - cost), max(0.0, h0 - exp_h), float(chg), p_response,
                     float(sum(p_o[i] * latency_for[n] for i, n in enumerate(outs))), target, scope, {n: float(p_o[i]) for i, n in enumerate(outs)})


def tool_candidates(belief: EnsembleBelief, tool_names: list[str], opts: list[Option], stakes: Stakes) -> list[Candidate]:
    p = params()
    out = []
    for t in tool_names:
        lat = p["tool_latency_min"].get(t, p["tool_latency_min"]["default"])
        cost = p["tool_cost_sar"].get(t, p["tool_cost_sar"]["default"])
        outs = belief.book.outcomes(t)
        out.append(evaluate(belief, t, kind="tool", label=t, opts=opts, stakes=stakes, cost=cost, latency_for={o: lat for o in outs}))
    return out


def inquiry_candidates(belief: EnsembleBelief, facts: dict[str, Any], now: pd.Timestamp, asked: set[str], opts: list[Option], stakes: Stakes) -> list[Candidate]:
    out = []
    for s in iq.all_specs():
        if s.id in asked or not iq.applicable(s, facts, now):
            continue
        p = iq.response_prob(s, facts)
        name = iq.variant_name(s.id, p)
        belief.book.ensure(name)
        lat = {a["id"]: iq.expected_latency_min(s) for a in s.answers}
        lat[iq.NO_RESPONSE] = float(s.raw["response"]["timeout_min"])
        out.append(evaluate(belief, name, kind="inquiry", label=s.id, opts=opts, stakes=stakes, cost=iq.cost_sar(s, facts), latency_for=lat,
                            p_response=p, target=s.target, scope=s.scope))
    return out


def set_voi(belief: EnsembleBelief, tool_names: list[str], opts: list[Option], stakes: Stakes, *, n: int = 192, seed: int = 0) -> tuple[float, float]:
    """Monte-Carlo value of consulting ALL of `tool_names` (the non-myopic upper bound used for look-ahead).

    One-step VOI is blind to evidence that only changes the best option in combination (each observation shifts the posterior a
    little but never enough on its own). Sampling a true state from the belief, simulating every tool's outcome from that state,
    updating sequentially and taking the best option on the resulting posterior measures that joint value. Returns (gross, cost).
    """
    if not tool_names:
        return 0.0, 0.0
    p = params()
    rng = np.random.default_rng(seed)
    w = belief.weights()
    best_now, eu_now = best_option(opts, belief.p_cause_vec(), stakes)
    total_lat = sum(p["tool_latency_min"].get(t, p["tool_latency_min"]["default"]) for t in tool_names)
    cost = sum(p["tool_cost_sar"].get(t, p["tool_cost_sar"]["default"]) for t in tool_names)
    acc = 0.0
    for _ in range(n):
        k = rng.choice(len(w), p=w)
        flat = belief.joint[k].ravel()
        cs = rng.choice(flat.size, p=flat / flat.sum())
        c, s = divmod(cs, 2)
        b = belief.copy()
        for t in tool_names:
            T = belief.book.tables[t][k][:, c, s]  # outcome distribution of tool t under the sampled truth and particle
            o = rng.choice(len(T), p=T / T.sum())
            b.update(t, belief.book.outcomes(t)[o])
        _, u = best_option(opts, b.p_cause_vec(), stakes, extra_delay_min=total_lat)
        acc += u
    return float(acc / n - eu_now), float(cost)
