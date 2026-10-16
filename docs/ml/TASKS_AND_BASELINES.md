# Dallal — Initial ML Tasks and Feasibility Baselines

*Task registry: [`backend/dallal/ml/tasks.py`](../../backend/dallal/ml/tasks.py) · Raw results: [`baselines.json`](baselines.json), [`incident_backtest.json`](incident_backtest.json) · Reproduce: `python -I -m dallal.ml.baselines` and `python -I -m dallal.ml.incident_backtest`*

These are **feasibility baselines**: untuned models, one chronological split, no model selection on the test set. Their job is to tell us which tasks the available data can support *before* anything is wired behind `predict_risk`. They are not production models and no number here is a claim about SPL.

## 1. Task definitions

| Task | Source | Predicts | Prediction time (`as_of`) | Status |
|---|---|---|---|---|
| `olist_late_at_handoff` | Olist | delivered calendar day > promised day (6.8%) | carrier hand-off | **baseline** |
| `amazon_package_failed_attempt` | Amazon LMRRC | ≥1 non-delivered visit on the route (0.75%) | planned route departure | **baseline** |
| `lade_slow_delivery_task` | LaDe-D (Shanghai) | duration > train-period P90 (engineered) | courier accept | **baseline** |
| `incident_detection` | LaDe noise + injected surges | surge in a scope's failure rate | end of window | **baseline** |
| `lade_pickup_late_vs_window` | LaDe-P | pickup after window end (0.2–0.5%) | courier accept | defined (rare event; needs a precision target) |
| `route_deviation_stop_displaced` | Route-deviation | stop visited out of planned position (54%) | route plan time | defined (canonical stop table lacks planned-distance features) |
| `cause_classification` | — | root cause of a disruption | decision time | **blocked: no public root-cause labels** |
| `recovery_uplift` | — | best action per shipment | decision time | **blocked: no public action→outcome data** |

## 2. Protocol (applies to every baseline)

* **Chronological** 65 / 15 / 20 split on the prediction instant; an **embargo** (30 days Olist, 1 day Amazon) separates blocks so labels that resolve after the cut cannot leak backwards.
* **Point-in-time history features** (`past_stat`): a row sees only outcomes that had *already resolved* (`available_at < as_of`). The shrinkage prior is estimated from the earliest 60% of the timeline only.
* **Label thresholds from train only** (LaDe P90).
* **Banned fields per task** plus a **behavioural leak guard**: any single feature with AUC ≥ 0.98 aborts the run (see §4 — it was needed).
* Only `observed`/`engineered` rows may appear in valid/test; synthetic rows are rejected by the splitter.
* Edge months with <500 labelled orders are dropped (Olist right-censoring).
* Metrics for rare events: PR-AUC (reported as lift over prevalence), lift/recall at top 10%, Brier vs the prevalence baseline, ECE. Not accuracy.

## 3. Results (test split)

| Task | Model | Test prevalence | ROC-AUC | PR-AUC (× prevalence) | Lift@top10% | Recall@top10% | Brier (prevalence ref.) | ECE |
|---|---|---|---|---|---|---|---|---|
| Olist late at hand-off | logistic, plan features | 3.6% | 0.836 | 0.302 (8.4×) | 5.0 | 50% | 0.0312 (0.0349) | 0.035 |
| | **GBM, plan features** | 3.6% | **0.867** | **0.489 (13.5×)** | **6.0** | **60%** | 0.0256 (0.0349) | 0.034 |
| | GBM, + seller/state/zip history | 3.6% | 0.739 | 0.298 (8.2×) | 4.0 | 40% | 0.0689 (0.0349) | 0.146 |
| | GBM, + history rates only | 3.6% | 0.836 | 0.371 (10.3×) | 5.4 | 54% | 0.0485 (0.0349) | 0.110 |
| Amazon failed attempt | logistic, plan features | 0.61% | 0.696 | 0.016 (2.7×) | 3.2 | 32% | 0.00611 (0.00608) | 0.0016 |
| | **GBM, plan features** | 0.61% | **0.769** | **0.027 (4.5×)** | **4.0** | **40%** | 0.00603 (0.00608) | 0.0009 |
| | GBM, + zone/station history | 0.61% | 0.758 | 0.025 (4.2×) | 4.0 | 40% | 0.00619 (0.00608) | 0.0037 |
| LaDe slow task (Shanghai, 400k sample) | logistic, context | 9.0% | 0.780 | 0.352 (3.9×) | 4.1 | 41% | 0.0705 (0.0818) | 0.023 |
| | GBM, context | 9.0% | 0.793 | 0.403 (4.5×) | 4.3 | 43% | 0.0674 (0.0818) | 0.017 |
| | **GBM, + AOI/courier/region history** | 9.0% | **0.863** | **0.517 (5.8×)** | **5.4** | **54%** | 0.0593 (0.0818) | 0.006 |

