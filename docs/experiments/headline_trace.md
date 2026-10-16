# Headline trace — developing disruption (synthetic scenario, sandbox WhatsApp)

> **SYNTHETIC case, SANDBOX channel.** No message left this machine (`real_delivery: false`). Utilities are SAR-equivalents from `utility.yaml` (assumptions).

Scenario `developing-seed11`: a high-value COD parcel (1,850 SAR); the courier's van has been parked ~60 m from the address for 28 min. No scan says why.

## A. Same case without inquiries (`v2_no_inquiry`)

* decision: **recommend** — Recommended: Contact recipient to confirm availability
* leading cause: `recipient_unavailable` (62%)

| # | step | why | outcome | belief after (top 2) |
|---|---|---|---|---|
| 0 | `get_shipment` | bootstrap: shipment facts are needed to form a prior | ok | none 33%, recipient_unavailable 15% |
| 1 | `get_journey` | net value of information +6.93 SAR-eq (gross 7.08, cost 0.15); 48% chance it changes the best option | clean | none 58%, address_issue 10% |
| 2 | `get_address_context` | net value of information +19.29 SAR-eq (gross 19.44, cost 0.15); 20% chance it changes the best option | address_ok | none 64%, recipient_unavailable 10% |
| 3 | `get_route_context` | net value of information +6.50 SAR-eq (gross 6.75, cost 0.25); 20% chance it changes the best option | stationary_at_address | recipient_unavailable 56%, none 18% |
| 4 | `get_facility_context` | net value of information +6.67 SAR-eq (gross 6.82, cost 0.15); 23% chance it changes the best option | normal | recipient_unavailable 60%, none 20% |
| 5 | `check_incident_context` | net value of information +2.36 SAR-eq (gross 2.66, cost 0.30); 5% chance it changes the best option | no_cluster | recipient_unavailable 61%, none 21% |
| 6 | `get_pickup_context` | net value of information +0.77 SAR-eq (gross 0.92, cost 0.15); 5% chance it changes the best option | online | recipient_unavailable 62%, none 22% |
| 7 | `analyze_disruption` | reconcile the recorded exception with the gathered evidence before deciding | ok | recipient_unavailable 62%, none 22% |
| 8 | `rank_recovery_actions` | leading cause 'recipient_unavailable' (62%); rank options by expected utility under the full belief | ok | recipient_unavailable 62%, none 22% |
| 9 | `retrieve_policy_constraints` | check approval and autonomy bounds on the best action | warn | recipient_unavailable 62%, none 22% |

## B. With value-based inquiry (`v2_value`)

### B1. Investigation until it needs a person

| # | step | why | outcome | belief after (top 2) |
|---|---|---|---|---|
| 0 | `get_shipment` | bootstrap: shipment facts are needed to form a prior | ok | none 33%, recipient_unavailable 15% |
| 1 | `get_journey` | net value of information +6.93 SAR-eq (gross 7.08, cost 0.15); 48% chance it changes the best option | clean | none 58%, address_issue 10% |
| 2 | `get_address_context` | net value of information +19.29 SAR-eq (gross 19.44, cost 0.15); 20% chance it changes the best option | address_ok | none 64%, recipient_unavailable 10% |
| 3 | `get_route_context` | net value of information +6.50 SAR-eq (gross 6.75, cost 0.25); 20% chance it changes the best option | stationary_at_address | recipient_unavailable 56%, none 18% |
| 4 | `get_facility_context` | net value of information +6.67 SAR-eq (gross 6.82, cost 0.15); 23% chance it changes the best option | normal | recipient_unavailable 60%, none 20% |
| 5 | `check_incident_context` | net value of information +2.36 SAR-eq (gross 2.66, cost 0.30); 5% chance it changes the best option | no_cluster | recipient_unavailable 61%, none 21% |
| 6 | `get_pickup_context` | net value of information +0.77 SAR-eq (gross 0.92, cost 0.15); 5% chance it changes the best option | online | recipient_unavailable 62%, none 22% |
| 7 | `ask:ask_courier_status` | net value of information +1.08 SAR-eq (gross 3.13, cost 2.05); 39% chance it changes the best option; databases are exhausted, so ask courier: answer expected in ~5 min w | warn | recipient_unavailable 62%, none 22% |

**Paused:** Asked courier: الشحنة DL-DEV-001: ما حالة التسليم؟

