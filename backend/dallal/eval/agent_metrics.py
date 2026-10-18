"""Direct agent-performance metrics against the independent PROCESS world's latent ground truth (SYNTHETIC).

What is compared with what (nothing here is scored against the agent's own output):
  * root cause      the agent's belief over causes vs the cause the environment DREW before any tool ran (`Episode.truth`)
  * recovery action the agent's committed action vs the action with the best EXPECTED realised utility given the true cause, the true action-success
                    table (TRUE_P, not the agent's `suitability`) and the true action times - the environment's oracle, not the planner
  * inquiry target  whether the asked party's answer distribution in the environment depends on the true cause (`BEHAVIOUR` in sim/process.py)
  * safety          automatic actions that realised worse than waiting on the same random draws; ground truth = the environment's draws
Re-runs the shared evaluation seeds (100000-101999 per regime, never used for tuning) so beliefs can be read out; the re-run is checked to reproduce the
stored evaluation episode for episode.

Run: python -I -m dallal.eval.agent_metrics   -> docs/experiments/results/agent_metrics.json
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
from typing import Any

import numpy as np
import pandas as pd

from dallal.agent.v2.runtime import AgentRuntimeV2
from dallal.config import PATHS
from dallal.eval.stages import SEEDS, SINGLE_REGIMES
from dallal.recovery.ranking import load_catalogue
from dallal.sim import lab
from dallal.sim.process import (
    ACTION_COST,
    BEHAVIOUR,
    WAIT_P,
    action_minutes,
    draw_process_episode,
    env_stakes,
    feasible,
    regime_set,
    true_p,
)

RESULTS = PATHS.docs / "experiments" / "results"
_LAST: dict[str, float] = {}


def _capture_start(orig):
    def start(self, *a, **k):
        rr = orig(self, *a, **k)
        _LAST.clear()
        _LAST.update({c.value if hasattr(c, "value") else str(c): float(p) for c, p in rr.state.belief.p_cause().items()})
        return rr
    return start


def oracle_table(seed: int, cfg) -> dict[str, float]:
    """Expected realised utility of every option under the TRUE cause (the environment's own numbers), incl. waiting."""
    ep, _, d = draw_process_episode(seed, cfg)
    V, F = env_stakes(ep, cfg)
    cat = load_catalogue()["actions"]
    out = {"wait": WAIT_P[ep.truth] * V - (1 - WAIT_P[ep.truth]) * F}
    for a in cat:
        if not feasible(ep, a):
            continue
        p = true_p(ep, a, cfg) * float(action_minutes(a, d, cat[a]["approval"]) <= ep.slack_min)
        out[a] = p * V - (1 - p) * F - ACTION_COST[a]
    return out


def _episode(args: tuple[str, int]) -> dict[str, Any]:
    regime, seed = args
    cfg = regime_set()[regime]
    AgentRuntimeV2.start = _capture_start(_ORIG)
    r = lab.run_episode("v2_value", seed, cfg)
    pc = dict(_LAST)
    tab = oracle_table(seed, cfg)
    order = sorted(pc, key=pc.get, reverse=True)
    opt = r["option"]
    ranked = sorted(tab, key=tab.get, reverse=True)
    return {"regime": regime, "seed": seed, "truth": r["truth"], "decision": r["decision"], "option": opt, "oracle_option": r["oracle_option"], "cause_correct": r["cause_correct"],
            "top1": order[0] == r["truth"], "top3": r["truth"] in order[:3], "p_truth": pc.get(r["truth"], 0.0), "top_p": pc[order[0]],
            "opt_rank": ranked.index(opt) + 1 if opt in tab else None, "opt_eu": tab.get(opt), "wait_eu": tab["wait"], "oracle_eu": tab[ranked[0]],
            "inquiries": [(s, ok) for s, ok, _ in r["ask_log"]], "ask_truth": r["truth"], "auto": r["auto"], "harmful_auto": r["harmful_auto"]}


_ORIG = AgentRuntimeV2.start


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [float("nan")] * 2
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(float(c - h), 4), round(float(c + h), 4)]


def rate(mask: pd.Series | np.ndarray) -> dict[str, Any]:
    m = np.asarray(mask, dtype=bool)
    return {"pct": round(100 * float(m.mean()), 2), "k": int(m.sum()), "n": int(len(m)), "ci95_pct": [round(100 * x, 2) for x in wilson(int(m.sum()), int(len(m)))]}


