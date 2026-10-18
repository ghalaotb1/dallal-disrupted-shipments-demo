# Direct agent-performance metrics (SYNTHETIC ground truth)

Source: `python -I -m dallal.eval.agent_metrics` → `results/agent_metrics.json`, `results/agent_metrics_episodes.csv` (per-episode). Safety figures come from the stored held-out safety run (`backend/.data/eval_raw/safety_*.parquet`).

**Ground truth is simulated.** The independent process world draws the true cause, hidden physical state, action success probabilities and timings *before* the agent runs. Nothing is scored against the agent's own output. No metric below is real-world validation; there is no labelled SPL data. Evaluated agent: `v2_value` (the shipped configuration), seeds 100000–101999 in each of 10 regimes (n = 20,000), never used for tuning. The re-run reproduces the stored evaluation exactly (20,000/20,000 identical decisions and causes). Intervals are 95% Wilson.

## Reportable metrics

| # | Metric | Result | n | Baseline | 
|---|---|---|---|---|
| 1 | Root-cause Top-1 | **65.7%** (65.1–66.4) | 20,000 | 18.6% (always predict most common cause) |
| 1b | Root-cause Top-3 | **84.3%** (83.8–84.8) | 20,000 | 51.7% (3 most common causes) |
| 1c | Top-1 when the agent is confident (top probability > 0.85, 39.8% of cases) | **90.2%** (89.5–90.8) | 7,961 | — |
| 1d | Calibration of the top-cause probability (ECE) | **0.029** | 20,000 | — |
| 2 | Action agreement with the oracle, on cases where Dallal commits to an action | **83.4%** exact (82.5–84.3); 88.4% within oracle top-2; 88.2% better than waiting | 6,631 (33.2% of cases) | 30.5% (always the most common action); legacy agent 69.1% on its own committed cases (n = 10,452) |
| 3 | Inquiry targets that discriminate the true cause (answer distribution under the true cause differs from "any other cause" by total variation ≥ 0.5) | **68.5%** (67.5–69.4) | 9,297 questions | 25.3% (random question); ≥ 0.3: 76.0% vs 27.0% |
| 4 | Harmful automatic actions (realised worse than waiting on identical draws) | **0.42 per 100 cases** (0.33–0.54); 4.3% of automatic actions; automatic actions are oracle-optimal 94.8% of the time | 15,000 cases, 1,472 automatic | previous policy 1.41 per 100 (7.9% of its 2,700 automatic actions) |

## Definitions

- **Top-1 / Top-3:** the true cause is the agent's most probable / one of its three most probable causes in the final belief (9 causes, including `none` and `unknown`).
- **Oracle:** zero-cost, zero-delay agent that knows the true cause and picks the option with the best expected realised utility under the environment's own success table and action times. It is not the planner.
- **Committed:** the decision is `auto_eligible` or `recommend`. The other cases are `escalate` (33.8%) or `resolved` (33.0%).
- **Harmful automatic action:** executed automatically and realised worse than waiting, on the same random draws.

## Limitations

- All metrics are on a simulation the team wrote. The environment is independent of the agent's likelihood tables in code, not independent of the authors' assumptions about how delivery problems look.
- Cause accuracy is **not better than the legacy agent** (65.1% legacy vs 65.7%, n = 20,000 each). The redesign's gains are in decisions and cost, not diagnosis.
- Accuracy varies by cause and regime: 86.7% for `none`, 80.5% recipient unavailable, but 17.2% for `unknown`, 35.8% attempt not completed, 35.4% pickup point unavailable; 56.4% in the unseen-behaviour/outage regime, 73.95% in the low-uncertainty regime.
- Only 33% of cases end in a committed action; 34% are escalated to a human. Metric 2 is selective accuracy, not accuracy over all cases. Exact agreement over all 20,000 cases is 36.1% and is not a fair figure, because escalations can never match the oracle.
- False-resolve: 8.7% of all cases (1,308 of 15,000, safety run) are declared fine although a real cause existed and an intervention would have helped; in the single-shipment run that is 11.7% of cases that had a cause, and 29% of the agent's "resolved" decisions (1,927 of 6,606). The autonomy gate does not change this.
- Inquiry relevance depends on the environment's answer tables. An earlier, looser definition ("the asked party has any cause-specific answer") gives 81.2% at TV ≥ 0.2 but is inflated because courier status has an entry for every cause; the TV ≥ 0.5 figure is the one to quote. Question value (not just relevance) is in `PITCH_METRICS.md` row 3.
- Safety "0 policy violations" is an invariant check, not a measured rate of mistakes.

## Not reportable

- **Correct tool-selection rate.** No independent ground truth defines the "correct" tool at a given step; any oracle would be a value-of-information calculation like the planner's own. Per-step tool calls were not retained in the evaluation output. Reportable alternatives: tool calls per case (legacy 8.7 vs 8.8 for the shipped agent, so no efficiency claim), or the ablation in `PITCH_METRICS.md` row 8 (asking before looking is worse).
- **Any real-world accuracy, optimal-action agreement or safety rate.** No public dataset has root-cause labels, incidents, or action-to-outcome pairs.