### B2. The WhatsApp exchange (sandbox)

* **Dallal → courier** `[sandbox/sandbox_accepted]` الشحنة DL-DEV-001: ما حالة التسليم؟
* **courier → Dallal** `[sandbox/received]` (interactive reply) — read as `at_address_no_answer` by `interactive_id`

### B3. After the answer

| # | step | why | outcome | belief after (top 2) |
|---|---|---|---|---|
| 0 | `get_shipment` | bootstrap: shipment facts are needed to form a prior | ok | none 33%, recipient_unavailable 15% |
| 1 | `get_journey` | net value of information +6.93 SAR-eq (gross 7.08, cost 0.15); 48% chance it changes the best option | clean | none 58%, address_issue 10% |
| 2 | `get_address_context` | net value of information +19.29 SAR-eq (gross 19.44, cost 0.15); 20% chance it changes the best option | address_ok | none 64%, recipient_unavailable 10% |
| 3 | `get_route_context` | net value of information +6.50 SAR-eq (gross 6.75, cost 0.25); 20% chance it changes the best option | stationary_at_address | recipient_unavailable 56%, none 18% |
| 4 | `get_facility_context` | net value of information +6.67 SAR-eq (gross 6.82, cost 0.15); 23% chance it changes the best option | normal | recipient_unavailable 60%, none 20% |
| 5 | `check_incident_context` | net value of information +2.36 SAR-eq (gross 2.66, cost 0.30); 5% chance it changes the best option | no_cluster | recipient_unavailable 61%, none 21% |
| 6 | `get_pickup_context` | net value of information +0.77 SAR-eq (gross 0.92, cost 0.15); 5% chance it changes the best option | online | recipient_unavailable 62%, none 22% |
| 7 | `ask:ask_courier_status` | net value of information +1.08 SAR-eq (gross 3.13, cost 2.05); 39% chance it changes the best option; databases are exhausted, so ask courier: answer expected in ~5 min w | at_address_no_answer | recipient_unavailable 95%, unknown 2% |
| 8 | `analyze_disruption` | reconcile the recorded exception with the gathered evidence before deciding | ok | recipient_unavailable 95%, unknown 2% |
| 9 | `rank_recovery_actions` | leading cause 'recipient_unavailable' (95%); rank options by expected utility under the full belief | ok | recipient_unavailable 95%, unknown 2% |
| 10 | `retrieve_policy_constraints` | check approval and autonomy bounds on the best action | warn | recipient_unavailable 95%, unknown 2% |

* decision: **recommend** / action `contact_recipient` — Recommended: Contact recipient to confirm availability
* rationale: recipient_unavailable at 95%; best option by expected utility. parcel value <= SAR 1,500.
* leading cause `recipient_unavailable` (95%); virtual elapsed 2.2 min

### Value-of-information table at the moment of asking

| source | net VOI | gross | cost | P(changes best action) | reply chance | latency (min) |
|---|---|---|---|---|---|---|
| `ask_courier_status` | +1.08 | 3.13 | 2.05 | 39% | 85% | 5 |
| `predict_risk` | -0.21 | -0.12 | 0.10 | 0% | 100% | 0 |
| `get_recipient_context` | -0.38 | -0.23 | 0.15 | 0% | 100% | 0 |
| `ask_corridor_status` | -1.47 | -0.92 | 0.55 | 4% | 95% | 5 |
| `ask_branch_backlog` | -10.33 | -9.28 | 1.05 | 8% | 90% | 9 |
| `ask_recipient_availability` | -27.70 | -25.95 | 1.75 | 27% | 78% | 29 |
| `ask_recipient_location` | -42.39 | -40.14 | 2.25 | 6% | 56% | 42 |

### B4. Why the answer matters: the same paused case under every possible reply

| courier's answer | belief after | decision | recommended action |
|---|---|---|---|
| `at_address_no_answer` | recipient_unavailable 95% | recommend | contact_recipient |
| `cannot_find_address` | address_issue 44% | escalate / unknown_pattern | — |
| `road_blocked` | route_disruption 44% | awaiting_response | — |
| `on_route_normal` | none 86% | resolved | — |
| `never_reached` | attempt_not_completed 42% | escalate / unknown_pattern | — |
| `parcel_missing` | unknown 33% | escalate / unknown_pattern | — |

