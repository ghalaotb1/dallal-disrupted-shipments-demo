# Dallal experiments (earlier report)

> **Superseded for decision experiments.** The independent, paired, regime-and-sensitivity evaluation is in [`../EVALUATION_REPORT.md`](../EVALUATION_REPORT.md) with results in `results/` and charts in `charts/`; pitch numbers in [`PITCH_METRICS.md`](PITCH_METRICS.md). The B1/B2 sections below come from the earlier table-perturbation simulator, whose truth is a noisy copy of the agent's own tables (circular); keep them as history, not as evidence.

Two kinds of evidence, never mixed:

* **Real-data model metrics** (Part A): models fitted on real public delivery datasets, evaluated on later held-out time windows. They describe those datasets, **not SPL**.
* **Synthetic decision experiments** (Part B): agents run on a generative simulator with *misspecified* likelihoods (the world differs from what the agent believes). Utilities are SAR-equivalents from `utility.yaml` - **assumptions**. Results are *relative* comparisons under stated assumptions, not forecasts of money saved.

Regenerate everything: see the commands at the end of this file.

## Part A - real data: trained, calibrated risk models

| model | source | target | train / valid / test rows | test ROC-AUC (95% CI) | test PR-AUC (base rate) | lift@10% | Brier vs base-rate | ECE | chosen on validation |
|---|---|---|---|---|---|---|---|---|---|
| `olist_late_at_handoff_v1` | Olist Brazilian e-commerce (public) | delivered after the promised calendar day (engineered from observed timestamps) | 54,804 / 7,610 / 19,156 | 0.838 (0.82-0.85) | 0.303 (3.6%) | 5.1x | 0.0335 vs 0.0346 | 0.0466 | logreg / plan |
| `amazon_failed_attempt_v1` | Amazon Last Mile Routing Research Challenge (public) | any non-delivered visit for this package on its route | 859,260 / 140,151 / 355,664 | 0.771 (0.75-0.79) | 0.028 (0.6%) | 4.1x | 0.0060 vs 0.0061 | 0.0020 | hist_gbm / plan |
| `lade_slow_task_v1` | LaDe last-mile delivery (Cainiao), Shanghai | accept-to-deliver duration above the training-period P90 (engineered) | 259,997 / 60,001 / 80,002 | 0.864 (0.86-0.87) | 0.519 (9.0%) | 5.3x | 0.0592 vs 0.0818 | 0.0087 | hist_gbm / context+history_means |

Protocol: chronological train/valid/test with embargo; estimator, feature set and calibrator chosen on validation only; test touched once. Limits: the Olist late rate drifted between validation and test, so its calibration does not transfer (ranking is what to trust); the Amazon model ranks only moderately (0.6% base rate). Full cards: `docs/ml/models.json`.

### Sequence model vs tabular (LaDe slow-task risk)

| contender | valid PR-AUC | test PR-AUC | test ROC-AUC |
|---|---|---|---|
| `tabular_hgb` | 0.567 | 0.517 | 0.863 |
| `tabular_hgb_lags` | 0.582 | 0.547 | 0.876 |
| `gru_sequence` | 0.575 | 0.537 | 0.867 |

**Decision:** Tabular retained: the sequence model did not clear the pre-registered margin on both windows.

## Part B - synthetic: decisions

### B1. Single shipment: do value-based questions help? (400 paired episodes)

| agent | mean regret vs oracle | unsafe-auto rate | questions/case | escalation | mean minutes used | comm. cost |
|---|---|---|---|---|---|---|
| `v1_legacy` | 40.1 | 0.5% | 0.00 | 41% | 1.8 | 0.00 |
| `v2_no_inquiry` | 33.4 | 2.2% | 0.00 | 37% | 1.9 | 0.00 |
| `v2_infogain` | 30.7 | 1.8% | 1.44 | 30% | 12.1 | 2.46 |
| `v2_value` | 27.9 | 1.5% | 0.45 | 34% | 4.9 | 0.67 |

Paired regret difference (negative = better):

