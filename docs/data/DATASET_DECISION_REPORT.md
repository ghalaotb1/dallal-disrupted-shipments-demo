# Dallal — Dataset Decision Report

*Audit date: 2026-10-15 · Machine-readable source of truth: [`backend/registry/datasets.yaml`](../../backend/registry/datasets.yaml) · Measured numbers: [`eda_summary.json`](eda_summary.json) (regenerate with `python -I -m dallal.data.eda`)*

## 1. Bottom line

No public dataset contains what Dallal's headline product needs end to end (shipment events **and** failed attempts **with reasons** **and** recovery actions with outcomes). The audit therefore produced a **portfolio**, each source mapped to the Dallal task it can legitimately support, plus a clearly tagged synthetic layer for the rare operational scenarios no real data covers.

| Dallal capability | Best real evidence found | Honest status |
|---|---|---|
| Courier-task timing, stalls, slow tasks | **LaDe** (4.5M delivery tasks, 5 cities, 184 days) | Strong. Engineered label (duration); no failure labels. |
| Failed delivery **attempts** (observed) | **Amazon LMRRC** (1.46M packages, 11,014 attempted + 32 rejected visits; 1,422 packages visited at ≥2 stops) | Real, but no reason, timestamp, or recipient data; 0.75% positive. |
| Repeated attempts | Amazon (1,304 `failed→delivered`, 105 `failed→failed`, 8 `failed→failed→delivered`) | Real but small. |
| Late-vs-promise risk | **Olist** (96,443 labelled orders, 6.8% late) | Real, coarse milestones only. |
| Time-window violation | LaDe-P (0.20% / 0.47% late), route-deviation (10.6% late) | Real; pickups are rare events. |
| Route behaviour / deviation | **Route-deviation** (22,269 routes, 400 drivers, 54% stops displaced) | Real, CC BY. |
| Systemic / cross-shipment incidents | **None labelled anywhere.** LaDe/Amazon give the *baseline noise*; incidents must be injected (synthetic) | Benchmark by injection only. |
| Failure reasons / address problems | **None.** | Synthetic scenarios only, never evaluated as real. |
| Recovery action → outcome | **None public** (see §5) | Policy ranking + logging contract; no causal claim. |
| Saudi network grounding | **SPL open data** (529 real branches, 491 geocoded, 13 regions) | Reference only; no shipment data. |

## 2. Decisions

### SELECT — real observed data, used for training/evaluation

