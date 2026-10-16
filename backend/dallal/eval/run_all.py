"""Reproduce every number in the evaluation report.

    python -I -m dallal.eval.run_all                 # full run (~45-60 min on an Apple-silicon laptop; 6 worker processes)
    python -I -m dallal.eval.run_all --quick         # smoke run (~5 min) with small samples: same code, wider intervals
    python -I -m dallal.eval.run_all --stages single,network
Stages: single ablation sensitivity network safety inquiry_effect (the last reads single's raw output)   (then:  python -I -m dallal.eval.charts && python -I -m dallal.eval.report_v2)
Real-data stages are separate because they need the third-party datasets locally:  python -I -m dallal.ml.train && python -I -m dallal.eval.bridge_eval
LLM stages need a local Ollama:  python -I -m dallal.eval.reply_bench qwen3.5:4b qwen3.5:9b ; python -I -m dallal.eval.llm_planner_bench 24 qwen3.5:4b qwen3.5:9b
Everything synthetic here is labelled SYNTHETIC in its output; fixed seed ranges are listed in dallal/eval/stages.py.
"""

from __future__ import annotations

import argparse
import time

from dallal.eval import stages as S


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--stages", default="single,inquiry_effect,ablation,sensitivity,network,safety")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--only-regimes", default="", help="comma list; with --stages single, adds/refreshes just those regimes")
    a = ap.parse_args()
    q = a.quick
    only = [r for r in a.only_regimes.split(",") if r] or None
    plan = {"single": lambda: S.stage_single(120 if q else 2000, a.workers, only), "ablation": lambda: S.stage_ablation(120 if q else 1500, a.workers),
            "sensitivity": lambda: S.stage_sensitivity(12 if q else 60, 80 if q else 250, a.workers), "network": lambda: S.stage_network(40 if q else 400, a.workers),
            "safety": lambda: S.stage_safety(120 if q else 1500, a.workers), "inquiry_effect": lambda: S.stage_inquiry_effect()}
    manifest = {}
    for name in a.stages.split(","):
        t0 = time.time()
        manifest[name] = {**plan[name](), "seconds": round(time.time() - t0), "quick": q}
        print(f"[{name}] done in {manifest[name]['seconds']}s", flush=True)
    import json as _json

    name = "manifest" + ("_quick" if q else "")
    f = S.RESULTS / f"{name}.json"
    old = _json.loads(f.read_text()) if f.exists() else {}
    S._save(name, {**old, **manifest})  # stages can be run separately; keep the record of the others


if __name__ == "__main__":
    main()
