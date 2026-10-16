# Dallal — Augmentation Strategy

*Generator: [`backend/dallal/data/augment/scenarios.py`](../../backend/dallal/data/augment/scenarios.py) · Tests: `test_every_scenario_is_valid_tagged_synthetic_and_deterministic`*

## Rule zero

Synthetic data exists to **exercise and regression-test** the agent in situations real data cannot show. It is **never** used to train or evaluate a risk model, never inflates a headline metric, and is excluded from every held-out split *by construction* (`splits.time_split` raises if a non-observed row would land in validation/test; `validate_frame` requires a `scenario_id` on every synthetic row and forbids one on observed rows).

## Order of work

1. Understand the real data first (EDA → [`DATASET_DECISION_REPORT.md`](DATASET_DECISION_REPORT.md) §3).
2. List what the real data **cannot** provide.
3. Generate only scenarios that fill those gaps.

| Real-data gap (measured) | Scenarios generated |
|---|---|
| No public data states failure **reasons** (Amazon: attempts without reason; LaDe: no failures) | `recipient_unavailable`, `repeated_failures`, `address_risk` (wrong/incomplete address) |
| No public data labels operational **root causes** | `route_blockage`, `branch_backlog`, `stalled_no_scan`, `pickup_unavailable` |
| No public data contains **contradictory evidence** | `custody_conflict` (delivered → out-for-delivery), `courier_no_show` (code says "unavailable", GPS says the courier was 2 km away) |
| No public data labels **systemic incidents** | `route_blockage`, `branch_backlog` (6 failing parcels + exposed ones sharing a corridor/branch) |
| No unexplained anomalies | `unknown_anomaly` (unmapped exception code, otherwise clean) |
| Negative control | `healthy` |

## What each scenario fixes and varies

* **Fixed (the structure that defines the situation):** which signals are present/absent, their direction, and the evaluation-only `expected` block (decision, cause, required/forbidden tools).
* **Varied by seed:** geometry (positions within a neighbourhood), counts of peers/exposed parcels, magnitudes (corridor speed, backlog), timestamps within windows.
* **Consequence:** the 220-run sweep (11 scenarios × 20 seeds) tests robustness to geometry and magnitude, **not** to novel structure. Its 100% pass rate is "the logic behaves as designed", not "the agent is 100% accurate". Metamorphic checks and safety invariants are the stronger evidence.

## Calibration status (honest)

| Parameter | Status |
|---|---|
| Event timing, jitter | arbitrary; not fitted to real data |
| Background exception rate on a corridor (0.4 ± 0.6 / 30 min) | **assumption**; the real-noise backtest (`docs/ml/TASKS_AND_BASELINES.md` §5) shows real overdispersion is larger and the default detector too noisy |
| Real-data calibration performed | incident **detector** thresholds against real LaDe noise; nothing else |
| Real-data calibration planned | inter-event gaps from LaDe/Olist; failure-rate level from Amazon (0.75%) for background parcels |

## Third-party simulation

The OCEL 2.0 Order Management log (311 failed-delivery events across 214 of 1,128 packages, up to 7 failures on one package) is a Petri-net simulation. It is mapped into the canonical model as `origin=synthetic` (`scenario_id=ocel2-order-management-v2`) to prove the event/attempt model round-trips a standard object-centric log and to show realistic *shapes* of repeated-failure loops. Its rates are the simulator's.

## Bridge to real learning

Because synthetic rows are tagged and separate, replacing them with SPL data is a data swap, not a schema change: the same `exception`, `attempt` (with `failure_reason`), `recipient_context`, `node_state` and `incident` tables are filled with `origin=observed`.