| Dataset | License / redistribution | What it supports | Key measured facts | Main caveats |
|---|---|---|---|---|
| **LaDe-D / LaDe-P** (Cainiao, KDD'24) | HF metadata Apache-2.0; README: research use. Not redistributed. | Task timing, stall/slow-task labels, courier workload, window violation (P), incident *baseline* | Delivery: 4.5M tasks; median accept→done 72–208 min by city, P99 up to 3,342 min. Pickup late-vs-window: Jilin 0.197% (514), Yantai 0.472% (5,398). `ds` = MMDD 501–1031 | **No failure/attempt labels** (completed tasks only). No year in timestamps (YEARLESS, ordering valid). Chinese cities. Zero-minute durations excluded. |
| **Amazon LMRRC 2021** (training) | CC BY-NC 4.0; non-commercial; not redistributed | Stop/package outcome (`DELIVERED/DELIVERY_ATTEMPTED/REJECTED`), zones, windows, planned service time, actual sequence | 6,112 routes, 898,415 stops, 1,457,175 visits; failed-visit rate 0.751% per package, drifting 0.99%→0.56% across 6 weeks; windows on 7.8% of packages | No reason, attempt timestamp, recipient. `route_score` is post-hoc (leakage-banned). **The 3,072 evaluation routes were audited and rejected: `scan_status` is withheld.** Commercial deployment would need SPL's own data. |
| **Route-deviation** (Molde; NO/DK; Mendeley, 2024; data paper 2026) | CC BY 4.0 | Planned-vs-actual sequence, arrival vs window | 22,269 route-days, 249,231 stops; late-vs-window 10.6%; displaced stop 54.4%; 75% of routes have ≥1 displaced stop | 3,049 rows carry sentinel-scale times (~1.28e7 min) → nulled & counted. Offsets only (no wall clock). |
| **Olist** (raw 9 tables via HF mirror of Kaggle) | CC BY-NC-SA 4.0; derived data stays local | Order-level lateness vs promise, hand-off delay | 99,441 orders; **6.77% late** by calendar-day promise (8.11% under strict timestamp compare — same figure as the HF derivative card); 1.4% hand-off timestamps precede payment approval | Coarse milestones. **Right-censoring**: edge months (2016-12: 50%, 2018-09: 100% late) are tiny censored samples → excluded by the splitter. Brazilian e-commerce. |
| **SPL Open Data** (areas, cities, offices, services) | Free use with attribution to "Saudi Post \| SPL Open Data Platform" | Real Saudi branch network for hub/branch grounding | 529 offices, 491 with valid Saudi coordinates, 13 regions | **Reference only — no shipments, tracking or performance data.** |

### SECONDARY / BENCHMARK ONLY

| Dataset | Why not primary |
|---|---|
| **OCEL 2.0 Order Management** (RWTH, CC BY 4.0) | **Simulated** by Petri-net (CPN Tools). Has `failed delivery` loops (311 failures over 214 of 1,128 packages, up to 7 on one package) — useful to prove our event/attempt model round-trips a standard object-centric log and to shape synthetic attempt sequences. Tagged `SYNTHETIC`; never evaluated as real. |
| **Cargo 2000** (UCI, CC BY 4.0) | Air freight; 3,943 process instances; planned-vs-effective durations per milestone. 29.6% final delivery slower than plan. Independent benchmark of *prefix-based delay prediction*; domain ≠ last mile. |
| **DataCo Smart Supply Chain** (Mendeley, CC BY 4.0) | `Late_delivery_risk` **is exactly** `Delivery Status == "Late delivery"` (verified on all 180,519 rows; 97.6% equal to real>scheduled days) and the 54.8% late rate is implausible for real operations; the page does not say whether data are real. Trivial/leaky label → benchmark-only, never a headline number. |
| **SPL National Address API** | Requires an API key (none provisioned), starter tier 100 calls/week, bulk extraction prohibited. Implemented only as a swappable `AddressProvider` interface at runtime. |

### REJECT

| Candidate | Reason | Evidence level |
|---|---|---|
| HF `samuelalex37/olist-delivery-risk-data` | Opaque pre-engineered derivative with a frozen split; we rebuild from raw tables to control timestamps and leakage. Its card did confirm the 8.11% rate and the banned-column list. | schema |
| Kaggle *Delivery Logistics (India, multi-partner)* and similar | Card states delayed→"Failed" is assigned "with realistic probability" → generated labels. | card only (login needed) |
| Kaggle *Delivery Logistics* (ayeshaseherr) | 1970 placeholder timestamps, irregular ids, truncated row. | card only |
| Delhivery trip/segment copies | No license stated; Kaggle login; revisit if a licensed copy appears (hub-to-hub actual vs OSRM time would be relevant to line-haul delay). | card only |
| HF synthetic logistics sets (`ClarusC64/*`, `electricsheepafrica/africa-synth-*`, `34data/ai-generated-*`, …) | Self-described synthetic; no real provenance. | card only |
| HF `aqxlogistics/salla-zid-fulfillment-logistics-benchmark` | Saudi-flavoured name, but the repo is **empty** (3.38 kB, no data). | data (inspected) |
| OCEL Container Logistics | Simulated port process; order-management log is the closer analogue. | card only |
| Amazon LMRRC *evaluation* routes | Outcomes withheld (`scan_status` absent) → no labels. | data (inspected) |
| CRITEO / Meituan / Alibaba uplift sets | Genuine RCT data but for marketing; would validate uplift *code* only and must never be presented as delivery evidence. | card only |

> "card only" means we did **not** download the data; the rejection rests on the publisher's own description. We say so rather than imply inspection.

## 3. Things the audit found that change the design

1. **LaDe has no failures.** Our failure-risk models cannot be trained on LaDe; it supplies timing structure, stall/slow-task signals and incident *baselines*.
2. **Amazon is the only source of real attempt outcomes** and it is small (0.75%), reasonless, and untimed. It trains an *attempt-failure-risk* baseline, not a diagnosis model.
3. **Repeated attempts exist in Amazon** (1,422 packages at ≥2 stops) — modelled as one shipment with several `attempt` rows, not dropped as duplicates.
4. **Class prevalence differs by an order of magnitude** across tasks (0.2% pickup-late, 0.75% attempt-failed, 6.8% Olist-late, 10.6% route-late) → PR-AUC / lift@k, not accuracy.
5. **Non-stationarity is real**: Amazon failure rate fell 43% over six weeks; Olist late rate spans 1.5%→20% by month → random splits would overstate performance.
6. **Olist is right-censored at the edges** (tiny, late-biased edge months) → excluded by rule.
7. **Failure *reasons*, recipient behaviour, address quality and systemic incidents have no public ground truth.** Dallal's diagnosis and incident layers are therefore evaluated functionally on tagged synthetic scenarios and, for incidents, by injecting disruptions into real LaDe/Amazon baselines.

## 4. What was downloaded and prepared

25 files / ~1.6 GB under `backend/.data/raw/` (git-ignored), every sha256 recorded in [`datasets.lock.json`](../../backend/registry/datasets.lock.json); pinned versions where the host supports it (HF commit SHAs; Mendeley/Zenodo published hashes). Reproduce with:

```bash
cd backend && uv venv && uv pip install -e ".[dev]"
python -I -m dallal.data.cli fetch selected --all
python -I -m dallal.data.cli build olist amazon_lmrrc lade route_deviation spl_open_data ocel_order_management labels
python -I -m dallal.data.eda
```

Canonical tables (parquet, git-ignored) were built for every selected source and **validated against the schema on write** (key uniqueness, enum domains, provenance, adapter `PROVIDES` contract, label leakage rule).

## 5. Recovery action → outcome data: search result

Searched Hugging Face, GitHub, Kaggle, Zenodo/Figshare/Dryad, process-mining repositories, and academic literature for interventions with logged outcomes in parcel delivery (rescheduling, redirection, re-contact, courier reassignment).

* **Found, not public:** an uplift study of appointment-based attended delivery on a Chinese logistics company's data (ScienceDirect, 2024; data not public); D3-TR courier task rescheduling (reports a 3.9% on-time improvement in deployment).
* **Found, public but wrong domain:** CRITEO-UPLIFT v2, Meituan-LIFT, Alibaba-LIFT (randomised marketing treatments).
* **Found, synthetic:** commercial "delay causes" generators.
* **Not found:** any public dataset pairing a last-mile recovery action with its outcome.

**Consequence:** we do **not** claim a learned or causal recovery policy. The first recovery layer is an evidence-weighted, rule-and-policy ranking that is explicitly labelled `causal_claim=false`, and the `action`/`decision`/`outcome` tables log the fields a future uplift model needs (assignment mechanism, logged propensity, frozen context snapshot, policy id). Real uplift learning requires either SPL's historical intervention logs or a small randomised pilot on low-risk actions.

## 6. Open items

* SPL operational data (events, exception codes, intervention logs) is the single most valuable missing input; all adapters are written so it drops into the same canonical tables.
* If a Kaggle credential is provisioned, re-audit the "card only" rejections that could plausibly be real (Delhivery, Amazon-India delivery table).