### What the numbers support — and what they don't

* **Olist:** with plan features known at hand-off, lateness is meaningfully rankable (top 10% captures 60% of late orders). History features *hurt* on the validation split too (valid AUC 0.788 → 0.751 rates-only → 0.704 with counts) because lateness drifts month to month (1.5%→20%) and count features act as a calendar clock. The variant was chosen on **validation**, not test. Test prevalence (3.6%) is lower than train (6.0%): probabilities drift, so calibrated deployment needs recalibration on recent data.
* **Amazon:** a real but weak ranking signal (AUC 0.77, ~4× lift). Brier ≈ prevalence reference, so the model **ranks** parcels but its probabilities add little over the base rate: use it as a relative risk ordering, never as "a 12% chance of failure". The label is a *visit* status with no reason; this cannot become a diagnosis model.
* **LaDe:** slow tasks are predictable from workload and location history (AUC 0.86). This is a *proxy* for stalled/slow shipments, not for failed delivery (LaDe has none).
* None of these uses the agent's observation models; the agent's `predict_risk` is still the transparent heuristic until a model is registered behind the `RiskModel` interface.

## 4. A leak found and closed (keep this in mind when reading any future number)

The first Olist run reported **AUC 1.000**. Cause: the label column was named `value`, the shipment table also has `value` (order price), and a merge silently made the *label itself* a feature. The name-based guard could not see it. Fix: labels are renamed `_label` at load, and `assert_no_label_proxy` now aborts any run in which a single feature alone has AUC ≥ 0.98. Both have tests (`test_label_proxy_guard_catches_a_renamed_label`).

## 5. Incident detection on real noise

No public dataset labels incidents. So: **real noise** (hourly counts of slow completions per region, 50 Shanghai regions, 1,921 evaluation hours) + **injected synthetic surges** (two consecutive hours, sized as multiples of the local baseline). Alarms on the untouched real series are counted as false alarms — an upper bound, since some may be genuine unlabeled events (promotions, weather).

| Detector | False alarms / scope-week | Detection of 1× / 2× / 4× / 8× / 16× surges |
|---|---|---|
| **Naive** (count ≥ 3, z ≥ 3; the agent's current defaults) | **2.00** | 66% / 74% / 78% / 94% / 99% |
| Quasi-Poisson, z\* = 4 (φ = 1.97 fitted on a calibration window) | 0.72 | 40% / 43% / 53% / 84% / 100% |
| z\* = 6 | 0.18 | 11% / 14% / 22% / 45% / 97% |
| z\* = 8 (calibrated to ≤0.1 FA on calibration window) | 0.058 | 1% / 2% / 7% / 24% / 87% |
| z\* = 10 | 0.019 | 1% / 0% / 3% / 14% / 68% |

**Conclusions.** (1) The agent's default thresholds are far too noisy on real data (2 false alarms per scope-week) — they are demo defaults, not tuned values. (2) Counts alone cannot separate small surges from ordinary variation: at a usable false-alarm rate only surges of roughly 8–16× the local baseline are reliably found. (3) This is the quantitative argument for the agent's design — treat the count detector as one signal and **fuse it with independent evidence** (corridor speed/stationary vehicles, facility scan gaps) in the Bayesian belief rather than alarm on counts. (4) Next step: replace the fixed thresholds in `check_incident_context` with a per-scope calibrated quasi-Poisson detector and a persistence rule.

## 6. What would change these results

* SPL event data with real exception codes and resolutions (the single biggest gap).
* A scan-event history per parcel (Olist/Amazon/LaDe have milestones, not scans).
* A short randomised pilot on reversible actions to make recovery uplift identifiable (see `dallal/agent/ledger.py`).
