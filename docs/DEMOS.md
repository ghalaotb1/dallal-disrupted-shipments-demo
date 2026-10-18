# Demo guide: launch, scenarios, recording

Everything runs on one Apple-silicon laptop (tested on 16 GB): the Next.js frontend, the Python backend with the agent and three trained models, a **sandbox** WhatsApp channel and, optionally, Qwen3.5-4B through Ollama. Nothing can message a real person (`WHATSAPP_MODE` is forced to `sandbox`) and nothing can execute a real operational action (the executor is simulated). Drivers, parcels, recipients and the road blockage are simulated; everything the backend decides is real.

## Launch, reset, stop

```bash
cd backend && uv venv && uv pip install -e ".[dev,api,report]" && cd ..   # once
npm install                                                                  # once
ollama pull qwen3.5:4b                                                       # optional (3.3 GB); without it, replies are read by rules only
npm run demo            # starts Ollama (if installed), backend :8000, frontend :3000, waits for health
npm run demo:reset      # same, after wiping the demo database
npm run demo:stop
npm run demo:scenarios  # headless end-to-end check of the three scenarios (needs npm run demo running)
```

Open <http://localhost:3000>. The top bar must show **Live** and **Sandbox**. If it says **Offline**, nothing can be investigated (the app never fakes an investigation): check `backend/.data/logs/backend.log`.

Memory: the launcher starts Ollama with one loaded model and a 10-minute keep-alive; Qwen3.5-4B needs about 3.6 GB. `./scripts/demo.sh --no-llm` skips Ollama entirely.

## What you see

- **Top: KPI strip.** Active parcels, at risk, disrupted, with manager, open cases, resolved by Dallal. Click a card to filter the routes.
- **Left: Routes.** One card per driver and van; one bar segment per parcel (grey = delivered, amber = at risk, red = failed, violet = with manager, blue = recovering, green = resolved). Cards with problems rise to the top. Click a card for its parcels, a parcel for its journey.
- **Centre: map.** Real roads, moving vans, parcels as stops. The camera follows the open case.
- **Right: Cases / Assistant.** Three open cases are listed. Opening one starts Dallal by itself: *What happened → What Dallal found → Who it asked → What changed → Decision*. The Assistant answers in Arabic or English using the local Qwen model, grounded in the live data (see below).
- **Top right: Operations | Manager, Reset.** Manager shows what needs approval. Reset restores the same starting point and clears the backend's demo history, so a replay is identical.

## The three cases

All three were chosen after reading the real policy (`backend/dallal/agent/v2/policy.py`, `utility.yaml`, `actions.yaml`): the first two end in actions the policy genuinely permits Dallal to take alone; the third is a group plan, which policy reserves for a supervisor, and the backend enforces it. They can be opened in any order.

### Address not found: resolved automatically
Open the case. Findings appear (address weak, one failed attempt, no customer-side problem). *Question needed?* **No.** Conclusion: address problem, 93%. Decision: **Resolved by Dallal**, no manager, with six safety checks that all passed. The simulated world then reports the outcome and the parcel turns green. Proves: diagnosis from evidence, a decision not to ask, bounded autonomy.

### Customer not answering: asks, then resolves
Open the case. The records are ambiguous, so Dallal asks **Turki, the driver**, with the reason and the value of asking. Tap the highlighted reply **At address, nobody answered** (or type Arabic free text: rules cannot read it, a local model suggests an answer, a person confirms). *What changed:* customer not available 64% → 91%; Dallal contacts the customer (sandbox). Replay and tap **Cannot find the address**: the decision becomes a recommendation an operator confirms. Proves: value-of-information questioning, whom to ask, belief update from a reply.

### Road blockage: escalates to the manager
Open the case. Dallal finds 4 failures on the corridor against a normal 0.4 and treats them as **one incident**: one plan for 10 parcels on 3 drivers (wait, spare courier, pickup point), and **one** question to the dispatcher (not 20). The sandbox dispatcher then **replies by itself** (a short typing indicator, then a tap on *Blocked, expected > 30 min*): the tap goes through the backend's real inbound path (webhook, interpreter, belief update, re-planning). The belief moves 30% → 88% and a *Plan updated* list shows each parcel that changed (for example Wait → Pickup). It is labelled a sandbox simulation and nothing reaches a phone. The case then needs the manager; an operator cannot approve it. Switch to **Manager**, review the reason, evidence and plan by driver, **Approve plan**. Parcels move to spare couriers and pickup points, outcomes stay pending. Proves: route-level impact, coordination across drivers, human approval where policy requires it.

## Recommended 60-90 second recording

