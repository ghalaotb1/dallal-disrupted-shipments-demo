"""Evaluation lab for single-shipment agents on the independent PROCESS world (SYNTHETIC). Paired by seed with common random numbers.

Every agent sees the SAME episode: same latent cause, hidden state, tool-gap draws, human answers (keyed by question), action-success uniforms and travel-time
draws. Differences in outcome are therefore differences in decisions. Outcomes are REALISED, not expected values.

Metrics per episode (all in the ENVIRONMENT's own utility units, not the agent's):
  utility            EXPECTED realised utility of what was done given the shared physical draws (true success probability x on-time indicator; low variance); `utility_realised`
                     is the Bernoulli-realised version. Value if protected on time, loss if not, action cost, message cost + friction
  regret             utility of an oracle that knows the true cause (zero information cost, zero delay, picks the best EXPECTED option, same draws) minus utility
  protected          the parcel was delivered on time (realised)
  harmful_auto       an automatically executed action that realised WORSE than simply waiting, on the same draws
  unsafe_auto        an automatically executed action whose true success probability was below 0.35 (the earlier metric)
  false_resolve      the agent declared the parcel fine / no action although a real cause existed and an action would have helped in expectation
"""

from __future__ import annotations

import contextlib
from typing import Any

import numpy as np
import pandas as pd

from dallal.agent.runtime import AgentRuntime
from dallal.agent.v2 import bayes
from dallal.agent.v2 import inquiry as iq
from dallal.agent.v2.bayes import default_book
from dallal.agent.v2.planner import PlannerV2
from dallal.agent.v2.runtime import AgentRuntimeV2
from dallal.agent.v2.tools import build_registry_v2
from dallal.agent.v2.utility import build_options, params
from dallal.recovery.ranking import load_catalogue
from dallal.sim.process import (
    WAIT_P,
    ProcessConfig,
    ProcessEnv,
    draw_process_episode,
    env_stakes,
    oracle_expected_best,
    realise,
    true_p,
)
from dallal.sim.world import sim_registry
from dallal.tools.builtin import build_registry

AGENTS = ("v1_legacy", "v2_no_inquiry", "v2_infogain", "v2_value", "v2_value_adaptive")
ABLATIONS = ("v2_value", "abl_point_belief", "abl_no_tempering", "abl_no_lookahead", "abl_asks_before_looking", "abl_mean_autonomy", "v2_no_inquiry")


@contextlib.contextmanager
def overrides(family_exponent: float | None = None, robust_quantile: float | None = None, robust_min: float | None = None, max_p_unknown: float | None = None):
    old_f, old_q, old_m = bayes.FAMILY_EXPONENT, params()["autonomy"]["robust_effectiveness_quantile"], params()["autonomy"]["robust_effectiveness_min"]
    old_u = params()["autonomy"].get("max_p_unknown", 1.0)
    try:
        if family_exponent is not None:
            bayes.FAMILY_EXPONENT = family_exponent
        if robust_quantile is not None:
            params()["autonomy"]["robust_effectiveness_quantile"] = robust_quantile
        if robust_min is not None:
            params()["autonomy"]["robust_effectiveness_min"] = robust_min
        if max_p_unknown is not None:
            params()["autonomy"]["max_p_unknown"] = max_p_unknown
        yield
    finally:
        bayes.FAMILY_EXPONENT = old_f
        params()["autonomy"]["robust_effectiveness_quantile"], params()["autonomy"]["robust_effectiveness_min"] = old_q, old_m
        params()["autonomy"]["max_p_unknown"] = old_u


def _runtime_v2(agent: str, env: ProcessEnv, extra: dict[str, Any] | None = None) -> AgentRuntimeV2:
    mode = {"v2_no_inquiry": "no_inquiry", "v2_infogain": "infogain"}.get(agent, "value")
    kw: dict[str, Any] = {"mode": mode}
    pk: dict[str, Any] = {}
    if agent == "abl_no_lookahead":
        pk["lookahead"] = False
    if agent == "abl_asks_before_looking":
        pk["tools_first"] = False
    if agent == "abl_point_belief":
        kw["book"] = default_book(k=1)
    responder = lambda pend, st: env.answer(pend, iq.spec(pend.spec_id), pend.p_response)  # noqa: E731
    planner = PlannerV2(mode, **pk) if pk else None
    return AgentRuntimeV2(tools=sim_registry(build_registry_v2(), "v2"), responder=responder, planner=planner, **kw)