* `v1_legacy_minus_v2_no_inquiry`: +6.7 (95% CI +0.6 to +12.6)
* `v2_infogain_minus_v2_no_inquiry`: -2.7 (95% CI -9.0 to +3.2)
* `v2_value_minus_v2_no_inquiry`: -5.6 (95% CI -9.7 to -1.6)
* `v2_value_minus_v2_infogain`: -2.9 (95% CI -9.0 to +3.5)

Unsafe-auto = the agent auto-executed an action whose TRUE success probability was below 0.35. Counts are small (a handful of episodes); the cases are cheap actions aimed at a neighbouring cause (address vs recipient). Do not over-read the rate.

### B2. Systemic incident: one piece of evidence, many shipments (300 paired incidents per regime)

Strategies: independent naive / independent strong / desk-greedy (a strong human-desk heuristic) / independent with per-parcel questions / coordinated (joint MILP) without question / coordinated with ONE value-gated question / always-ask ablation / oracle.

**tight_scarce**

| strategy | mean regret | questions sent | on-time parcels | deferred parcels | asked |
|---|---|---|---|---|---|
| `independent_naive` | 919 | 0.00 | 3.45 | 6.44 | 0.0 |
| `independent_strong` | 403 | 0.00 | 6.74 | 0.72 | 0.0 |
| `desk_greedy` | 299 | 0.00 | 6.65 | 1.49 | 0.0 |
| `independent_inquiry` | 396 | 5.96 | 6.74 | 0.73 | 0.0 |
| `coordinated_no_inquiry` | 223 | 0.00 | 6.97 | 1.35 | 0.0 |
| `coordinated_inquiry` | 131 | 0.91 | 6.97 | 1.99 | 0.91 |
| `coordinated_always_ask` | 132 | 1.00 | 6.96 | 1.99 | 1.0 |
| `oracle` | 0 | 0.00 | 7.33 | 1.89 | 0.0 |

Paired gains (SAR-eq per incident, 95% bootstrap CI; win/loss = share of incidents):

* independent_strong minus independent_naive: +516 (+423 to +599), wins 74%, losses 26%
* coordinated_no_inquiry minus independent_strong: +180 (+144 to +223), wins 68%, losses 30%
* coordinated_no_inquiry minus desk_greedy: +76 (+57 to +98), wins 67%, losses 18%
* coordinated_inquiry minus desk_greedy: +168 (+129 to +209), wins 83%, losses 16%
* coordinated_inquiry minus independent_inquiry: +265 (+210 to +318), wins 77%, losses 23%
* coordinated_inquiry minus coordinated_no_inquiry: +92 (+53 to +127), wins 61%, losses 30%
* coordinated_inquiry minus coordinated_always_ask: +1 (-3 to +5), wins 5%, losses 3%

**tight_ample**

| strategy | mean regret | questions sent | on-time parcels | deferred parcels | asked |
|---|---|---|---|---|---|
| `independent_naive` | 970 | 0.00 | 4.62 | 5.25 | 0.0 |
| `independent_strong` | 472 | 0.00 | 7.62 | 0.25 | 0.0 |
| `desk_greedy` | 149 | 0.00 | 8.62 | 0.38 | 0.0 |
| `independent_inquiry` | 474 | 4.93 | 7.57 | 0.25 | 0.0 |
| `coordinated_no_inquiry` | 94 | 0.00 | 8.80 | 0.36 | 0.0 |
| `coordinated_inquiry` | 86 | 0.57 | 8.70 | 0.38 | 0.57 |
| `coordinated_always_ask` | 102 | 1.00 | 8.60 | 0.38 | 1.0 |
| `oracle` | 0 | 0.00 | 8.86 | 0.32 | 0.0 |

Paired gains (SAR-eq per incident, 95% bootstrap CI; win/loss = share of incidents):

