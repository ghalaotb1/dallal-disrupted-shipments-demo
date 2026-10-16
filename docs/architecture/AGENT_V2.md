# Dallal agent v2 - critical review of v1 and the revised decision architecture

This document is the engineering record behind the v2 agent. Every quantitative claim links to a committed experiment report in [`docs/experiments`](../experiments/README.md). **All decision experiments are synthetic** (a simulator whose true world differs from the agent's beliefs) and all utilities are SAR-equivalents under stated, expert-assumption parameters (`backend/dallal/agent/v2/utility.yaml`). They support *relative* conclusions only. Real-data evidence is limited to the three trained risk models (`docs/ml/models.json`).

## 1. What v1 got right (kept)

* A **canonical data model with provenance** (observed / engineered / synthetic / demo) and **leakage guards** (`as_of` / `available_at`, label-proxy check). It caught a real bug early: an Olist label column silently merged into the features (single-feature AUC 1.000).
* **Typed tools with preconditions**, provenance on every result, an outcome **ledger**, and hard **safety invariants** (no automation above value / attempt / confidence bounds, no skipped policy gate, no repeated tool, escalation always carries a packet).
* A planner-independent runtime (the LLM never touches evidence or policy).

## 2. What v1 got wrong (and the evidence)

| Area | v1 behaviour | Why it is a weakness | v2 |
|---|---|---|---|
| Belief | One Bayesian table with expert-assumed likelihoods, treated as exact; correlated tools (all "scan" tools) multiplied as if independent | Over-confident posteriors: three weak scans looked like three independent confirmations | **Ensemble belief**: 24 perturbed likelihood tables (log-normal sigma 0.35), Bayesian model averaging over table uncertainty, evidence-**family tempering** (exponent 0.65 for tools of the same family) |
| Information acquisition | Entropy-reduction planner | Information is not value: it asks whenever uncertain, even when no answer could change the action, ignores delay, cost, response risk | **Net expected value of information** in utility units (section 3) |
| Decision rule | Posterior threshold on one cause (`diagnose_min_posterior`, `decisive_margin`) then a ranking | Thresholds throw away the shape of the posterior and the stakes. A cheap, reversible action that is best under every plausible cause was blocked because no cause crossed 0.6 | **Expected-utility ranking** under the full belief; `actionable` gating removed; reason `delegation_preferred` when escalating is best |
| Escalation | Free fallback | "Escalate" dominated everything else in value calculations, so the planner stopped after one tool | Escalation is **delegation**: costs supervisor time and hand-off delay, but the supervisor then *knows* the cause (success = 0.9 x best achievable) |
| Autonomy | Posterior and value bounds | Single-point confidence | **Bounded autonomy v2**: automatic only if the action is automatable, needs no approval, is reversible, <= SAR 1,500, <= 2 prior failures, no code/evidence conflict **and** its effectiveness is >= 0.62 at the **10th percentile** across belief particles |
| Humans | None in the loop; runs were atomic | A question to a person is the most valuable evidence in many disruptions (is the courier at the door?) | **Active evidence acquisition** with a durable pause/resume runtime and WhatsApp (sections 3-4) |
| Shared cause | Incident detection, then per-shipment handling | Ten shipments on one blocked corridor compete for the same spare couriers and vans, and each asks the same question | **Coordinated recovery** (section 5) |
| Risk model | Hand-written noisy-OR | Not a model; scores were not calibrated or evidence-backed | Three trained, calibrated models behind a feature contract (section 6); heuristic remains the labelled fallback |
| Evaluation | Authored scenarios and pass rates | Pass rate on cases written alongside the agent says nothing about decision quality | **Generative simulator with a misspecified truth**, oracle regret, paired seeds, bootstrap CIs |

## 3. Active evidence acquisition

For each candidate evidence source *e* (a database tool or a question to a person) the agent computes, by exact enumeration over outcomes and over table uncertainty:

```
net EVOI(e) = sum_o P(o) * max_a EU_o(a | extra delay of e)  -  max_a EU(a)  -  cost(e)
```

* **Decision impact**: gain exists only if some outcome changes the best action.
* **Urgency**: on-time value decays as `exp(-delay / horizon)`; a 40-minute answer is worth little when the promise is 30 minutes away (waiting is exempt: the van keeps moving while we ask).
* **Response risk**: *no response* is an outcome with its own probability, the timeout as its delay, and near-zero information. The agent pays the cost and learns little.
* **Communication cost, friction and fatigue** enter `cost(e)` (recipient messages are capped at 2 per 24 h; quiet hours 21:30-08:00; opt-out respected).
* **Set-level look-ahead** fixes one-step myopia (a tool that only matters together with another is undervalued by a single-step rule).
* **Ask only for what you cannot look up**: free, instant database evidence is exhausted before any person is asked, and a question is valued at the belief *after* the lookups.

Research basis: value of information and decision-focused sensing (Howard 1966), expected-value-of-sample-information in decision analysis, active sensing / Bayesian experimental design, and the finding in active-learning work that uncertainty alone is a poor acquisition criterion when actions are discrete. The implementation is a direct EVOI computation, not a learned acquisition policy.

**Result (B1, 400 paired episodes).** Value-based asking beats database-only (paired regret -5.6, 95% CI -9.7 to -1.6), uses 0.45 questions per case versus 1.44 for the information-gain asker, spends ~5 vs ~12 virtual minutes, and is not significantly different in regret from information gain (-2.9, CI -9.0 to +3.6): the practical win is *the same decision quality for a third of the questions and less delay*. v1 is worse than v2 database-only (+6.7, CI +0.6 to +12.6). Caveat: unsafe-auto cases (true success < 0.35) were 1.5% for v2-value vs 0.5% for v1 (6 vs 2 of 400); the cases are cheap actions aimed at a neighbouring cause (address vs recipient). The counts are too small to rank the two, but the direction is a reason to keep supervising automation.

## 4. WhatsApp in the loop

See [`docs/integration/WHATSAPP.md`](../integration/WHATSAPP.md). In short: justified inquiry -> template/interactive send through a guard -> durable checkpoint -> idempotent webhook -> closed-answer interpretation (or human review) -> belief update -> resume. Sandbox and Cloud API providers share one code path; a sandbox message is never reported as delivered to a phone.

## 5. Coordinated network recovery

For one shared-cause incident (`backend/dallal/recovery/network.py`):

* Options per shipment: **wait**, **reroute** the van, **spare** courier *j*, **pickup point** *p*, **defer** with notice.
* One MILP (`scipy.optimize.milp`, HiGHS): `x[i,o]` (shipment i takes option o), `z[v]` (van v reroutes), `y[j]` (spare j dispatched). Constraints: one option per shipment; van consistency (shipments that stay on a rerouted van reroute with it); spare and pickup capacity; shared fixed costs (dispatching a spare, rerouting a van) paid once. The objective is expected utility over the blockage duration `D` (short or long), using the same stakes and urgency curves as the single-shipment agent. Solves in milliseconds.
* **Cluster-level value of information with recourse**: asking the dispatcher *once* serves every shipment. Shipments whose best option is the same under both extremes are committed immediately; the rest wait for the answer, then the remaining plan is re-solved on the posterior for each possible answer (and for silence).
* Supervisor-only approval; execution is simulated and written to the outcome ledger.

**Result (B2, 300 paired incidents x 4 regimes).** Against a *strong human-desk heuristic* (parcels worked highest stake first, each taking its best option given what is already committed), joint optimisation gains +55 to +76 SAR-eq per incident in the capacity-tight regimes (CIs exclude zero) and one shared question adds a further +8 (not significant, ample capacity), +21 (loose), +92 (scarce) and +135 (wrong prior), never worse than always asking and clearly better when the prior is wrong. Independent per-parcel questions cost 5-6 messages per incident and do not help in the capacity-tight regimes (a 5-6x more expensive way to buy the same answer, after which the parcels still collide on capacity); in the loose regime they help modestly. In **loose** regimes, where waiting is fine, coordination alone does *not* beat a decent independent strategy (-7, CI -17 to +2); the benefit there comes from the question. Numbers in [`docs/experiments/README.md`](../experiments/README.md).

## 6. Real ML models, and what they are for

Three models, three targets, never merged (`dallal/ml/train.py`, cards in `docs/ml/models.json`):

| model | source | test ROC-AUC | note |
|---|---|---|---|
| `olist_late_at_handoff_v1` | Olist (Brazil) | 0.838 | validation preferred logistic regression; the late rate drifted between validation and test, so calibration does not transfer (ranking does) |
| `amazon_failed_attempt_v1` | Amazon LMRRC (US) | 0.771 | 0.6% base rate; PR-AUC 0.028 (4.6x base). A moderate ranker, not a detector |
| `lade_slow_task_v1` | LaDe Shanghai | 0.863 | resolved-history features adopted (valid PR-AUC +31% over context only) |

Protocol: chronological split with embargo, choice of estimator / feature set / calibrator on validation only, test touched once, richer feature sets adopted only if >= 5% better on validation. A **feature contract** refuses missing features (no imputation) and abstains outside the training range. These models are trained on other countries' data: the agent uses them as ranking evidence when a case supplies a complete in-range feature row, and the Model Lab shows live scoring and real held-out replays. **A pre-registered GRU sequence model did not beat the tabular model** (valid PR-AUC 0.575 vs 0.582 for tabular with lag features), so tabular stays. Cause classification and recovery uplift remain unlearned: no public labels exist.

## 7. LLM planner and interpreter (Qwen3.5 via local Ollama)

**Model choice.** Candidates were Qwen3.5 4B (3.3 GB) and 9B (6.6 GB): both advertise native tool calling, both fit a 16 GB laptop, and the family is multilingual (Arabic is a stated language; we measured it ourselves on a hand-written set). Larger variants (27B and up) do not fit the target hardware and were not tried. Bigger was not assumed better; it was measured.

**What the LLM is allowed to do** (`agent/v2/llm_planner.py`): choose the *next investigation step* from an eligible menu by calling a function. Beliefs, tool results, the closing pipeline (diagnosis -> expected-utility ranking -> policy gates) and permissions remain deterministic. Unknown / ineligible / repeated names, missing calls and backend errors fall back to the EVOI step and are counted. Tests use a scripted stand-in (no model needed).

**Measured (24 paired simulator episodes, [details](../experiments/README.md)):**

| planner | paired regret vs EVOI | agrees with EVOI | valid tool calls | latency / step |
|---|---|---|---|---|
| EVOI (no LLM) | 0 | - | - | ~ms |
| Qwen3.5-4B pure (no advisor numbers) | +8.4 (worse) | 25% | 100% | ~10 s |
| Qwen3.5-4B hybrid (sees EVOI table) | +0.6 | 99% | 100% | ~12 s |
| Qwen3.5-9B hybrid | 0.0 | 99% | 99% (1 timeout) | ~22 s |

Conclusion: tool calling is reliable at both sizes, but judgement without the decision-theoretic numbers is worse than the numbers, and with them the LLM merely follows. **The shipped planner stays EVOI**; the LLM planner is an optional, guarded component useful for explanation and for operators who want to override. No fine-tuning was attempted: there was no demonstrated need.

**Where the LLM does help: reading replies.** On 96 hand-written Arabic/English replies, the keyword rules cover 38% of answerable replies; Qwen3.5 covers 95-97% (false-accept 2.6-3.8% vs 6.2% for the rules, which have no lexicon for courier/dispatcher answers). But its self-reported confidence is not calibrated (a contradictory "yes and no" came back at 0.95), and Ollama does not enforce JSON-schema `format` for Qwen3.5 (enum-constrained **tool calls** do work). So the interpreter's output is a **suggestion shown to a human reviewer with one-click accept** (`dallal/llm/interpret.py`, enabled with `DALLAL_LLM_INTERPRET_MODEL`); it never becomes evidence by itself. Verified live: an Arabic free-text courier reply ("I'm standing at the door and the customer doesn't answer") produced the suggestion *At address, nobody answered*; the analyst accepted it; belief moved to recipient-unavailable 78% and a recommendation was produced.

## 8. Limits, stated plainly

* Utilities, response rates, answer likelihoods, spare/pickup resources and the cause prior are **assumptions**. Absolute SAR figures are not forecasts.
* Cause likelihoods remain expert tables; they should be re-estimated from SPL exception and resolution logs when available (the ensemble already carries the uncertainty).
* The simulator is mine: a misspecified truth is still my idea of misspecification.
* No real WhatsApp message has been sent; no SPL data has been used; the LLM has not been evaluated on real traffic.
