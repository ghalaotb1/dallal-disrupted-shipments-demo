# دلّال · Dallal

**An AI agent for disrupted last-mile deliveries: it investigates, asks the right person only when it is worth it, recovers parcels across drivers, and knows when to call a manager.**

Dallal is organised the way a last-mile operation really works: a **driver** carries many **parcels** along one **route**. The operator sees drivers and routes first, each with a segmented progress bar and a status per parcel, and can open any single parcel. When a delivery fails or a road jams, Dallal's agent investigates from evidence, decides whether a question is worth asking (and whom to ask), updates its understanding from the reply, and either resolves the case within strict safety limits, coordinates one recovery plan across all affected drivers, or escalates to a manager.

> **What is real and what is simulated.** The agent, its Bayesian belief and value-of-information reasoning, the policy and approval gates, the WhatsApp channel logic and the coordinated-recovery solver all run for real in the Python backend (`backend/`). Drivers, parcels, recipients, spare couriers and the road blockage are a **simulated operation** on real Eastern Province roads (labelled *Simulated* in the UI). WhatsApp is **sandbox only**: nothing reaches a phone. Actions execute **in simulation**, and an outcome is only shown once the simulated world observes it. No SPL data is used. The three trained risk models are validated on other countries' public data and abstain on simulated parcels.

---

## The experience

| Area | What it shows |
|---|---|
| **Drivers & routes** (left) | One card per driver and van: segmented progress bar (one segment per parcel, coloured by status), "N of M done", next stop and ETA, and a one-line note when something is wrong ("Slow traffic on King Fahd Rd"). Expand a card to see every parcel on the route; click a parcel to inspect it. Cards with problems rise to the top and say how many parcels are affected. |
| **Map** (centre) | Real roads. Each route is a line, each van a labelled marker that moves, each parcel a stop coloured by status. A disruption shows as a blockage zone with the affected routes highlighted; after a plan, parcels that left a route are drawn as dashed links to their spare courier or pickup point. The camera follows the story. |
| **Dallal** (right) | Idle: the three situations to try. During a case: **What happened → What Dallal found → Who it asked and why → What changed → Decision and action**, told in plain language. An optional *Technical details* section holds the trace, probabilities and policy. |
| **Operations / Manager** (top right) | The manager view collects what policy reserves for a supervisor (group plans, escalations) with the reasons, the evidence and Approve / Reject. |

## The three demonstration scenarios