* independent_strong minus independent_naive: +498 (+422 to +570), wins 80%, losses 20%
* coordinated_no_inquiry minus independent_strong: +378 (+318 to +445), wins 75%, losses 24%
* coordinated_no_inquiry minus desk_greedy: +55 (+48 to +63), wins 92%, losses 4%
* coordinated_inquiry minus desk_greedy: +63 (+36 to +89), wins 88%, losses 10%
* coordinated_inquiry minus independent_inquiry: +388 (+325 to +458), wins 83%, losses 17%
* coordinated_inquiry minus coordinated_no_inquiry: +8 (-21 to +33), wins 37%, losses 20%
* coordinated_inquiry minus coordinated_always_ask: +16 (+3 to +31), wins 25%, losses 18%

**loose**

| strategy | mean regret | questions sent | on-time parcels | deferred parcels | asked |
|---|---|---|---|---|---|
| `independent_naive` | 49 | 0.00 | 10.44 | 0.00 | 0.0 |
| `independent_strong` | 28 | 0.00 | 10.53 | 0.00 | 0.0 |
| `desk_greedy` | 74 | 0.00 | 10.38 | 0.00 | 0.0 |
| `independent_inquiry` | 20 | 1.42 | 10.53 | 0.00 | 0.0 |
| `coordinated_no_inquiry` | 35 | 0.00 | 10.49 | 0.00 | 0.0 |
| `coordinated_inquiry` | 15 | 0.77 | 10.53 | 0.00 | 0.77 |
| `coordinated_always_ask` | 15 | 1.00 | 10.53 | 0.00 | 1.0 |
| `oracle` | 0 | 0.00 | 10.56 | 0.00 | 0.0 |

Paired gains (SAR-eq per incident, 95% bootstrap CI; win/loss = share of incidents):

* independent_strong minus independent_naive: +22 (+9 to +35), wins 9%, losses 31%
* coordinated_no_inquiry minus independent_strong: -7 (-17 to +2), wins 27%, losses 9%
* coordinated_no_inquiry minus desk_greedy: +39 (+23 to +59), wins 19%, losses 19%
* coordinated_inquiry minus desk_greedy: +60 (+40 to +80), wins 39%, losses 39%
* coordinated_inquiry minus independent_inquiry: +5 (-4 to +13), wins 58%, losses 13%
* coordinated_inquiry minus coordinated_no_inquiry: +20 (+7 to +33), wins 39%, losses 38%
* coordinated_inquiry minus coordinated_always_ask: -0 (-0 to +0), wins 22%, losses 1%

**tight_scarce_prior_wrong**

| strategy | mean regret | questions sent | on-time parcels | deferred parcels | asked |
|---|---|---|---|---|---|
| `independent_naive` | 728 | 0.00 | 3.42 | 6.44 | 0.0 |
| `independent_strong` | 660 | 0.00 | 5.47 | 0.72 | 0.0 |
| `desk_greedy` | 383 | 0.00 | 5.72 | 1.49 | 0.0 |
| `independent_inquiry` | 692 | 5.96 | 5.35 | 0.79 | 0.0 |
| `coordinated_no_inquiry` | 314 | 0.00 | 6.04 | 1.35 | 0.0 |
| `coordinated_inquiry` | 180 | 0.91 | 5.96 | 2.84 | 0.91 |
| `coordinated_always_ask` | 201 | 1.00 | 5.89 | 2.85 | 1.0 |
| `oracle` | 0 | 0.00 | 6.38 | 3.02 | 0.0 |

Paired gains (SAR-eq per incident, 95% bootstrap CI; win/loss = share of incidents):

* independent_strong minus independent_naive: +68 (-27 to +165), wins 48%, losses 52%
* coordinated_no_inquiry minus independent_strong: +346 (+294 to +400), wins 80%, losses 18%
* coordinated_no_inquiry minus desk_greedy: +68 (+43 to +96), wins 62%, losses 23%
* coordinated_inquiry minus desk_greedy: +203 (+154 to +250), wins 80%, losses 19%
* coordinated_inquiry minus independent_inquiry: +512 (+440 to +588), wins 82%, losses 18%
* coordinated_inquiry minus coordinated_no_inquiry: +134 (+86 to +181), wins 61%, losses 30%
* coordinated_inquiry minus coordinated_always_ask: +21 (+4 to +47), wins 7%, losses 2%

