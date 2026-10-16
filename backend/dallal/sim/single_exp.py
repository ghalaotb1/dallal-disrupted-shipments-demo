"""Single-shipment experiment on the generative simulator (SYNTHETIC; paired by seed): do value-based inquiries help?

Contenders: v1_legacy (information-gain planner, point-estimate Bayes, posterior-threshold policy), v2_no_inquiry (database tools only),
v2_infogain (asks whenever entropy reduction is high), v2_value (asks when net value of information is positive).
The simulator's true likelihood tables differ from the agent's (misspecification), 8% of tool calls hit data gaps, and response rates differ.
Run: python -I -m dallal.sim.single_exp [episodes]  -> docs/experiments/single_shipment.json
"""

from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from dallal.config import PATHS
from dallal.sim.runner import AGENTS, run_suite
from dallal.sim.world import TrueModel


def boot(x: np.ndarray, n: int = 1000, seed: int = 0) -> list[float]:
    rng = np.random.default_rng(seed)
    m = [rng.choice(x, len(x)).mean() for _ in range(n)]
    return [round(float(np.quantile(m, 0.025)), 2), round(float(np.quantile(m, 0.975)), 2)]


def main(n: int) -> None:
    df = run_suite(n, TrueModel(), AGENTS)
    df["stake_band"] = pd.qcut(df["stake"], 3, labels=["low", "mid", "high"])
    rep: dict = {"origin": "synthetic simulator, misspecified likelihoods, paired by seed", "episodes": n, "agents": {}, "paired_regret_difference": {}, "by_stake": {}}
    for a in AGENTS:
        d = df[df.agent == a]
        rep["agents"][a] = {"mean_regret": round(float(d.regret.mean()), 2), "median_regret": round(float(d.regret.median()), 2), "mean_utility": round(float(d.utility.mean()), 2),
                            "unsafe_auto_rate": round(float(d.unsafe_auto.mean()), 4), "escalation_rate": round(float(d.escalated.mean()), 3), "questions_per_case": round(float(d.n_questions.mean()), 3),
                            "answered_per_case": round(float(d.n_answered.mean()), 3), "timeouts_per_case": round(float(d.n_timeouts.mean()), 3), "tools_per_case": round(float(d.n_tools.mean()), 2),
                            "mean_elapsed_min": round(float(d.elapsed_min.mean()), 1), "mean_comm_cost": round(float(d.comm_cost.mean()), 2), "cause_accuracy": round(float(d.cause_correct.mean()), 3)}
    base = df[df.agent == "v2_no_inquiry"].set_index("seed").regret
    for a in ("v1_legacy", "v2_infogain", "v2_value"):
        diff = (df[df.agent == a].set_index("seed").regret - base).to_numpy()
        rep["paired_regret_difference"][f"{a}_minus_v2_no_inquiry"] = {"mean": round(float(diff.mean()), 2), "ci95": boot(diff)}
    d = (df[df.agent == "v2_value"].set_index("seed").regret - df[df.agent == "v2_infogain"].set_index("seed").regret).to_numpy()
    rep["paired_regret_difference"]["v2_value_minus_v2_infogain"] = {"mean": round(float(d.mean()), 2), "ci95": boot(d)}
    for b in ("low", "mid", "high"):
        rep["by_stake"][b] = {a: {"mean_regret": round(float(df[(df.agent == a) & (df.stake_band == b)].regret.mean()), 2), "questions": round(float(df[(df.agent == a) & (df.stake_band == b)].n_questions.mean()), 2)} for a in AGENTS}
    (PATHS.docs / "experiments").mkdir(parents=True, exist_ok=True)
    (PATHS.docs / "experiments" / "single_shipment.json").write_text(json.dumps(rep, indent=2) + "\n")
    print(json.dumps(rep["agents"], indent=1))
    print(json.dumps(rep["paired_regret_difference"], indent=1))


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 400)