Each runs the real backend agent on deterministic simulated inputs, and can be reset and replayed (the backend's demo history is cleared on every start, so a replay is identical).

| | Situation | What it proves | Who decides |
|---|---|---|---|
| **A · Address doubt** | Yousef cannot find the address for `DL-20417` (Express, SAR 740, first delivery there). | The agent diagnoses from evidence alone, judges that no question is worth asking, and fixes it within its safety limits. | **Dallal**, automatically (policy gates all pass) |
| **B · Ask the driver** | Nobody answers for `DL-20655` on Turki's route; the records cannot say why. | The agent reads the records, then asks the **driver** (the person who can see the door). The reply moves its belief from 64% to 91% "customer not available" and the action it takes; a different reply gives a different decision. | **Dallal**, automatically after the reply |
| **C · Road blocked** | A lane blockage on King Fahd Rd delays 4 parcels on 3 drivers and exposes 6 more. | The agent recognises one shared incident, plans all 10 parcels **together** over shared spare couriers and pickup points, asks the dispatcher **once** (not once per parcel), and the answer changes the plan for 5 parcels. | **Manager** (policy: group actions need a supervisor; the backend refuses an operator) |

## Run it

Requirements: Node.js ≥ 20.9, Python 3.11+ (uv), optional Ollama with `qwen3.5:4b`.

```bash
npm install
cd backend && uv venv && uv pip install -e ".[dev,api,report]" && cd ..
npm run demo            # backend :8000 + frontend :3000 (+ Ollama if installed); open http://localhost:3000
npm run demo:reset      # same, after wiping the demo database
npm run demo:stop
npm run demo:scenarios  # headless end-to-end check of A, B and C against the running backend
```

The top bar must read **Live backend** and **WhatsApp sandbox**. Full launch, recording and troubleshooting guide: [docs/DEMOS.md](docs/DEMOS.md).

## Architecture of the front end

```
app/page.tsx              the operations screen (app/models: the real-data model evidence page)
components/ops/           TopBar · RoutesPanel · OpsMap (MapLibre) · CasePanel · Story · PlanCard · ReplyDevice · ManagerPanel
data/ops/world.ts         the simulated operation: 7 drivers, 40 parcels on real road geometry (data/geo/*)
lib/ops/                  scenarios (deterministic staging) · case (backend payloads) · agent (runs, replies, approvals, execution) · narrative · derive
lib/live/                 typed client for the backend API
store/ops.ts              zustand store: world, runs, plans, UI state
scripts/scenario_check.ts the same code driven headlessly against the real backend
```

The browser owns the *simulated physical world*; for every question it snapshots the case (parcel, journey, context, van position, peers on the corridor) and the backend reasons over that snapshot only. Authorization is enforced by the backend (an action runs without a person only if the policy marks it `auto_eligible`; group plans are supervisor-only).

## AI/ML backend

`backend/` (Python 3.11+, FastAPI, SQLite) holds the data pipeline, trained models, the v2 agent, the WhatsApp channel and the coordinated-recovery solver. The frontend talks to it through `lib/live/*` and `lib/ops/*`; without the backend the app says so and runs no investigation (it never fakes one).

| What | Where | Doc |
|---|---|---|
| Critical review of v1 and the v2 decision architecture (ensemble belief, net value of information, bounded autonomy) | `backend/dallal/agent/v2/` | [Agent v2](docs/architecture/AGENT_V2.md) |
| Active inquiries over WhatsApp (sandbox + Cloud API), durable pause/resume, idempotent webhooks | `backend/dallal/channels/`, `service.py`, `store.py` | [WhatsApp](docs/integration/WHATSAPP.md) |
| Coordinated network recovery (joint MILP, one shared question with recourse, supervisor approval) | `backend/dallal/recovery/network.py`, `plans.py` | [Agent v2 §5](docs/architecture/AGENT_V2.md#5-coordinated-network-recovery) |
| Real-data risk models (calibrated, feature-contract, abstaining) and the Model Lab page | `backend/dallal/ml/`, `backend/artifacts/`, `/models` | [Experiments, Part A](docs/experiments/README.md) |
| Guarded LLM planner (Qwen via Ollama) and reply-interpretation benchmark | `backend/dallal/agent/v2/llm_planner.py`, `eval/` | [Experiments](docs/experiments/README.md) |
| **Technical evaluation** (independent simulators, paired, regimes, ablation, sensitivity, safety; real-data results kept apart) | `backend/dallal/sim/`, `dallal/eval/` | [**Evaluation report**](docs/EVALUATION_REPORT.md) · [pitch metrics](docs/experiments/PITCH_METRICS.md) · [charts](docs/experiments/charts) · [results](docs/experiments/results) |
| The three demonstration scenarios (route-centric operations UI) | `scripts/demo.sh`, `scripts/scenario_check.ts`, `backend/scripts/demo_check.py` | [Demo guide](docs/DEMOS.md) · [backend traces](docs/demos/DEMO_TRACES.md) |
| Dataset audit, canonical schema, augmentation, baselines | `backend/registry/`, `dallal/data/`, `dallal/ml/` | [Dataset report](docs/data/DATASET_DECISION_REPORT.md) · [Schema](docs/data/CANONICAL_SCHEMA.md) · [Augmentation](docs/data/AUGMENTATION.md) · [Baselines](docs/ml/TASKS_AND_BASELINES.md) |
| Deployment (Vercel frontend + container backend) | `backend/Dockerfile`, `render.yaml`, `app/api/dallal` | [Deployment](docs/deployment/DEPLOYMENT.md) |

```bash
# backend
cd backend && uv venv && source .venv/bin/activate && uv pip install -e ".[dev,api]"
python -I -m pytest -q
DALLAL_TIME_SCALE=30 python -m uvicorn dallal.api.app:app --port 8000     # sandbox WhatsApp; no secrets needed
npm run demo           # one command: Ollama (optional) + backend :8000 + frontend :3000; npm run demo:reset / demo:stop / demo:check / demo:scenarios
# open http://localhost:3000 and pick scenario A, B or C; /models has the real-data model evidence
```

Datasets are never committed: `python -I -m dallal.data.cli fetch selected --all` reproduces them (hash-verified); training needs them (`python -I -m dallal.ml.train`), serving does not (the three small calibrated artifacts are committed and SHA-256 checked on load).

**Status, honestly.** Real: the three trained models and their held-out metrics (other countries' data, not SPL); the agent, solver, durable runtime and sandbox channel running live in the UI. Not real: any SPL data, any delivered WhatsApp message (the Cloud API provider is implemented but has never talked to Meta), every shipment/courier/recipient, spare-courier capacity, response rates and utilities (assumptions), and all decision experiments (synthetic, assumption-based). The backend is packaged for deployment but not deployed from this environment.

## Data sources & attribution

- Map data © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright) (ODbL), tiles by [OpenFreeMap](https://openfreemap.org) / [CARTO](https://carto.com/attributions).
- Route geometry computed once with the [OSRM](https://project-osrm.org) public demo server.
- Place names geocoded with [Nominatim](https://nominatim.org). All operational records are fictional.
- **Backend datasets** (reproduced from source, never redistributed; full terms in `backend/registry/datasets.yaml`): [Cainiao LaDe](https://huggingface.co/datasets/Cainiao-AI/LaDe) (Wu et al., KDD 2024) · [Amazon Last Mile Routing Research Challenge](https://registry.opendata.aws/amazon-last-mile-challenges) (© Amazon.com, Inc., CC BY-NC 4.0) · [Last-mile route deviations, planned vs. actual](https://data.mendeley.com/datasets/kkwgfvmtxn/1) (Konovalenko, Hvattum, Iversen; CC BY 4.0) · [Olist Brazilian E-Commerce](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) (CC BY-NC-SA 4.0) · Saudi Post | SPL Open Data Platform (areas, cities, offices) · [OCEL 2.0 Order Management](https://zenodo.org/records/8428112) (CC BY 4.0, simulated) · [Cargo 2000](https://archive.ics.uci.edu/dataset/382/cargo+2000+freight+tracking+and+tracing) (Metzger et al., CC BY 4.0) · [DataCo Smart Supply Chain](https://data.mendeley.com/datasets/8gx2fvg2k6/5) (CC BY 4.0, benchmark only). Amazon and Olist are non-commercial licenses: fine for this hackathon/research use, not for a commercial deployment.
