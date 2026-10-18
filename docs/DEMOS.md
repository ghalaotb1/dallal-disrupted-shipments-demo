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

Open <http://localhost:3000>. The top bar must show **Live backend** and **WhatsApp sandbox**. If it says **Backend offline**, nothing can be investigated (the app never fakes an investigation): check `backend/.data/logs/backend.log`.

Memory: the launcher starts Ollama with one loaded model and a 10-minute keep-alive; Qwen3.5-4B needs about 3.6 GB. `./scripts/demo.sh --no-llm` skips Ollama entirely.

## What you see

- **Left: Drivers & routes.** One card per driver and van. The segmented bar has one segment per parcel (grey = delivered, amber = at risk, red = failed, violet = waiting for the manager, blue = recovering, green = resolved). Cards with problems rise to the top and say how many parcels are affected. Click a card to expand its parcels; click a parcel to inspect it (journey, address, promise) and, if you like, *Ask Dallal to check this parcel*.
- **Centre: the map.** Real roads. Routes are lines, vans are labelled markers that move, parcels are stops. The camera follows the story.
- **Right: Dallal.** Idle: the three situations. During a case: *What happened → What Dallal found → Who it asked and why → What changed → Decision and action*. *Technical details* (collapsed) holds the trace, probabilities and policy.
- **Top: Scenarios A / B / C, Reset, Operations | Manager.** Scenario buttons stage a fresh, identical situation; *Replay* (top of the case panel) does the same; *Reset* returns to a calm network. Every start also clears the backend's demo history, so a replay is identical.

## The three scenarios

All three were chosen after reading the real policy (`backend/dallal/agent/v2/policy.py`, `utility.yaml`, `actions.yaml`): A and B end in actions the policy genuinely permits Dallal to take alone; C is a group plan, which policy reserves for a supervisor, and the backend enforces it.

### A · Address doubt: Dallal resolves it alone

1. Click **A · Address doubt**. Yousef's route turns red; the card says *1 failed*; the case panel says what happened.
2. Click **Investigate with Dallal**. Findings appear one by one (address weak, a failed attempt logged, no recipient-side problem).
3. *Did it need to ask anyone?* **No** - the best question was not worth its cost, so Dallal asks nobody.
4. *What Dallal concluded:* address problem, 93%. *Decision:* "Dallal resolved this on its own - no manager needed", with the six safety checks that all passed (reversible and low impact, SAR 740 within the SAR 1,500 limit, at most 2 earlier failures, confident and nothing unexplained, works even in the pessimistic case, evidence agrees with the record).
5. A few seconds later the simulated world reports the outcome: the parcel turns green, "Failure prevented", Yousef's bar fills.

Proves: evidence-based diagnosis, a *decision not to ask*, bounded autonomy.

### B · Ask the driver: intelligent inquiry changes the decision

1. Click **B · Ask the driver**, then **Investigate with Dallal**. Nobody answered for `DL-20655`; the records are ambiguous (customer not available 64%).
2. Dallal reads six sources, then asks **Turki, the driver**: why him (he can see the door), what it is worth, the chance of a reply. The WhatsApp card says *Sandbox - not sent to a real phone*.
3. In **Simulated device** tap **At address, nobody answered** (highlighted). You can also type Arabic free text such as `وصلت العنوان بس مافي احد يفتح`: the rules cannot read that phrase, a local language model suggests an answer, and a person confirms it (the model never decides).
4. *What the answer changed:* customer not available 64% → 91%. Dallal now auto-sends the customer a WhatsApp (sandbox) to confirm availability, again within policy.
5. Replay and tap **Cannot find the address** instead: the decision becomes a *recommendation* that an operator confirms. The answer changes the action.

Proves: value-of-information questioning, choosing whom to ask, belief update from a reply, the model/rules/human split.

### C · Road blocked: coordinated recovery, manager approval

1. Click **C · Road blocked**. Salem, Nawaf and Majid queue behind a blockage on King Fahd Rd: 4 parcels delayed, 6 more exposed; the cards say *3 / 4 / 3 at risk*.
2. **Investigate with Dallal.** Dallal reads the records, finds **4 related failures on corridor DK-04 against a baseline of 0.4**, and stops treating them one by one: "One disruption is behind several delays".
3. It builds **one plan for 10 parcels on 3 drivers**, grouped by driver (wait, spare courier, pickup point), and asks the dispatcher **once**: one message instead of 20.
4. Tap **Blocked, expected > 30 min** on the simulated device. The plan changes for 5 of 10 parcels; the plan then says *Waiting for the manager* (an operator cannot approve it; the backend refuses).
5. Click **Manager** (top right). The manager sees why Dallal is asking, the evidence, the plan by driver, the value of planning together, and **Approve plan / Reject**.
6. Approve. Parcels move to spare couriers and pickup points (dashed links on the map), vans move through the managed lane, the ledger records the actions, and outcomes stay *pending* - nothing is claimed as delivered.

Proves: route-level impact, coordination across drivers, one shared question, and human approval where policy requires it.

## Recommended 60-90 second recording

| Time | Action | Say |
|---|---|---|
| 0:00 | Open Dallal. Show drivers, routes, map. | "A driver carries many parcels on one route. Dallal watches every route." |
| 0:08 | Click **A**, then **Investigate**. | "A delivery failed. Dallal checks the evidence, decides no question is worth asking, and fixes it itself - within safety limits." |
| 0:25 | Point at the six safety checks and the green parcel. | "No manager needed, and nothing is assumed: the outcome appears once the simulated world reports it." |
| 0:32 | Click **B**, **Investigate**. | "Here the records can't say why. Dallal asks the driver." |
| 0:45 | Tap the highlighted reply. | "The answer moves its belief from 64 to 91 percent and the action it takes." |
| 0:55 | Click **C**, **Investigate**. | "One blockage, three drivers. Dallal sees one incident and plans all ten parcels together." |
| 1:10 | Tap the dispatcher reply, switch to **Manager**, **Approve plan**. | "One question, not twenty. Group actions need a manager, and the backend enforces it." |
| 1:25 | Show the routes updated. | "Simulated execution; outcomes stay pending." |

Tips: use **Replay** to retake; resize the window to 1440x900 or larger; the basemap needs internet (without it the routes and parcels still show on a plain background); give the page two seconds after each start before clicking.

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
npm run demo:check       # backend-only traces of the same ideas (docs/demos/DEMO_TRACES.md)
```

## Other pages

`/models` is the **Model evidence** page: each trained risk model with its held-out metrics, calibration and feature contract, and a real-data replay (a real held-out LaDe delivery task through the live agent, scored by the model or an explicit abstention, with the real outcome revealed afterwards). It is linked from the idle panel.

## Troubleshooting

- Logs: `backend/.data/logs/{backend,frontend,ollama}.log`.
- *Backend offline* in the top bar: the backend is not on `:8000`; `npm run demo` again.
- A scenario looks different on replay: restart with `npm run demo:reset` (the backend must be the one launched by the script so the demo reset is allowed: it only works with `DALLAL_ENV=dev`, sandbox WhatsApp and simulated execution).
- The basemap is blank: the tile servers are slow or unreachable; routes, vans and parcels still work.
- Real-data replay needs the LaDe canonical tables under `backend/.data/canonical/lade` (`python -I -m dallal.data.cli build lade`).
