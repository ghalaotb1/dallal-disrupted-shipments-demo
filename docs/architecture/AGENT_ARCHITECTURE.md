# Dallal — Agent Architecture

> **Superseded in part.** This describes the v1 agent. The v2 decision architecture (ensemble belief, net value of information, active WhatsApp inquiries, coordinated recovery) and a critical review of v1 are in [AGENT_V2.md](AGENT_V2.md). The tool framework, provenance and safety invariants described here are unchanged.

*Code: [`backend/dallal/agent/`](../../backend/dallal/agent/), [`tools/`](../../backend/dallal/tools/), [`recovery/`](../../backend/dallal/recovery/) · Traces: [`EVAL_TRACES.md`](EVAL_TRACES.md)*

## Design in one paragraph

A **stateful, tool-using agent** keeps a Bayesian belief over *(root cause × is-this-systemic)*. Each investigative tool returns a discrete outcome that updates the belief. The planner picks the next tool by **exact expected information gain per unit cost**, gated by a **decision-theoretic stop** ("is there ≥10% chance another tool changes what I would do?"). The path is therefore not a script: it emerges from what the tools return. Facts, predictions, analytics and policy come from deterministic tools; an LLM, if used, only chooses *which tool next* and cannot override gates, numbers or the autonomy policy.

```
trigger ──► get_shipment ──► prior over (cause, systemic)
                │
        ┌───────▼────────────────────────────────────────────┐
        │ loop: planner.next(state)                          │
        │   EVOI table over eligible information tools        │
        │   pick argmax EIG/cost with P(decision change)≥10%  │
        │   runtime validates (exists · not repeated · precond)│
        │   tool runs → outcome → Bayes update → trace         │
        └───────┬────────────────────────────────────────────┘
                ▼ closing gates (always allowed, never starved by the budget)
     incident confirmed? ─► stop (incident-level handling)
     healthy ≥80%?        ─► stop (monitor)
     analyze_disruption   (recorded code vs evidence: agrees / conflicts / inconclusive)
     distinct cause?      ─► rank_recovery_actions ─► retrieve_policy_constraints
                ▼
        policy-v1 decision:  incident · resolved · auto_eligible · recommend · escalate
                ▼
        escalate ─► escalate_case (packet: question, evidence, leading hypotheses)
        execute  ─► ledger (decision/action/outcome=pending), simulated executor
```

## Why this satisfies the Dallal principles

| Principle | Mechanism |
|---|---|
| **Preventive** | `risk_alert` triggers start from a prior where "healthy" holds only about a third of the mass (the alert itself is evidence); weak address / predicted risk is investigated *before* any failure (Case A). |
| **Evidence-based diagnosis** | Posterior from tool outcomes; `analyze_disruption` reconciles the human-recorded code with it and reports *agrees / conflicts / inconclusive*. |
| **Systemic awareness** | The latent *systemic* variable is part of the belief; `check_incident_context` runs when it is uncertain and can end per-parcel handling (Case B skips ranking entirely). |
| **Bounded autonomy** | `auto_eligible` requires ALL of: automatable & approval-free action · posterior ≥ 80% · reversible/low-impact · value ≤ SAR 1,500 · ≤ 2 prior failures · no code/evidence conflict. Otherwise recommend or escalate. |
| **Human escalation** | Unknown, conflicting or high-impact cases hand a *packet* to a supervisor, with the single question that must be answered (derived from the competing hypotheses, never free-form). |
| **Auditable** | Every step records tool, args, *why chosen*, the EVOI candidate table, outcome, belief after, duration, provenance (data origin, model id/basis); JSON log line per call; one JSON document per run. |
| **Learning-ready** | `Ledger` writes canonical `decision`/`action`/`outcome` rows with assignment mechanism, propensity (required if randomised), frozen context snapshot, policy id; outcomes stay `pending` — never fabricated. |

## Tools (13)

`get_shipment` · `get_journey` · `get_address_context` · `get_recipient_context` · `get_route_context` · `get_facility_context` · `get_pickup_context` · `predict_risk` · `check_incident_context` · `analyze_disruption` · `rank_recovery_actions` · `retrieve_policy_constraints` · `escalate_case`

Each tool is a `ToolSpec` (name, description, JSON schema, kind, cost, precondition) so it can be offered to an LLM as a function-calling tool unchanged. Tools return *facts + a discrete outcome*; they never call an LLM. Preconditions create genuinely different paths: `get_pickup_context` exists only for parcels with a pickup point, `get_route_context` only with a corridor/courier, `rank_recovery_actions` only after a diagnosis.

## Swapping real components in (no agent changes)

| Today | Tomorrow | Interface |
|---|---|---|
| `HeuristicRiskModel` (transparent noisy-OR; labelled `prototype-heuristic`) | trained gradient-boosted model (baselines in `docs/ml/`) | `RiskModel.score(world, shipment_id, facts)` |
| `Bundle` over fixtures / canonical parquet | SPL event store queries | same accessors, all `as_of`-filtered |
| `SimulatedExecutor` (records, sends nothing) | SPL messaging / dispatch APIs | `ActionExecutor.execute(tool, subject, params)` |
| Expert-assumption observation models (`expert_assumption_v1`) | tables re-estimated from SPL exception + resolution logs | `OBSERVATION_MODELS` |
| Default detector constants | per-scope calibrated quasi-Poisson (see backtest) | `incident_signals` |
| `EvidenceDrivenPlanner` | `LLMPlanner` (Anthropic tool use) | `Planner.next(state, tools)` |

## The LLM's role and limits

`LLMPlanner` receives the belief, tools called so far, the eligible tools, and the EVOI table as advice; it picks one tool or `finish`. The runtime then **rejects** unknown, repeated, or precondition-failing choices and **refuses** an early `finish` while a tool still has decision value (all recorded as deviations). Mandatory closing gates are never delegated. It activates only if `ANTHROPIC_API_KEY` is set; **no live-LLM run has been performed in this phase** (no key was available) — the plumbing is covered by offline tests with an injected fake client, and the offline planner is the one evaluated.

## Recovery decisioning — what it is and is not

`rank_recovery_actions` scores `Σ_c P(cause=c)·suitability(action,c) − friction`, with preconditions (recipient reachable, alternative pickup online, alternative route, spare courier) and repeat-failure adjustments (after ≥2 failures, re-contact is down-weighted and redirection up-weighted). It is a **policy**, labelled `method=evidence_weighted_policy_ranking`, `causal_claim=false`. No public data pairs actions with outcomes, so nothing here is learned or causal.

## Frontend

`dallal.agent.frontend.to_frontend(run)` emits the exact `AgentRun` shape of `types/domain.ts` (steps, statuses, outcome union). Three new tool names map to the nearest existing `ToolName` with the real name preserved in `args`. Widening the TS union is a small optional change; **no frontend file was modified in this phase**.

## Honesty ledger (what is assumption vs. evidence)

* **Real, measured:** data audit, EDA, baselines, incident backtest on real noise.
* **Expert assumption:** all observation-model probabilities, priors, action suitabilities, autonomy bounds, EVOI/stop thresholds.
* **Synthetic:** every agent evaluation case; pass rates are functional, not accuracy.
* **Not done:** live-LLM evaluation, trained model behind `predict_risk`, calibrated detector inside the agent, any causal recovery claim.