def main(n_per_regime: int = 2000) -> None:
    seeds = range(SEEDS["single"], SEEDS["single"] + n_per_regime)
    jobs = [(r, s) for r in SINGLE_REGIMES for s in seeds]
    with mp.get_context("spawn").Pool(max(2, mp.cpu_count() - 1)) as pool:
        rows = pool.map(_episode, jobs, chunksize=50)
    df = pd.DataFrame(rows)
    stored = pd.read_parquet(PATHS.root / ".data" / "eval_raw" / "single.parquet")
    stored = stored[stored.agent == "v2_value"].set_index(["regime", "seed"])
    chk = df.set_index(["regime", "seed"]).join(stored[["option", "cause_correct"]], rsuffix="_stored")
    repro = {"episodes": int(len(chk)), "option_identical": rate(chk.option == chk.option_stored)["pct"], "cause_identical": rate(chk.cause_correct == chk.cause_correct_stored)["pct"]}
    out: dict[str, Any] = {"label": "SYNTHETIC process world - latent ground truth drawn by the environment; not real-world validation", "reproduction_of_stored_run": repro,
                           "n_episodes": int(len(df)), "regimes": SINGLE_REGIMES}
    # --- root cause ---------------------------------------------------------------------------------------------------------------------------------
    prior = df.truth.value_counts(normalize=True)
    out["root_cause"] = {"top1": rate(df.top1), "top3": rate(df.top3), "majority_class_top1_pct": round(100 * float(prior.iloc[0]), 2), "majority_class": prior.index[0],
                         "top3_prior_baseline_pct": round(100 * float(prior.iloc[:3].sum()), 2), "top1_excluding_truth_unknown": rate(df[df.truth != "unknown"].top1),
                         "top1_by_regime": {r: rate(g.top1) for r, g in df.groupby("regime")},
                         "top1_when_committed": rate(df[df.decision.isin(["auto_eligible", "recommend"])].top1),
                         "top1_confident_gt85": rate(df[df.top_p > 0.85].top1), "share_confident_gt85": rate(df.top_p > 0.85)}
    df["bin"] = pd.cut(df.top_p, [0, .3, .5, .7, .85, .95, 1.0001])
    cal = df.groupby("bin", observed=True).agg(n=("top1", "size"), mean_conf=("top_p", "mean"), acc=("top1", "mean"))
    out["root_cause"]["calibration"] = {"ece": round(float((cal.n * (cal.mean_conf - cal.acc).abs()).sum() / cal.n.sum()), 4), "bins": cal.round(4).reset_index().astype({"bin": str}).to_dict("records")}
    out["root_cause"]["per_cause_recall_top1"] = {c: rate(g.top1) for c, g in df.groupby("truth")}
    # --- recovery action ----------------------------------------------------------------------------------------------------------------------------
    com = df[df.decision.isin(["auto_eligible", "recommend"])]
    maj = com.oracle_option.value_counts(normalize=True)
    out["recovery_action"] = {
        "all_episodes_exact_agreement": rate(df.option == df.oracle_option),
        "all_episodes_note": "includes escalations, which the oracle never chooses, and 'resolved' (wait); not a fair accuracy figure",
        "decision_mix_pct": (100 * df.decision.value_counts(normalize=True)).round(2).to_dict(),
        "committed_coverage": rate(df.decision.isin(["auto_eligible", "recommend"])),
        "committed_exact_agreement": rate(com.option == com.oracle_option),
        "committed_in_oracle_top2": rate(com.opt_rank <= 2),
        "committed_beats_waiting": rate(com.opt_eu > com.wait_eu),
        "committed_majority_action_baseline_pct": round(100 * float(maj.iloc[0]), 2), "committed_majority_action": maj.index[0],
        "committed_mean_oracle_regret": round(float((com.oracle_eu - com.opt_eu).mean()), 2),
        "committed_exact_by_regime": {r: rate(g.option == g.oracle_option) for r, g in com.groupby("regime")},
        "resolved_correct": rate(df[df.decision == "resolved"].truth == "none"),
        "resolved_correct_or_oracle_wait": rate(df[df.decision == "resolved"].oracle_option == "wait"),
        "escalated_share": rate(df.decision == "escalate"),
    }
    # --- inquiry targets ----------------------------------------------------------------------------------------------------------------------------
    qs = [(s, t) for ql, t in zip(df.inquiries, df.truth, strict=True) for s, _ in ql]
    rel = np.array([t in BEHAVIOUR[s] for s, t in qs], dtype=bool)
    rand = np.mean([np.mean([t in BEHAVIOUR[s] for s in BEHAVIOUR]) for _, t in qs]) if qs else float("nan")
    ans = np.array([ok for ql in df.inquiries for _, ok in ql], dtype=bool)
    out["inquiry_target"] = {"questions": rate(rel), "random_target_baseline_pct": round(100 * float(rand), 2), "asked_cases": rate(df.inquiries.map(len) > 0),
                             "answered_share_of_questions": rate(ans), "relevant_among_answered": rate(rel[ans]) if ans.any() else None,
                             "relevant_by_spec": {s: rate(np.array([t in BEHAVIOUR[s] for s2, t in qs if s2 == s])) for s in BEHAVIOUR if any(s2 == s for s2, _ in qs)}}
    # --- safety (held-out re-evaluation seeds 500000+, policy chosen on seeds 0-2999) ---------------------------------------------------------------------
    sn = pd.read_parquet(PATHS.root / ".data" / "eval_raw" / "safety_new.parquet")
    so = pd.read_parquet(PATHS.root / ".data" / "eval_raw" / "safety_old.parquet")

    def safety(s: pd.DataFrame) -> dict[str, Any]:
        a = s[s.auto]
        return {"episodes": int(len(s)), "auto_actions": rate(s.auto), "harmful_auto_per_case": rate(s.harmful_auto), "harmful_among_auto": rate(a.harmful_auto),
                "unsafe_auto_true_p_lt_035": rate(s.unsafe_auto), "auto_oracle_optimal": rate(a.option == a.oracle_option), "policy_violations": rate(s.policy_violation),
                "false_resolve_per_case": rate(s.false_resolve)}

    out["safety"] = {"new_policy": safety(sn), "previous_policy": safety(so), "regimes_in_safety_eval": sorted(sn.regime.unique().tolist())}
    (RESULTS / "agent_metrics.json").write_text(json.dumps(out, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n")
    df.drop(columns=["bin"]).astype({"inquiries": str}).to_csv(RESULTS / "agent_metrics_episodes.csv", index=False, float_format="%.5g")
    print(json.dumps({k: out[k] for k in ("reproduction_of_stored_run",)}, indent=1))


def _dist(table: dict, cause) -> dict[str, float]:
    d = table.get(cause, table.get("default"))
    z = sum(d.values())
    return {k: v / z for k, v in d.items()}


def discrimination(spec: str, truth: str) -> float:
    """Total-variation distance between the answer distribution under the TRUE cause and under 'any other cause' (environment prior mix).

    Near 0: the answer would read the same whether or not this cause holds (an uninformative question for this case). 1: the answer identifies it.
    """
    from dallal.agent.belief import Cause
    from dallal.sim.process import MIX

    t = BEHAVIOUR[spec]
    ct = Cause(truth)
    others = {c: w for c, w in MIX.items() if c != ct}
    z = sum(others.values())
    keys = {k for c in [*others, ct] for k in _dist(t, c)}
    pt = _dist(t, ct)
    po = {k: sum(w / z * _dist(t, c).get(k, 0.0) for c, w in others.items()) for k in keys}
    return 0.5 * sum(abs(pt.get(k, 0.0) - po[k]) for k in keys)


def post_inquiry(thresholds: tuple[float, ...] = (0.2, 0.3, 0.5)) -> None:
    """Stricter inquiry-target metric from the saved episodes: does the asked party's answer discriminate the TRUE cause from the rest?"""
    import ast

    df = pd.read_csv(RESULTS / "agent_metrics_episodes.csv")
    qs = [(s, t) for ql, t in zip(df.inquiries, df.truth, strict=True) for s, _ in ast.literal_eval(ql)]
    tv = np.array([discrimination(s, t) for s, t in qs])
    rnd = np.array([np.mean([discrimination(s, t) for s in BEHAVIOUR]) for _, t in qs])
    res: dict[str, Any] = {"questions": len(qs), "mean_tv_asked": round(float(tv.mean()), 4), "mean_tv_random_target": round(float(rnd.mean()), 4)}
    for th in thresholds:
        rnd_hit = np.mean([np.mean([discrimination(s, t) >= th for s in BEHAVIOUR]) for _, t in qs])
        res[f"share_tv_ge_{th}"] = {**rate(tv >= th), "random_target_baseline_pct": round(100 * float(rnd_hit), 2)}
    res["by_spec"] = {s: {"n": int(sum(1 for q, _ in qs if q == s)), "mean_tv": round(float(np.mean([discrimination(q, t) for q, t in qs if q == s])), 3)} for s in BEHAVIOUR if any(q == s for q, _ in qs)}
    path = RESULTS / "agent_metrics.json"
    out = json.loads(path.read_text())
    out["inquiry_target"]["discrimination"] = res
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--post-inquiry":
        post_inquiry()
    else:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 2000)
