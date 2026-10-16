"""Evaluation stages. Each stage is deterministic given its seed range and writes small machine-readable results (JSON/CSV) under docs/experiments/results/.

Seed ranges (never overlap): 0-2999 development (autonomy-policy sweep ONLY) | 100000+ single-shipment evaluation | 200000+ ablations | 300000+ sensitivity | 400000+ network |
500000+ safety re-evaluation. The policy chosen on development seeds is never scored on them.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

from dallal.config import PATHS
from dallal.sim import lab, network_lab
from dallal.sim.process import ProcessConfig, regime_set

RESULTS = PATHS.docs / "experiments" / "results"
SEEDS = {"dev": 0, "single": 100_000, "ablation": 200_000, "sensitivity": 300_000, "network": 400_000, "safety": 500_000}
SINGLE_REGIMES = [r for r in regime_set() if r != "systemic_incidents"]


def _save(name: str, obj: Any) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, pd.DataFrame):
        obj.to_csv(RESULTS / f"{name}.csv", index=False, float_format="%.5g")
    else:
        (RESULTS / f"{name}.json").write_text(json.dumps(obj, indent=2, default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n")


def mean_ci(x: pd.Series) -> dict[str, float]:
    x = x.astype(float).dropna()
    se = float(x.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else 0.0
    return {"mean": round(float(x.mean()), 4), "ci95": [round(float(x.mean() - 1.96 * se), 4), round(float(x.mean() + 1.96 * se), 4)]}


SINGLE_METRICS = ["utility", "regret", "protected_prob", "harmful_auto", "unsafe_auto", "false_resolve", "auto", "escalated", "recommended", "n_tools", "n_questions", "n_answered", "n_timeouts",
                  "elapsed_min", "comm_cost", "cause_correct", "inquiry_relevance"]


def summarise_single(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (reg, ag), g in df.groupby(["regime", "agent"]):
        r = {"regime": reg, "agent": ag, "n": len(g)}
        for m in SINGLE_METRICS:
            c = mean_ci(g[m])
            r[m] = c["mean"]
            r[m + "_lo"], r[m + "_hi"] = c["ci95"]
        rows.append(r)
    return pd.DataFrame(rows)


def paired_table(df: pd.DataFrame, pairs: list[tuple[str, str]], cols: list[str]) -> pd.DataFrame:
    rows = []
    for reg, g in df.groupby("regime"):
        for a, b in pairs:
            for c in cols:
                e = lab.paired_effect(g, a, b, c)
                rows.append({"regime": reg, "a": a, "b": b, "metric": c, **{k: v for k, v in e.items() if k != "ci95"}, "ci_lo": e["ci95"][0], "ci_hi": e["ci95"][1]})
    return pd.DataFrame(rows)


def _merge(name: str, new: pd.DataFrame, regimes: list[str]) -> pd.DataFrame:
    """Replace the rows of `regimes` in an existing results table (used to add a regime without rerunning the others)."""
    f = RESULTS / f"{name}.csv"
    if f.exists():
        old = pd.read_csv(f)
        new = pd.concat([old[~old.regime.isin(regimes)], new], ignore_index=True)
    return new


def stage_single(n: int, workers: int, only: list[str] | None = None) -> dict[str, Any]:
    regs = {k: v for k, v in regime_set().items() if k in SINGLE_REGIMES and (only is None or k in only)}
    df = lab.run_suite_seq(lab.AGENTS, regs, n, start=SEEDS["single"], workers=workers)
    _raw(df, "single")
    summ = summarise_single(df)
    pairs = [("v2_value", "v2_no_inquiry"), ("v2_value_adaptive", "v2_no_inquiry"), ("v2_value_adaptive", "v2_value"), ("v2_infogain", "v2_no_inquiry"), ("v2_value", "v2_infogain"), ("v2_no_inquiry", "v1_legacy"), ("v2_value", "v1_legacy")]
    pt = paired_table(df, pairs, ["utility", "regret", "protected_prob"])
    if only:
        summ, pt = _merge("single_summary", summ, only), _merge("single_paired", pt, only)
    _save("single_summary", summ)
    _save("single_paired", pt)
    return {"episodes_per_regime_per_agent": n, "regimes": list(regs), "seed_start": SEEDS["single"]}


def _raw(df: pd.DataFrame, name: str) -> None:
    out = PATHS.data / "eval_raw"
    out.mkdir(parents=True, exist_ok=True)
    d = df.copy()
    for c in d.columns:
        if d[c].dtype == object and c not in ("regime", "agent", "strategy", "truth", "decision", "option", "named_cause", "oracle_option", "policy"):
            d[c] = d[c].astype(str)  # list-valued diagnostics (answers, ask_log)
    d.to_parquet(out / f"{name}.parquet")  # git-ignored (.data); the committed results are the aggregated tables


ABLATION_REGIMES = ["baseline", "high_uncertainty", "contradictory_evidence", "urgent_deadlines", "correlated_evidence"]


def stage_ablation(n: int, workers: int) -> dict[str, Any]:
    regs = {k: v for k, v in regime_set().items() if k in ABLATION_REGIMES}
    df = lab.run_suite(lab.ABLATIONS, regs, n, start=SEEDS["ablation"], workers=workers)
    _raw(df, "ablation")
    summ = summarise_single(df)
    _save("ablation_summary", summ)
    pairs = [("v2_value", a) for a in lab.ABLATIONS if a != "v2_value"]
    _save("ablation_paired", paired_table(df, pairs, ["utility", "regret", "n_questions", "harmful_auto", "auto", "false_resolve"]))
    return {"episodes_per_regime_per_variant": n, "regimes": ABLATION_REGIMES, "variants": list(lab.ABLATIONS)}


def random_env(rng: np.random.Generator, i: int) -> ProcessConfig:
    from dallal.agent.belief import Cause

    shift = {Cause.ROUTE_DISRUPTION: float(np.exp(rng.uniform(np.log(.5), np.log(4)))), Cause.NONE: float(np.exp(rng.uniform(np.log(.5), np.log(2))))}
    return ProcessConfig(f"env{i:03d}", data_gap=float(rng.uniform(0, .25)), signal_noise=float(np.exp(rng.uniform(np.log(.5), np.log(2)))), prior_shift=shift,
                         slack_scale=float(np.exp(rng.uniform(np.log(.3), np.log(3)))), p_resp_scale=float(rng.uniform(.2, 1.3)), latency_scale=float(np.exp(rng.uniform(np.log(.5), np.log(4)))),
                         answer_noise=float(rng.uniform(0, .45)), util_scale=float(np.exp(rng.uniform(np.log(.6), np.log(1.6)))), action_scale=float(rng.uniform(.6, 1.3)),
                         comm_scale=float(np.exp(rng.uniform(np.log(.3), np.log(5)))))


def stage_sensitivity(n_envs: int, n: int, workers: int) -> dict[str, Any]:
    rng = np.random.default_rng(SEEDS["sensitivity"])
    envs = {f"env{i:03d}": random_env(rng, i) for i in range(n_envs)}
    df = lab.run_suite_seq(("v2_no_inquiry", "v2_infogain", "v2_value", "v2_value_adaptive"), envs, n, start=SEEDS["sensitivity"], workers=workers)
    rows = []
    for name, g in df.groupby("regime"):
        e = lab.paired_effect(g, "v2_value", "v2_no_inquiry", "utility", n_boot=500)
        e2 = lab.paired_effect(g, "v2_infogain", "v2_no_inquiry", "utility", n_boot=500)
        e3 = lab.paired_effect(g, "v2_value_adaptive", "v2_no_inquiry", "utility", n_boot=500)
        c = envs[name]
        rows.append({"env": name, "value_minus_dbonly": e["mean_diff"], "ci_lo": e["ci95"][0], "ci_hi": e["ci95"][1], "infogain_minus_dbonly": e2["mean_diff"], "adaptive_minus_dbonly": e3["mean_diff"], "adaptive_ci_lo": e3["ci95"][0], "adaptive_ci_hi": e3["ci95"][1], "questions_adaptive": g[g.agent == "v2_value_adaptive"].n_questions.mean(), "questions_value": g[g.agent == "v2_value"].n_questions.mean(),
                     "questions_infogain": g[g.agent == "v2_infogain"].n_questions.mean(), "data_gap": c.data_gap, "signal_noise": c.signal_noise, "slack_scale": c.slack_scale, "p_resp_scale": c.p_resp_scale,
                     "latency_scale": c.latency_scale, "answer_noise": c.answer_noise, "util_scale": c.util_scale, "action_scale": c.action_scale, "comm_scale": c.comm_scale})
    t = pd.DataFrame(rows)
    _save("sensitivity_envs", t)
    knobs = ["data_gap", "signal_noise", "slack_scale", "p_resp_scale", "latency_scale", "answer_noise", "util_scale", "action_scale", "comm_scale"]
    corr = {k: round(float(t[k].corr(t["value_minus_dbonly"], method="spearman")), 3) for k in knobs}
    summ = {"environments": n_envs, "episodes_per_env": n, "value_minus_dbonly": {"median": round(float(t.value_minus_dbonly.median()), 3), "mean": round(float(t.value_minus_dbonly.mean()), 3),
                                                                                  "share_positive": round(float((t.value_minus_dbonly > 0).mean()), 3), "share_significantly_positive": round(float((t.ci_lo > 0).mean()), 3),
                                                                                  "share_significantly_negative": round(float((t.ci_hi < 0).mean()), 3), "p10": round(float(t.value_minus_dbonly.quantile(.1)), 3),
                                                                                  "p90": round(float(t.value_minus_dbonly.quantile(.9)), 3)},
            "infogain_minus_dbonly": {"median": round(float(t.infogain_minus_dbonly.median()), 3), "share_positive": round(float((t.infogain_minus_dbonly > 0).mean()), 3)},
            "adaptive_minus_dbonly": {"median": round(float(t.adaptive_minus_dbonly.median()), 3), "mean": round(float(t.adaptive_minus_dbonly.mean()), 3), "share_positive": round(float((t.adaptive_minus_dbonly > 0).mean()), 3),
                                      "share_significantly_positive": round(float((t.adaptive_ci_lo > 0).mean()), 3), "share_significantly_negative": round(float((t.adaptive_ci_hi < 0).mean()), 3),
                                      "p10": round(float(t.adaptive_minus_dbonly.quantile(.1)), 3), "p90": round(float(t.adaptive_minus_dbonly.quantile(.9)), 3)},
            "spearman_of_benefit_with_knob": corr, "seed_start": SEEDS["sensitivity"]}
    _save("sensitivity_summary", summ)
    return summ


def stage_network(n: int, workers: int) -> dict[str, Any]:
    df = network_lab.run_suite(network_lab.regimes(), n, start=SEEDS["network"], workers=workers)
    _raw(df, "network")
    metrics = ["utility", "regret", "protected_share", "late", "interventions", "messages", "cap_over_requests", "deferred"]
    rows = []
    for (reg, st), g in df.groupby(["regime", "strategy"]):
        r = {"regime": reg, "strategy": st, "n": len(g)}
        for m in metrics:
            c = mean_ci(g[m])
            r[m], r[m + "_lo"], r[m + "_hi"] = c["mean"], c["ci95"][0], c["ci95"][1]
        r["asked_rate"] = float(g["asked"].mean())
        rows.append(r)
    _save("network_summary", pd.DataFrame(rows))
    pairs = [("independent_strong", "independent_naive"), ("coordinated_no_inquiry", "desk_greedy"), ("coordinated_no_inquiry", "independent_strong"), ("coordinated_inquiry", "desk_greedy"),
             ("coordinated_inquiry", "independent_inquiry"), ("coordinated_inquiry", "coordinated_no_inquiry"), ("coordinated_inquiry", "coordinated_always_ask"), ("coordinated_inquiry", "coordinated_inquiry_no_recourse"),
             ("coordinated_inquiry_adaptive", "coordinated_no_inquiry"), ("coordinated_inquiry_adaptive", "coordinated_inquiry"), ("coordinated_inquiry_adaptive", "desk_greedy")]
    prow = []
    for reg, g in df.groupby("regime"):
        for a, b in pairs:
            x = g[g.strategy == a].set_index("seed")
            y = g[g.strategy == b].set_index("seed")
            for m in ("utility", "protected_share", "late"):
                d = (x[m] - y[m].reindex(x.index)).to_numpy(dtype=float)
                rng = np.random.default_rng(0)
                boots = np.array([rng.choice(d, len(d)).mean() for _ in range(1000)])
                sd = d.std(ddof=1)
                prow.append({"regime": reg, "a": a, "b": b, "metric": m, "n": len(d), "mean_diff": round(float(d.mean()), 4), "ci_lo": round(float(np.quantile(boots, .025)), 4), "ci_hi": round(float(np.quantile(boots, .975)), 4),
                             "d_z": round(float(d.mean() / sd), 3) if sd > 0 else 0.0, "wins": round(float((d > 1e-9).mean()), 3), "losses": round(float((d < -1e-9).mean()), 3)})
    _save("network_paired", pd.DataFrame(prow))
    return {"incidents_per_regime": n, "regimes": list(network_lab.regimes()), "strategies": list(network_lab.STRATS), "seed_start": SEEDS["network"]}


def stage_safety(n: int, workers: int) -> dict[str, Any]:
    """Autonomy policy before/after (old: no out-of-pattern gate; new: max_p_unknown = 0.03) on held-out seeds, in every process regime and in the older table-perturbation world."""
    import multiprocessing as mp

    from dallal.sim import runner as sim1
    from dallal.sim.world import TrueModel

    regs = {k: v for k, v in regime_set().items() if k in SINGLE_REGIMES}
    policies = {"old_policy(no_unknown_gate)": {"max_p_unknown": 1.0}, "new_policy(max_p_unknown=0.03)": {"max_p_unknown": 0.03}}
    rows = []
    for pname, pol in policies.items():
        tasks = [("v2_value", SEEDS["safety"] + i, cfg, pol) for cfg in regs.values() for i in range(n)]
        with mp.get_context("spawn").Pool(workers) as pool:
            df = pd.DataFrame(pool.map(lab._task_pol, tasks, chunksize=40))
        for reg, g in df.groupby("regime"):
            a = g[g.auto]
            rows.append({"env": f"process/{reg}", "policy": pname, "n": len(g), "auto_rate": g.auto.mean(), "harmful_per_episode": g.harmful_auto.mean(), "harmful_among_auto": a.harmful_auto.mean() if len(a) else 0.0,
                         "unsafe_true_p_lt_035_per_episode": g.unsafe_auto.mean(), "recommended_rate": g.recommended.mean(), "escalated_rate": g.escalated.mean(), "utility": g.utility.mean(), "regret": g.regret.mean(),
                         "policy_violations": int(g.policy_violation.sum()), "false_resolve": g.false_resolve.mean()})
        _raw(df.assign(policy=pname), "safety_" + pname[:3])
    tm = TrueModel()
    for pname, pol in policies.items():
        with lab.overrides(**pol):
            sdf = pd.DataFrame([sim1.run_episode("v2_value", SEEDS["safety"] + i, tm) for i in range(n)])
        a = sdf[sdf.decision == "auto_eligible"]
        rows.append({"env": "table_perturbation_world(sigma=0.5)", "policy": pname, "n": len(sdf), "auto_rate": float((sdf.decision == "auto_eligible").mean()), "harmful_per_episode": np.nan, "harmful_among_auto": np.nan,
                     "unsafe_true_p_lt_035_per_episode": float(sdf.unsafe_auto.mean()), "recommended_rate": float((sdf.decision == "recommend").mean()), "escalated_rate": float(sdf.escalated.mean()),
                     "utility": float(sdf.utility.mean()), "regret": float(sdf.regret.mean()), "policy_violations": 0, "false_resolve": np.nan})
    t = pd.DataFrame(rows)
    _save("safety_policy_eval", t)
    old = t[t.policy.str.startswith("old")].set_index("env")
    new = t[t.policy.str.startswith("new")].set_index("env")
    pe = new[new.index.str.startswith("process/")]
    summ = {"seeds": SEEDS["safety"], "episodes_per_env": n,
            "process_worlds_mean": {"auto_rate_old": round(float(old.loc[pe.index].auto_rate.mean()), 4), "auto_rate_new": round(float(pe.auto_rate.mean()), 4),
                                    "harmful_per_episode_old": round(float(old.loc[pe.index].harmful_per_episode.mean()), 5), "harmful_per_episode_new": round(float(pe.harmful_per_episode.mean()), 5),
                                    "recommended_old": round(float(old.loc[pe.index].recommended_rate.mean()), 4), "recommended_new": round(float(pe.recommended_rate.mean()), 4),
                                    "utility_old": round(float(old.loc[pe.index].utility.mean()), 3), "utility_new": round(float(pe.utility.mean()), 3)},
            "policy_violations_total": int(t.policy_violations.sum())}
    _save("safety_summary", summ)
    return summ


def stage_inquiry_effect() -> dict[str, Any]:
    """What did asking change? Paired with the same agent's database-only twin on the same episodes (reads the raw single-shipment results written by stage_single)."""
    df = pd.read_parquet(PATHS.data / "eval_raw" / "single.parquet")
    rows = []
    for reg, g in df.groupby("regime"):
        base = g[g.agent == "v2_no_inquiry"].set_index("seed")
        for ag in ("v2_infogain", "v2_value", "v2_value_adaptive"):
            v = g[g.agent == ag].set_index("seed")
            idx = v.index.intersection(base.index)
            v, b = v.loc[idx], base.loc[idx]
            asked = v.n_questions > 0
            changed = (v.option != b.option) & asked
            gain = v.utility - b.utility
            r = {"regime": reg, "agent": ag, "n": len(v), "asked_share": float(asked.mean()), "questions_per_case": float(v.n_questions.mean()), "answered_per_asked_question": float(v.n_answered.sum() / max(v.n_questions.sum(), 1)),
                 "timeout_per_asked_question": float(v.n_timeouts.sum() / max(v.n_questions.sum(), 1)), "inquiry_target_relevant_share": float(v.loc[asked, "inquiry_relevance"].mean()) if asked.any() else np.nan,
                 "decision_changed_share_of_asked": float(changed.sum() / max(asked.sum(), 1)), "mean_gain_when_decision_changed": float(gain[changed].mean()) if changed.any() else np.nan,
                 "mean_gain_when_asked_but_unchanged": float(gain[asked & ~changed].mean()) if (asked & ~changed).any() else np.nan, "mean_gain_all": float(gain.mean()),
                 "minutes_to_decision_with_asking": float(v.elapsed_min.mean()), "minutes_to_decision_db_only": float(b.elapsed_min.mean()), "comm_cost": float(v.comm_cost.mean())}
            rows.append(r)
    t = pd.DataFrame(rows)
    _save("inquiry_effect", t)
    return {"rows": len(t)}


