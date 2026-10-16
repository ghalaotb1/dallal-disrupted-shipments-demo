"""Render docs/experiments/README.md from the committed experiment JSON files. Synthetic and real-data results are kept in separate sections.

Run: python -I -m dallal.eval.report
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dallal.config import PATHS

EXP = PATHS.docs / "experiments"
ML = PATHS.docs / "ml"


def _load(p: Path) -> dict[str, Any] | None:
    return json.loads(p.read_text()) if p.exists() else None


def main() -> None:
    md = ["# Dallal experiments", "",
          "Two kinds of evidence, never mixed:", "",
          "* **Real-data model metrics** (Part A): models fitted on real public delivery datasets, evaluated on later held-out time windows. They describe those datasets, **not SPL**.",
          "* **Synthetic decision experiments** (Part B): agents run on a generative simulator with *misspecified* likelihoods (the world differs from what the agent believes). Utilities are SAR-equivalents from `utility.yaml` - **assumptions**. Results are *relative* comparisons under stated assumptions, not forecasts of money saved.", "",
          "Regenerate everything: see the commands at the end of this file.", "", "## Part A - real data: trained, calibrated risk models", ""]
    models = _load(ML / "models.json")
    if models:
        md += ["| model | source | target | train / valid / test rows | test ROC-AUC (95% CI) | test PR-AUC (base rate) | lift@10% | Brier vs base-rate | ECE | chosen on validation |", "|---|---|---|---|---|---|---|---|---|---|"]
        for mid, c in models["models"].items():
            t, sp = c["metrics"]["test"], c["split"]
            ch = c["metrics"]["chosen"]
            md.append(f"| `{mid}` | {c['source']} | {c['target']} | {sp['train']:,} / {sp['valid']:,} / {sp['test']:,} | {t['roc_auc']:.3f} ({c['metrics']['test_auc_95ci'][0]:.2f}-{c['metrics']['test_auc_95ci'][1]:.2f}) | {t['pr_auc']:.3f} ({t['prevalence']:.1%}) | {t['lift@top10%']:.1f}x | "
                      f"{t['brier']:.4f} vs {t['brier_prevalence_baseline']:.4f} | {t['ece']:.4f} | {ch['estimator']} / {ch['feature_set']} |")
        md += ["", "Protocol: chronological train/valid/test with embargo; estimator, feature set and calibrator chosen on validation only; test touched once. Limits: the Olist late rate drifted between validation and test, so its calibration does not transfer (ranking is what to trust); the Amazon model ranks only moderately (0.6% base rate). Full cards: `docs/ml/models.json`.", ""]
    seq = _load(ML / "sequence_experiment.json")
    if seq:
        md += ["### Sequence model vs tabular (LaDe slow-task risk)", "", "| contender | valid PR-AUC | test PR-AUC | test ROC-AUC |", "|---|---|---|---|"]
        md += [f"| `{k}` | {v['valid']['pr_auc']:.3f} | {v['test']['pr_auc']:.3f} | {v['test']['roc_auc']:.3f} |" for k, v in seq["contenders"].items()]
        md += ["", f"**Decision:** {seq['decision']['reading']}", ""]

    md += ["## Part B - synthetic: decisions", ""]
    ss = _load(EXP / "single_shipment.json")
    if ss:
        md += [f"### B1. Single shipment: do value-based questions help? ({ss['episodes']} paired episodes)", "",
               "| agent | mean regret vs oracle | unsafe-auto rate | questions/case | escalation | mean minutes used | comm. cost |", "|---|---|---|---|---|---|---|"]
        md += [f"| `{a}` | {v['mean_regret']:.1f} | {v['unsafe_auto_rate']:.1%} | {v['questions_per_case']:.2f} | {v['escalation_rate']:.0%} | {v['mean_elapsed_min']:.1f} | {v['mean_comm_cost']:.2f} |" for a, v in ss["agents"].items()]
        md += ["", "Paired regret difference (negative = better):", ""]
        md += [f"* `{k}`: {v['mean']:+.1f} (95% CI {v['ci95'][0]:+.1f} to {v['ci95'][1]:+.1f})" for k, v in ss["paired_regret_difference"].items()]
        md += ["", "Unsafe-auto = the agent auto-executed an action whose TRUE success probability was below 0.35. Counts are small (a handful of episodes); the cases are cheap actions aimed at a neighbouring cause (address vs recipient). Do not over-read the rate.", ""]
    nr = _load(EXP / "network_recovery.json")
    if nr:
        md += [f"### B2. Systemic incident: one piece of evidence, many shipments ({nr['episodes_per_regime']} paired incidents per regime)", "",
               "Strategies: independent naive / independent strong / desk-greedy (a strong human-desk heuristic) / independent with per-parcel questions / coordinated (joint MILP) without question / coordinated with ONE value-gated question / always-ask ablation / oracle.", ""]
        for reg, v in nr["regimes"].items():
            md += [f"**{reg}**", "", "| strategy | mean regret | questions sent | on-time parcels | deferred parcels | asked |", "|---|---|---|---|---|---|"]
            for s, t in v["strategies"].items():
                md.append(f"| `{s}` | {t['mean_regret']:.0f} | {t['mean_messages']:.2f} | {t['mean_on_time_parcels']:.2f} | {t['mean_deferred']:.2f} | {t.get('asked_rate', '')} |")
            md += ["", "Paired gains (SAR-eq per incident, 95% bootstrap CI; win/loss = share of incidents):", ""]
            md += [f"* {k}: {t['mean_gain']:+.0f} ({t['ci95'][0]:+.0f} to {t['ci95'][1]:+.0f}), wins {t['win_rate']:.0%}, losses {t['loss_rate']:.0%}" for k, t in v["paired"].items()]
            md.append("")
        md += ["Assumptions (all printed in the JSON): prior P(long blockage) 0.30; dispatcher reply probability and latency from `inquiries.yaml`; answer likelihoods `LIK`; resource counts/capacities per regime; pickup acceptance 0.75; deferral cost share 0.4.", ""]
    lp = _load(EXP / "llm_planner.json")
    if lp:
        md += [f"### B3. LLM planner vs the decision-theoretic planner ({lp['n_episodes']} paired episodes, simulator)", "",
               "| contender | mean regret | paired regret diff vs EVOI | questions/case | valid tool-call rate | agrees with EVOI | median / p95 latency per step (s) | failures |", "|---|---|---|---|---|---|---|---|"]
        for k, v in lp["contenders"].items():
            s = v["summary"]
            md.append(f"| `{k}` | {s['mean_regret']:.1f} | {v.get('paired_regret_diff_vs_evoi', 0):+.1f} | {s['mean_questions']:.2f} | {v.get('valid_call_rate', '')} | {v.get('agreement_with_evoi', '')} | {v.get('median_latency_s', '')} / {v.get('p95_latency_s', '')} | {v.get('failures', '')} |")
        md.append("")
    rb = _load(EXP / "reply_interpretation.json")
    if rb:
        md += [f"### B4. Free-text reply interpretation ({rb['set']['n']} hand-written Arabic/English replies, {rb['set']['answerable']} answerable)", "",
               "| interpreter | coverage of answerable | false-accept rate | abstains correctly on unanswerable | median latency (s) |", "|---|---|---|---|---|"]
        r = rb["rules_only"]
        md.append(f"| rules only | {r['coverage_of_answerable']:.0%} | {r['false_accept_rate']:.1%} ({r['false_accepts']}) | {r['abstain_correct_on_unanswerable']:.0%} | - |")
        for m, v in rb["models"].items():
            for k in ("llm_only", "rules_then_llm"):
                x = v[k]
                md.append(f"| {m} {k.replace('_', ' ')} | {x['coverage_of_answerable']:.0%} | {x['false_accept_rate']:.1%} ({x['false_accepts']}) | {x['abstain_correct_on_unanswerable']:.0%} | {v['median_latency_s']} |")
        md += ["", "Set authored by the team (not real traffic). A false accept would become evidence, so it is the metric that matters.", ""]
    md += ["## Reproduce", "", "```bash", "cd backend", "python -I -m dallal.ml.train                       # real-data models (needs built canonical tables)", "python -I -m dallal.ml.sequence                    # needs `pip install torch`",
           "python -I -m dallal.sim.single_exp 400            # B1", "python -I -m dallal.sim.network_exp 300           # B2", "python -I -m dallal.eval.headline                 # end-to-end trace",
           "python -I -m dallal.eval.llm_planner_bench 24 qwen3.5:4b qwen3.5:9b   # B3 (local Ollama)", "python -I -m dallal.eval.reply_bench qwen3.5:4b qwen3.5:9b           # B4", "python -I -m dallal.eval.report", "```", ""]
    (EXP / "README.md").write_text("\n".join(md))
    print("wrote", EXP / "README.md")


if __name__ == "__main__":
    main()