def run_episode(agent: str, seed: int, cfg: ProcessConfig, *, policy: dict[str, float] | None = None) -> dict[str, Any]:
    ep, hidden, draws = draw_process_episode(seed, cfg)
    engine = "v1" if agent == "v1_legacy" else "v2"
    env = ProcessEnv(ep, hidden, draws, cfg, np.random.default_rng([seed, 9200]), engine)
    opts = {o.name: o for o in build_options(ep.facts, ep.preds)}
    ctx = overrides(1.0) if agent == "abl_no_tempering" else overrides(robust_quantile=0.5) if agent == "abl_mean_autonomy" else overrides(**(policy or {}))
    with ctx:
        if agent == "v1_legacy":
            run, st = AgentRuntime(tools=sim_registry(build_registry(), "v1")).investigate(env)
            elapsed, inquiries = 0.2 * len(run.steps), []
        else:
            rr = _runtime_v2(agent, env).start(env)
            run, st = rr.run, rr.state
            elapsed, inquiries = st.virtual_min, st.inquiries
    d = run.decision
    dtype, V_F = d["type"], env_stakes(ep, cfg)
    cat = load_catalogue()["actions"]
    comm = env.comm_cost
    approval, option, irreversible = "none", "wait", False
    if dtype in ("auto_eligible", "recommend"):
        option = d["action"]
        o = opts[option]
        approval = o.approval if dtype == "auto_eligible" else ("analyst" if o.approval == "none" else o.approval)  # a recommendation waits for a human
        irreversible = not cat[option]["reversible"]
    elif dtype == "escalate":
        option = "escalate"
    res = realise(ep, draws, cfg, option, elapsed, approval, comm, irreversible)
    if dtype == "incident":
        res["utility"] -= 30.0  # a (false) incident declaration for a single parcel wastes supervisor effort
        res["exp_utility"] -= 30.0
    o_name, o_res = oracle_expected_best(ep, draws, cfg)
    wait_res = realise(ep, draws, cfg, "wait", 0.0, "none", 0.0, False)
    o_exp = o_res["exp_utility"]
    auto = dtype == "auto_eligible"
    f = ep.facts
    violation = bool(auto and option in opts and (opts[option].approval != "none" or not opts[option].automatable or (f.get("value") or 0) > load_catalogue()["limits"]["auto_value_max_sar"]
                                                  or (f.get("failed_attempts") or 0) > load_catalogue()["limits"]["auto_max_prior_failures"]))
    tp = true_p(ep, option, cfg) if option not in ("wait", "escalate") else float(WAIT_P[ep.truth])
    from dallal.sim.process import BEHAVIOUR

    relevant = [int(i["spec"] in BEHAVIOUR and (ep.truth in BEHAVIOUR[i["spec"]])) for i in inquiries]
    return {"agent": agent, "regime": cfg.name, "seed": seed, "truth": ep.truth.value, "decision": dtype, "option": option, "named_cause": d["top_cause"], "cause_correct": d["top_cause"] == ep.truth.value,
            "utility": res["exp_utility"], "oracle_utility": o_exp, "regret": o_exp - res["exp_utility"], "protected_prob": res["p"], "utility_realised": res["utility"], "regret_realised": o_res["utility"] - res["utility"],
            "protected": bool(res["success"]), "oracle_protected": bool(o_res["success"]),
            "harmful_auto": bool(auto and option != "wait" and res["exp_utility"] < wait_res["exp_utility"] - comm), "unsafe_auto": bool(auto and option not in ("wait", "escalate") and tp < 0.35), "auto": auto, "policy_violation": violation,
            "false_resolve": bool(dtype == "resolved" and ep.truth.value != "none" and o_name != "wait"), "n_tools": sum(1 for s in run.steps if not s["tool"].startswith("ask:")),
            "n_questions": len(inquiries), "n_answered": sum(1 for i in inquiries if i["status"] == "answered"), "n_timeouts": sum(1 for i in inquiries if i["status"] == "timed_out"),
            "inquiry_relevance": float(np.mean(relevant)) if relevant else np.nan, "elapsed_min": float(elapsed), "comm_cost": comm, "slack_min": ep.slack_min, "stake": V_F[0], "escalated": dtype == "escalate",
            "recommended": dtype == "recommend", "claimed_eff": d.get("robust_effectiveness"), "posterior": d.get("posterior"), "stability": d.get("decision_stability"), "n_support": d.get("n_support"), "p_unknown": d.get("p_unknown"), "true_p_action": tp, "oracle_option": o_name, "answers": [a.get("answer") for a in env.answers_given], "ask_log": [(a["spec"], a["answer"] is not None, a.get("lat")) for a in env.answers_given]}


