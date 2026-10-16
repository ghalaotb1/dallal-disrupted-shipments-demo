# Dallal agent — evaluation traces

> **All data in these traces is SYNTHETIC** (`origin=synthetic`, scenario ids shown). They demonstrate that the agent's behaviour depends on the
> evidence; they are **not** accuracy estimates. Probabilities come from expert-assumption observation models (`expert_assumption_v1`),
> not from a fitted model. Regenerate: `python -I evals/run_cases.py && python -I evals/render_traces.py`.

## A — Low-risk case → safe automated recovery

* scenario `address_risk-seed7` · trigger `risk_alert` · planner `evidence-driven-evoi-v1`
* **tool path:** `get_shipment → predict_risk → get_address_context → get_recipient_context → get_journey → analyze_disruption → rank_recovery_actions → retrieve_policy_constraints`
* **decision:** `auto_eligible` · action `verify_address` · leading cause `address_issue` (82%) · P(systemic) 3%
* **headline:** Eligible for automated action: Ask recipient to confirm the delivery pin
* **rationale:** address_issue at 82% (≥ 80%); action is reversible/low-impact and within value and attempt limits.

| # | tool | why it was chosen | outcome | leading hypotheses after |
|---|---|---|---|---|
| 0 | `get_shipment` | bootstrap: shipment facts are needed to form a prior | ok | none 34%, recipient_unavailable 15% |
| 1 | `predict_risk` | largest information gain per cost (0.24 bits, cost 0.5); 0% chance it changes the decision | driver_address | address_issue 42%, none 22% |
| 2 | `get_address_context` | largest information gain per cost (0.52 bits, cost 1.0); 46% chance it changes the decision | address_weak | address_issue 84%, none 5% |
| 3 | `get_recipient_context` | largest information gain per cost (0.10 bits, cost 1.0); 19% chance it changes the decision | no_signal | address_issue 88%, none 6% |
| 4 | `get_journey` | largest information gain per cost (0.09 bits, cost 1.0); 12% chance it changes the decision | clean | address_issue 82%, none 13% |
| 5 | `analyze_disruption` | reconcile the recorded exception with the gathered evidence before deciding | ok | address_issue 82%, none 13% |
| 6 | `rank_recovery_actions` | cause 'address_issue' is distinct (82%); rank actions that fit it | ok | address_issue 82%, none 13% |
| 7 | `retrieve_policy_constraints` | check approval and autonomy bounds for the top action | ok | address_issue 82%, none 13% |

<details><summary>Facts returned by tools</summary>

* `get_shipment` — DL-ADD-001 loaded
  * Standard · Prepaid · value SAR 180
  * no exception recorded
  * 0 failed attempt(s) so far
* `predict_risk` — Risk 0.65 (high) — prototype-heuristic
  * ↑ address confidence 0.47
* `get_address_context` — Address weak
  * confidence 0.47
  * 2 address-related failure(s) at this address
  * first delivery to this address
* `get_recipient_context` — No recipient-side problem signal
  * responsiveness high
  * preferred channel WhatsApp
* `get_journey` — 4 events, no failures
  * scan sequence follows the expected order
* `analyze_disruption` — Evidence no code — high confidence
  * most likely cause: address_issue (posterior 0.82, margin 0.69)
* `rank_recovery_actions` — Top action: Ask recipient to confirm the delivery pin
  * #1 Ask recipient to confirm the delivery pin (fit strong, approval none)
* `retrieve_policy_constraints` — Automated action permitted
  * all autonomy bounds satisfied

</details>

## B — Shared root cause → incident-level reasoning

* scenario `route_blockage-seed7` · trigger `exception_recorded` · planner `evidence-driven-evoi-v1`
* **tool path:** `get_shipment → get_recipient_context → predict_risk → check_incident_context → get_facility_context → get_route_context`
* **decision:** `incident` · leading cause `route_disruption` (99%) · P(systemic) 98%
* **headline:** Handle as incident on corridor DK-04
* **rationale:** 6 related failures in 30 min vs baseline 0.4 (z=9.3); 3 more shipments exposed. One incident response is faster and safer than case-by-case fixes.

| # | tool | why it was chosen | outcome | leading hypotheses after |
|---|---|---|---|---|
| 0 | `get_shipment` | bootstrap: shipment facts are needed to form a prior | ok | recipient_unavailable 54%, address_issue 11% |
| 1 | `get_recipient_context` | largest information gain per cost (0.41 bits, cost 1.0); 46% chance it changes the decision | no_signal | address_issue 22%, recipient_unavailable 19% |
| 2 | `predict_risk` | largest information gain per cost (0.25 bits, cost 0.5); 39% chance it changes the decision | driver_route | route_disruption 51%, address_issue 12% |
| 3 | `check_incident_context` | largest information gain per cost (0.58 bits, cost 1.5); 84% chance it changes the decision | incident_confirmed | route_disruption 77%, facility_backlog 16% |
| 4 | `get_facility_context` | largest information gain per cost (0.29 bits, cost 1.0); 100% chance it changes the decision | normal | route_disruption 91%, unknown 3% |
| 5 | `get_route_context` | largest information gain per cost (0.15 bits, cost 1.5); 21% chance it changes the decision | blocked_stationary | route_disruption 99%, unknown 1% |

<details><summary>Facts returned by tools</summary>

* `get_shipment` — DL-ROU-001 loaded
  * Standard · COD SAR 2,450 · value SAR 2,450
  * recorded exception: RECIPIENT_NOT_AVAILABLE
  * 0 failed attempt(s) so far
* `get_recipient_context` — No recipient-side problem signal
  * responsiveness high
  * preferred channel WhatsApp
