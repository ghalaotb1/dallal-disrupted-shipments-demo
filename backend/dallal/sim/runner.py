"""Run agents on simulated episodes and score them against the latent truth (SYNTHETIC; paired by episode seed).

Scoring uses the TRUE model: expected utility of what the agent actually ended up doing, including the time its information
gathering consumed, the cost of every message sent, and the friction it caused. `regret` is measured against an oracle that knows
the true cause at no information cost. Everything is in the utility.yaml SAR-equivalents (assumptions), so the comparison is about
RELATIVE decision quality under stated assumptions, not about money.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from dallal.agent.belief import CI, Cause
from dallal.agent.runtime import AgentRuntime
from dallal.agent.v2 import inquiry as iq
from dallal.agent.v2.runtime import AgentRuntimeV2
from dallal.agent.v2.tools import build_registry_v2
from dallal.agent.v2.utility import Option, build_options, params, stakes
from dallal.sim.world import SimEnv, TrueModel, draw_episode, sim_registry
from dallal.tools.builtin import build_registry

AGENTS = ("v1_legacy", "v2_no_inquiry", "v2_infogain", "v2_value")


def true_eu(o: Option, cause: Cause, tm: TrueModel, V: float, L: float, H: float, extra_delay: float) -> tuple[float, float]:
    """(expected utility, probability of on-time) of executing `o` after `extra_delay` minutes, under the TRUE model."""
    s = float(np.clip(o.success[CI[cause]] * tm.effect_noise[CI[cause]], 0.0, 0.99))
    u = 1.0 if o.kind == "wait" else float(np.exp(-(o.delay_min + extra_delay) / H))
    se = s * u
    irrev = 0.0 if o.reversible else params()["irreversible_penalty_sar"] * (1 - s)
    return V * se - L * (1 - se) - o.cost - irrev, se


def oracle(ep, tm, opts) -> tuple[float, str]:
    stk = stakes(ep.facts, ep.slack_min)
    best = max(((true_eu(o, ep.truth, tm, stk.value, stk.fail, stk.horizon_min, 0.0)[0], o.name) for o in opts if o.kind != "escalate"), key=lambda t: t[0])
    return best


def _chosen_option(decision: dict[str, Any], opts: list[Option], ep, tm, rng, stk) -> tuple[Option, str]:
    t = decision["type"]
    by = {o.name: o for o in opts}
    if t in ("auto_eligible", "recommend"):
        return by[decision["action"]], t
    if t == "escalate":
        # A supervisor who then knows the cause: 90% pick the best action for the TRUE cause, otherwise a random eligible one.
        acts = [o for o in opts if o.kind == "act"]
        if acts and rng.random() < 0.9:
            o = max(acts, key=lambda a: true_eu(a, ep.truth, tm, stk.value, stk.fail, stk.horizon_min, 0)[0])
        elif acts:
            o = acts[int(rng.integers(len(acts)))]
        else:
            o = by["wait"]
        # carry the hand-off overhead of escalation
        esc = by["escalate"]
        o = Option(o.name, "act" if o.kind == "act" else "wait", o.success, o.cost + params()["escalate"]["supervisor_cost_sar"], o.delay_min + params()["escalate"]["handoff_delay_min"], o.approval,
                   False, o.reversible, o.impact, o.title)
        _ = esc
        return o, t
    if t == "incident":  # S=0 episodes: a false incident declaration wastes effort; the parcel is effectively left to recover on its own
        w = by["wait"]
        return Option("wait", "wait", w.success, w.cost + 30.0, 0.0), t
    return by["wait"], t


def run_episode(agent: str, seed: int, tm: TrueModel, *, systemic: bool = False, planner: Any = None) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    ep = draw_episode(rng, systemic=systemic, seed=seed)
    env = SimEnv(ep, tm, np.random.default_rng(seed + 10_000), engine="v1" if agent == "v1_legacy" else "v2")
    opts = build_options(ep.facts, ep.preds)
    base_stk = stakes(ep.facts, ep.slack_min)
    o_u, o_name = oracle(ep, tm, opts)
    if agent == "v1_legacy":
        run, st = AgentRuntime(tools=sim_registry(build_registry(), "v1")).investigate(env)
        elapsed, inquiries = 0.2 * len(run.steps), []
    else:
        mode = {"v2_no_inquiry": "no_inquiry", "v2_infogain": "infogain", "v2_value": "value", "v2_llm": "value"}[agent]
        responder = lambda pend, st_: env.answer(pend, iq.spec(pend.spec_id), pend.p_response)  # noqa: E731
        rr = AgentRuntimeV2(mode=mode, tools=sim_registry(build_registry_v2(), "v2"), responder=responder, planner=planner).start(env)
        run, st = rr.run, rr.state
        elapsed, inquiries = st.virtual_min, st.inquiries
    d = run.decision
    stk = stakes(ep.facts, ep.slack_min)
    chosen, dtype = _chosen_option(d, opts, ep, tm, np.random.default_rng(seed + 20_000), stk)
    u_exec, p_on_time = true_eu(chosen, ep.truth, tm, stk.value, stk.fail, stk.horizon_min, elapsed)
    msg_cost = sum(iq.spec(i["spec"]).raw["cost"]["comm_sar"] + iq.spec(i["spec"]).raw["cost"]["friction_sar"] for i in inquiries)
    u_total = u_exec - msg_cost
    true_succ = float(np.clip(chosen.success[CI[ep.truth]] * tm.effect_noise[CI[ep.truth]], 0, 0.99))
    unsafe = dtype == "auto_eligible" and chosen.kind == "act" and true_succ < 0.35
    return {"agent": agent, "seed": seed, "truth": ep.truth.value, "decision": dtype, "action": chosen.name, "named_cause": d["top_cause"], "cause_correct": d["top_cause"] == ep.truth.value,
            "utility": u_total, "oracle_utility": o_u, "regret": o_u - u_total, "p_on_time": p_on_time, "unsafe_auto": bool(unsafe), "elapsed_min": float(elapsed),
            "n_tools": sum(1 for s in run.steps if not s["tool"].startswith("ask:")), "n_questions": len(inquiries), "n_answered": sum(1 for i in inquiries if i["status"] == "answered"),
            "n_timeouts": sum(1 for i in inquiries if i["status"] == "timed_out"), "comm_cost": msg_cost, "slack_min": ep.slack_min, "stake": base_stk.value,
            "escalated": dtype == "escalate", "false_incident": dtype == "incident"}


def run_suite(n: int, tm: TrueModel, agents=AGENTS, start_seed: int = 0) -> pd.DataFrame:
    rows = [run_episode(a, start_seed + i, tm) for i in range(n) for a in agents]
    return pd.DataFrame(rows)