def stage_ensemble(n: int, workers: int) -> dict[str, Any]:
    """Stress test of the 24-table ensemble where it is supposed to matter: the agent's likelihood tables are wrong by a controlled amount (sigma_true). Table-perturbation world."""
    import multiprocessing as mp

    rows = []
    for sigma in (0.2, 0.5, 1.0):
        with mp.get_context("spawn").Pool(workers) as pool:
            res = pool.map(_ens_task, [(sigma, s, k) for s in range(SEEDS["ablation"] + 90_000, SEEDS["ablation"] + 90_000 + n) for k in (24, 1)], chunksize=40)
        df = pd.DataFrame(res)
        for k in (24, 1):
            g = df[df.k == k]
            rows.append({"sigma_true": sigma, "ensemble_size": k, "n": len(g), "regret": g.regret.mean(), "regret_lo": g.regret.mean() - 1.96 * g.regret.std() / np.sqrt(len(g)), "regret_hi": g.regret.mean() + 1.96 * g.regret.std() / np.sqrt(len(g)),
                         "unsafe_auto": g.unsafe_auto.mean(), "auto": g.auto.mean(), "questions": g.n_questions.mean(), "escalated": g.escalated.mean()})
        a, b = df[df.k == 24].set_index("seed").regret, df[df.k == 1].set_index("seed").regret
        d = (b - a).to_numpy()  # >0: the ensemble has lower regret
        rows[-2]["paired_regret_reduction_by_ensemble"] = float(d.mean())
        rows[-2]["paired_ci_lo"], rows[-2]["paired_ci_hi"] = float(d.mean() - 1.96 * d.std() / np.sqrt(len(d))), float(d.mean() + 1.96 * d.std() / np.sqrt(len(d)))
    t = pd.DataFrame(rows)
    _save("ensemble_stress", t)
    return {"episodes_per_cell": n}


def _ens_task(args: tuple) -> dict[str, Any]:
    from dallal.agent.v2.bayes import default_book
    from dallal.sim import runner as sim1
    from dallal.sim.world import TrueModel

    sigma, seed, k = args
    r = sim1.run_episode("v2_value", seed, TrueModel(sigma_true=sigma), book=default_book(k=k))
    return {"sigma_true": sigma, "k": k, "seed": seed, "regret": r["regret"], "unsafe_auto": r["unsafe_auto"], "auto": r["decision"] == "auto_eligible", "n_questions": r["n_questions"], "escalated": r["escalated"]}