* `predict_risk` — Risk 0.74 (high) — prototype-heuristic
  * ↑ corridor at 16% of typical speed
  * ↑ recorded exception RECIPIENT_NOT_AVAILABLE
* `check_incident_context` — 6 related failures on corridor DK-04
  * 6 in last 30 min vs baseline 0.4±0.6 · z=9.3 (threshold 3)
  * members: DL-ROU-001, DL-ROU-002, DL-ROU-003, DL-ROU-004, DL-ROU-005, DL-ROU-006 · 3 exposed
* `get_facility_context` — Branch operating normally
  * backlog 25 parcels
* `get_route_context` — Vehicle held in a corridor slowdown
  * corridor 10 km/h vs 62 typical (16%)
  * vehicle stationary 50 min

</details>

## C — Conflicting evidence → human escalation

* scenario `custody_conflict-seed7` · trigger `analyst_request` · planner `evidence-driven-evoi-v1`
* **tool path:** `get_shipment → predict_risk → get_journey → check_incident_context → get_recipient_context → get_route_context → analyze_disruption → escalate_case`
* **decision:** `escalate` / `conflicting_evidence` · leading cause `custody_anomaly` (91%) · P(systemic) 0%
* **headline:** Escalate — the agent will not guess a cause
* **rationale:** Evidence contradicts itself: the scans point to a custody anomaly (91%), so no recovery action is safe until a person establishes what actually happened to the parcel.
* **question for the human:** Was the parcel handed to the recipient, or was the 'delivered' scan made in error?

| # | tool | why it was chosen | outcome | leading hypotheses after |
|---|---|---|---|---|
| 0 | `get_shipment` | bootstrap: shipment facts are needed to form a prior | ok | recipient_unavailable 19%, none 17% |
| 1 | `predict_risk` | largest information gain per cost (0.25 bits, cost 0.5); 0% chance it changes the decision | driver_custody | unknown 16%, custody_anomaly 16% |
| 2 | `get_journey` | largest information gain per cost (0.56 bits, cost 1.0); 0% chance it changes the decision | sequence_conflict | custody_anomaly 80%, unknown 6% |
| 3 | `check_incident_context` | largest information gain per cost (0.21 bits, cost 1.5); 6% chance it changes the decision | no_cluster | custody_anomaly 81%, attempt_not_completed 6% |
| 4 | `get_recipient_context` | largest information gain per cost (0.08 bits, cost 1.0); 0% chance it changes the decision | no_signal | custody_anomaly 80%, unknown 6% |
| 5 | `get_route_context` | largest information gain per cost (0.11 bits, cost 1.5); 0% chance it changes the decision | attempt_geo_mismatch | custody_anomaly 91%, attempt_not_completed 6% |
| 6 | `analyze_disruption` | reconcile the recorded exception with the gathered evidence before deciding | ok | custody_anomaly 91%, attempt_not_completed 6% |
| 7 | `escalate_case` | policy requires human review (conflicting_evidence) | ok | custody_anomaly 91%, attempt_not_completed 6% |

<details><summary>Facts returned by tools</summary>

* `get_shipment` — DL-CUS-001 loaded
  * Standard · Prepaid · value SAR 950
  * no exception recorded
  * 1 failed attempt(s) so far
* `predict_risk` — Risk 0.60 (high) — prototype-heuristic
  * ↑ 'out_for_delivery' recorded after 'delivered' at 11:10
* `get_journey` — Conflicting custody scans
  * 'out_for_delivery' recorded after 'delivered' at 11:10
* `check_incident_context` — No related failures
  * 0 in last 30 min vs baseline 0.3±0.5 · z=-0.6 (threshold 3)
* `get_recipient_context` — No recipient-side problem signal
  * responsiveness medium
  * preferred channel Call
* `get_route_context` — Failed attempt logged 318 m from the address
  * courier GPS places the attempt away from the delivery address
  * corridor 58 km/h vs 62 typical (94%)
  * vehicle stationary 0 min
* `analyze_disruption` — Evidence no code — high confidence
  * most likely cause: custody_anomaly (posterior 0.91, margin 0.85)
* `escalate_case` — Escalated to shift supervisor (P2)
  * Was the parcel handed to the recipient, or was the 'delivered' scan made in error?

</details>

## Functional sweep (synthetic, 11 scenarios × 20 seeds)

* runs: 220 · distinct tool paths: 12 · scenario-expectation pass rate: 100% · safety-invariant violations: 0
* **Read with care:** scenarios were authored alongside the agent and seeds vary geometry/counts, not structure. The pass rate shows the logic
  behaves as designed; it says nothing about real-world accuracy. The invariants (no automation above value/attempt/confidence bounds, no skipped
  policy gate, no repeated tool, escalation always carries a packet) are the stronger result.

| scenario | pass | mean tool calls |
|---|---|---|
| healthy | 100% | 4 |
| address_risk | 100% | 8 |
| route_blockage | 100% | 6 |
| custody_conflict | 100% | 8.7 |
| recipient_unavailable | 100% | 6 |
| repeated_failures | 100% | 6 |
| branch_backlog | 100% | 4 |
| stalled_no_scan | 100% | 9 |
| pickup_unavailable | 100% | 11 |
| courier_no_show | 100% | 11 |
| unknown_anomaly | 100% | 10 |

## Metamorphic checks (change the evidence → behaviour must change)

| perturbation | before | after | required change observed |
|---|---|---|---|
| `address_ok` | auto_eligible / address_issue | resolved / none | True |
| `drop_delivered_scan` | escalate / custody_anomaly | recommend / attempt_not_completed | True |
