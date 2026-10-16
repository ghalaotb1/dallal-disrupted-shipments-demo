"""LLM planner vs the decision-theoretic (EVOI) planner on the SAME simulated episodes (SYNTHETIC, assumption-based; paired by seed).

Contenders:  evoi (v2_value, no LLM)  |  per model: llm-pure, llm-hybrid.   All use the identical simulator truth, tools, closing pipeline and policy gates;
only the choice of the NEXT investigation step differs. Reported: regret vs oracle, unsafe auto-actions, questions asked, tools used, valid-tool-call rate,
agreement with the EVOI planner at the same states, and LLM latency per planning step.
Run: python -I -m dallal.eval.llm_planner_bench N qwen3.5:4b [qwen3.5:9b ...]  -> docs/experiments/llm_planner.json
"""

from __future__ import annotations

import json
import sys
import time

import pandas as pd

from dallal.agent.v2.llm_planner import LLMPlanner
from dallal.config import PATHS
from dallal.sim.runner import run_episode
from dallal.sim.world import TrueModel


def summarise(df: pd.DataFrame) -> dict:
    return {"episodes": int(len(df)), "mean_regret": round(float(df["regret"].mean()), 2), "median_regret": round(float(df["regret"].median()), 2),
            "mean_utility": round(float(df["utility"].mean()), 2), "unsafe_auto_rate": round(float(df["unsafe_auto"].mean()), 3), "mean_questions": round(float(df["n_questions"].mean()), 2),
            "mean_tools": round(float(df["n_tools"].mean()), 2), "escalation_rate": round(float(df["escalated"].mean()), 3), "cause_accuracy": round(float(df["cause_correct"].mean()), 3)}


def main(n: int, models: list[str]) -> None:
    tm = TrueModel()
    rows = [run_episode("v2_value", s, tm) | {"contender": "evoi"} for s in range(n)]
    out: dict = {"origin": "synthetic simulator (misspecified-likelihood, paired seeds); relative comparison under stated assumptions", "n_episodes": n, "contenders": {}, "generated": pd.Timestamp.now().isoformat(timespec="seconds")}
    out["contenders"]["evoi"] = {"summary": summarise(pd.DataFrame(rows))}
    for m in models:
        for mode in ("pure", "hybrid"):
            key = f"{m}|{mode}"
            ep_rows, logs = [], []
            t0 = time.time()
            for s in range(n):
                pl = LLMPlanner(m, mode)
                ep_rows.append(run_episode("v2_llm", s, tm, planner=pl) | {"contender": key})
                logs += pl.log
                print(key, s, ep_rows[-1]["decision"], round(ep_rows[-1]["regret"], 1), f"{time.time() - t0:.0f}s", flush=True)
            df = pd.DataFrame(ep_rows)
            lg = pd.DataFrame(logs)
            valid = lg[lg["valid"]] if len(lg) else lg
            fail_counts = lg["failure"].value_counts().to_dict() if "failure" in lg else {}
            out["contenders"][key] = {"summary": summarise(df), "planning_steps": int(len(lg)), "valid_call_rate": round(float(lg["valid"].mean()), 3) if len(lg) else None, "failures": fail_counts,
                                      "agreement_with_evoi": round(float(valid["agrees"].mean()), 3) if len(valid) else None, "median_latency_s": round(float(lg["latency_s"].median()), 2) if len(lg) else None,
                                      "p95_latency_s": round(float(lg["latency_s"].quantile(0.95)), 2) if len(lg) else None, "mean_output_tokens": round(float(lg["output_tokens"].mean()), 1) if "output_tokens" in lg else None,
                                      "chose_finish_first": round(float((lg["chosen"] == "finish_investigation").mean()), 3) if len(lg) else None}
            out["contenders"][key]["paired_regret_diff_vs_evoi"] = round(float((df["regret"].to_numpy() - pd.DataFrame(rows)["regret"].to_numpy()).mean()), 2)
            (PATHS.docs / "experiments").mkdir(parents=True, exist_ok=True)
            (PATHS.docs / "experiments" / "llm_planner.json").write_text(json.dumps(out, indent=2) + "\n")
            print(key, json.dumps(out["contenders"][key]), flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]), sys.argv[2:])