| Time | Action | Say |
|---|---|---|
| 0:00 | Open Dallal. Point at the KPIs, routes and map. | "Dallal monitors every driver and route and detects problems." |
| 0:10 | Open **Address not found**. | "It investigates on its own, decides no question is needed, and resolves it within safety limits." |
| 0:28 | Open **Customer not answering**, tap the highlighted reply. | "Here the records can't say why, so it asks the driver. The answer changes its belief and its action." |
| 0:50 | Open **Road blockage**; the dispatcher replies by itself. | "One blockage, three drivers: one plan, one question. The reply updates the plan." |
| 1:10 | Switch to **Manager**, **Approve plan**. | "Group actions need a manager. Routes update." |
| 1:20 | Open **Assistant**, ask in Arabic: "لماذا فشل تسليم الطرد DL-20655 وماذا فعل دلّال؟". | "Operators can ask in Arabic or English; it answers from live data and shows its sources." |

Tips: use **Reset** to retake; use a window of 1440x900 or larger; the basemap needs internet (routes and parcels still show without it); give the page two seconds after loading.

## The Assistant (local Qwen)

- **What it does:** a conversational interface over the operation. Ask about drivers, routes, parcels, disruptions, Dallal's investigations (what it checked, whom it asked, what they replied, how its belief changed) and recovery decisions, in Arabic or English. Answers stream in; *Based on* chips link to the parcel, driver or case used.
- **Grounding:** the backend (`backend/dallal/assistant.py`) builds a context from the operation snapshot the screen sends (drivers, parcels, cases, KPIs, activity) plus its **own records**: agent runs, WhatsApp questions and replies, coordinated plans, the ledger. Only what the question needs is sent to the model (about 1,000 tokens). The prompt forbids anything outside it, and every answer is checked: an unknown parcel / run / plan id or a percentage that is not in the context discards the answer and shows a verified basic answer instead.
- **It never decides:** the deterministic agent, the policy gates and the manager approval are untouched. Asked to approve, it explains where it is done.
- **Local and graceful:** Qwen3.5-4B through Ollama (`DALLAL_ASSISTANT_MODEL` overrides it). The model is loaded when the tab opens ("Loading the local model…"), the first token takes about 4-8 s, and the status line shows whether Qwen is ready. If Ollama or the model is missing, or an answer takes too long, the chat answers in basic mode with a note.
- **Limit:** a 4B model can still mis-summarise (for example a count); the *Based on* chips and the Technical details let you check. `npm run demo:assistant` runs a live check in Arabic and English against the real model.

## What is real, what is simulated

| Real | Simulated (labelled) |
|---|---|
| The agent's reasoning, tool choices, belief updates, value-of-information decisions, the policy and approval gates, the coordinated-plan solver, the reply interpreter | Drivers, parcels, recipients, merchants, vans' movement, the road blockage |
| Backend enforcement of roles (an operator cannot approve a group plan; only `auto_eligible` decisions run without a person) | Spare couriers, pickup capacity, promise windows and prior blockage duration (assumptions, marked *Sim*) |
| Real road geometry (OpenStreetMap / OSRM); WhatsApp message logic, delivery states, 24-hour window rules | WhatsApp delivery (sandbox: recorded, never sent) and the replies you tap on the simulated device |
| Qwen reading unclear replies as a *suggestion* a person confirms (optional, local) | Action execution and outcomes (observed in the simulated world; the agent never grades itself) |
| Model domain restriction: trained models abstain on these simulated parcels, and the UI says so | |

The steps in the case panel are shown at a readable pace; the backend run itself completes in well under a second. Likelihoods, utilities and thresholds inside the agent are expert assumptions (no public dataset has root causes or action outcomes); see [the evaluation report](EVALUATION_REPORT.md).

## Verification

```bash
npm run demo:scenarios   # headless: same code as the browser, real backend. Asserts for each scenario the decision, the question (or its absence), sandbox delivery, role enforcement, determinism on replay and pending outcomes
npm run demo:assistant   # live Qwen assistant check in Arabic and English (needs Ollama with qwen3.5:4b)
npm run demo:check       # backend-only traces of the same ideas (docs/demos/DEMO_TRACES.md)
```

## Other pages

`/models` is the **Model evidence** page: each trained risk model with its held-out metrics, calibration and feature contract, and a real-data replay (a real held-out LaDe delivery task through the live agent, scored by the model or an explicit abstention, with the real outcome revealed afterwards). It is not linked from the main screen; open it directly when asked how the models were validated.

## Troubleshooting

- Logs: `backend/.data/logs/{backend,frontend,ollama}.log`.
- *Backend offline* in the top bar: the backend is not on `:8000`; `npm run demo` again.
- A scenario looks different on replay: restart with `npm run demo:reset` (the backend must be the one launched by the script so the demo reset is allowed: it only works with `DALLAL_ENV=dev`, sandbox WhatsApp and simulated execution).
- The basemap is blank: the tile servers are slow or unreachable; routes, vans and parcels still work.
- Real-data replay needs the LaDe canonical tables under `backend/.data/canonical/lade` (`python -I -m dallal.data.cli build lade`).