def _task(args: tuple) -> dict[str, Any]:
    agent, seed, cfg = args
    return run_episode(agent, seed, cfg)


def _task_pol(args: tuple) -> dict[str, Any]:
    agent, seed, cfg, pol = args
    return run_episode(agent, seed, cfg, policy=pol)


def run_sequence(agent: str, cfg: ProcessConfig, seeds: list[int]) -> list[dict[str, Any]]:
    """Episodes of one environment in order. `v2_value_adaptive` carries learned response statistics from episode to episode (the others are memoryless)."""
    from dallal.agent.v2.response_stats import ResponseStats

    stats = ResponseStats()
    rows = []
    for sd in seeds:
        if agent == "v2_value_adaptive":
            with stats.apply():
                r = run_episode("v2_value", sd, cfg)
            for spec, ok, lat in r["ask_log"]:
                stats.update(spec, ok, lat)
            r["agent"] = agent
        else:
            r = run_episode(agent, sd, cfg)
        rows.append(r)
    return rows


def _seq_task(args: tuple) -> list[dict[str, Any]]:
    return run_sequence(*args)


def run_suite_seq(agents, regimes: dict[str, ProcessConfig], n: int, start: int = 0, workers: int = 1) -> pd.DataFrame:
    tasks = [(a, cfg, list(range(start, start + n))) for cfg in regimes.values() for a in agents]
    if workers <= 1:
        rows = [r for t in tasks for r in _seq_task(t)]
    else:
        import multiprocessing as mp

        with mp.get_context("spawn").Pool(workers) as pool:
            rows = [r for chunk in pool.map(_seq_task, tasks, chunksize=1) for r in chunk]
    return pd.DataFrame(rows)


def run_suite(agents, regimes: dict[str, ProcessConfig], n: int, start: int = 0, workers: int = 1) -> pd.DataFrame:
    tasks = [(a, start + i, cfg) for cfg in regimes.values() for i in range(n) for a in agents]
    if workers <= 1:
        return pd.DataFrame([_task(t) for t in tasks])
    import multiprocessing as mp

    with mp.get_context("spawn").Pool(workers) as pool:
        return pd.DataFrame(pool.map(_task, tasks, chunksize=40))


def paired_effect(df: pd.DataFrame, a: str, b: str, col: str = "utility", n_boot: int = 2000, seed: int = 0) -> dict[str, Any]:
    """Mean paired difference (a - b) with a bootstrap 95% CI, Cohen's d_z, win/loss shares."""
    x = df[df.agent == a].set_index("seed")[col].astype(float)
    y = df[df.agent == b].set_index("seed")[col].astype(float)
    d = (x - y.reindex(x.index)).dropna().to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    boots = np.array([rng.choice(d, len(d)).mean() for _ in range(n_boot)])
    sd = float(d.std(ddof=1)) if len(d) > 1 else 0.0
    return {"n": int(len(d)), "mean_diff": round(float(d.mean()), 3), "ci95": [round(float(np.quantile(boots, 0.025)), 3), round(float(np.quantile(boots, 0.975)), 3)], "d_z": round(float(d.mean() / sd), 3) if sd > 0 else 0.0,
            "wins": round(float((d > 1e-9).mean()), 3), "losses": round(float((d < -1e-9).mean()), 3)}