Assumptions (all printed in the JSON): prior P(long blockage) 0.30; dispatcher reply probability and latency from `inquiries.yaml`; answer likelihoods `LIK`; resource counts/capacities per regime; pickup acceptance 0.75; deferral cost share 0.4.

### B3. LLM planner vs the decision-theoretic planner (24 paired episodes, simulator)

| contender | mean regret | paired regret diff vs EVOI | questions/case | valid tool-call rate | agrees with EVOI | median / p95 latency per step (s) | failures |
|---|---|---|---|---|---|---|---|
| `evoi` | 30.9 | +0.0 | 0.62 |  |  |  /  |  |
| `qwen3.5:4b / pure` | 39.4 | +8.4 | 2.00 | 1.0 | 0.254 | 9.77 / 12.0 | {} |
| `qwen3.5:4b / hybrid` | 31.5 | +0.6 | 0.75 | 1.0 | 0.987 | 12.2 / 14.08 | {} |
| `qwen3.5:9b / hybrid` | 30.9 | +0.0 | 0.62 | 0.993 | 0.987 | 21.93 / 25.39 | {'llm_error': 1} |

Reading: the model may only choose the next investigation step (closing pipeline and policy gates are deterministic). With the advisor table (`hybrid`) both Qwen3.5 sizes follow the decision-theoretic planner 99% of the time and match its decision quality - the LLM adds no measurable decision value here, only 12-22 s per planning step on a shared 16 GB Apple-silicon laptop (indicative, not a clean latency benchmark). Without the advisor (`pure`) the 4B model agrees with EVOI on 25% of steps, always spends both allowed questions and is worse (paired regret +8.4). Qwen3.5-9B `pure` was not run (time). One 9B call hit the client timeout and fell back to the EVOI step. Valid tool-call rate is 99-100%: tool calling works; judgement without the numbers is the weak part. 24 episodes: the CI on the paired difference is wide; treat the ordering, not the decimals, as the result.

### B4. Free-text reply interpretation (96 hand-written Arabic/English replies, 78 answerable)

| interpreter | coverage of answerable | false-accept rate | abstains correctly on unanswerable | median latency (s) |
|---|---|---|---|---|
| rules only | 38% | 6.2% (2) | 94% | - |
| qwen3.5:4b llm only | 96% | 3.8% (3) | 89% | 6.21 |
| qwen3.5:4b rules then llm | 96% | 5.1% (4) | 89% | 6.21 |
| qwen3.5:9b llm only | 95% | 2.6% (2) | 94% | 11.33 |
| qwen3.5:9b rules then llm | 97% | 3.8% (3) | 89% | 11.33 |

Set authored by the team (not real traffic). A false accept would become evidence, so it is the metric that matters. Findings: the LLM reads 95-97% of answerable replies versus 38% for the keyword rules (the rules have no lexicon for courier / dispatcher answers), but it still accepts contradictory or vague replies ("yes and no", "حاضر") with confidence 0.95-1.0, so its stated confidence is not calibrated. Qwen3.5 under Ollama does not enforce `format` JSON schemas (first attempt: 0% parsed); enum-constrained **tool calling** works. Therefore the LLM output is a *suggestion shown to a human reviewer*, never evidence by itself.

## Reproduce

```bash
cd backend
python -I -m dallal.ml.train                       # real-data models (needs built canonical tables)
python -I -m dallal.ml.sequence                    # needs `pip install torch`
python -I -m dallal.sim.single_exp 400            # B1
python -I -m dallal.sim.network_exp 300           # B2
python -I -m dallal.eval.headline                 # end-to-end trace
python -I -m dallal.eval.llm_planner_bench 24 qwen3.5:4b qwen3.5:9b   # B3 (local Ollama)
python -I -m dallal.eval.reply_bench qwen3.5:4b qwen3.5:9b           # B4
python -I -m dallal.eval.report
```
