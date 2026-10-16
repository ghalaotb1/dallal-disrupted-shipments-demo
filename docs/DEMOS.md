# Local demonstration guide

Everything runs on one Apple-silicon laptop (tested on 16 GB): Next.js frontend, Python backend, three trained models, the agent, a **sandbox** WhatsApp channel, and (optionally) Qwen3.5-4B through Ollama. Nothing can message a real person (`WHATSAPP_MODE` is forced to `sandbox`) or execute a real operational action (executor is simulated). Shipments, couriers, recipients and roads in the operator UI are simulated; everything the backend returns is labelled `LIVE`, `SANDBOX`, `SIM` or `REAL DATA` accordingly.

## Start, reset, stop

```bash
cd backend && uv venv && uv pip install -e ".[dev,api,report]" && cd ..   # once
npm install                                                                  # once
ollama pull qwen3.5:4b                                                       # optional (3.3 GB); without it replies are read by rules only
npm run demo            # starts Ollama (if needed), backend :8000, frontend :3000, waits for health
npm run demo:reset      # same, after wiping the demo database (runs, inquiries, plans, ledger)
npm run demo:stop
npm run demo:check      # automated end-to-end check of the three demos below, prints the backend traces
```

Memory: the launcher starts Ollama with `OLLAMA_MAX_LOADED_MODELS=1` and a 10-minute keep-alive; Qwen3.5-4B needs ~3.6 GB. Do not load the 9B model at the same time as the browser + backend on a 16 GB machine unless nothing else is open. `--no-llm` skips Ollama entirely.

Top bar must read **Live backend** and **WA SANDBOX**. If it says **Simulated**, the backend is not reachable (the app keeps working on its in-browser prototype logic).

## Demo A - real-data replay with trained-model inference (`/models`)

1. Open `http://localhost:3000/models?demo=manual`. The **This deployment** card states what is real and what is simulated.
2. In **Real-data agent replay** click *Replay a real task*. A real held-out LaDe (Shanghai) delivery task, from the period after the model's training data, goes through the live agent 10 minutes after the courier accepted it.
3. You will see the agent's tool trace; `predict_risk` is tagged **MODEL** with the calibrated probability, the base rate and the *as-of time of the features* (workload and delivery history are read point-in-time). Click *Replay another real task* until one shows **heuristic - model abstained**: the reason is printed (e.g. a history feature outside the training range) and no risk claim is made.
4. Click *Reveal what actually happened* to see the real outcome recorded in the dataset.
5. Below, each trained model has its held-out metrics, calibration plot, feature contract and a *Score a case* form that refuses incomplete rows.

What this proves: a trained model is reachable through the agent's `RiskModel` interface with train/serve parity and no look-ahead (see `docs/EVALUATION_REPORT.md`, "Real-data model bridge"). What it does not: the models are not SPL models, and demo shipments (Saudi, synthetic) are refused by the domain gate and say so.

## Demo B - uncertain shipment: valuable inquiry, sandbox reply, belief update (`/shipments/DL-20764`)

1. Open `http://localhost:3000/shipments/DL-20764?demo=manual` and click *Investigate with agent*.
2. The agent reads seven database tools first, then asks the **courier** one question (net value of information shown). The WhatsApp card says *Recorded in sandbox - not sent to a phone*.
3. In **Simulated recipient device** answer with a button, or type Arabic free text such as `وصلت العنوان بس مافي احد يفتح`. Rules cannot read that dialect phrase; Qwen3.5-4B suggests *At address, nobody answered* (its own confidence is shown as uncalibrated) and a person clicks **Accept suggestion**.
4. The belief line updates (recipient unavailable ~74%), the policy refuses automation (parcel value above the autonomy bound), and the decision becomes *Recommended: contact the recipient* for an analyst to approve. Re-run and answer *Cannot find the address* instead: the agent escalates rather than guess. The answer changes the decision.
5. Approving records a **simulated** action in the ledger with outcome *pending*; Dallal never marks an unobserved recovery as successful.

## Demo C - shared incident: one question changes the plan for several shipments (`/incidents/INC-2417`)

1. Open `http://localhost:3000/incidents/INC-2417?demo=manual`, click *Advance demo to detection*.
2. In **Coordinated network recovery** tick *Tight promises (half the remaining window)* (a simulated operating assumption; with the world's generous promise windows the plan is already right for both outcomes, and the card says so) and click *Plan with the backend*.
3. One question goes to the dispatcher for all ten shipments (not ten questions). Answer *Blocked, > 30 min* on the simulated device. The card states exactly how many shipments' decisions changed (e.g. "3 of 10: wait to spare, spare to pickup, ...") and compares the coordinated plan with a naive per-shipment baseline.
4. An analyst cannot approve a network plan; a supervisor can. Approval executes it **in simulation**: each shipment's journey, the incident timeline, the ledger and notifications update consistently.

`npm run demo:check` replays these three flows against the API and writes the backend traces to `docs/demos/DEMO_TRACES.md`.

## Resetting and troubleshooting

* `npm run demo:reset` wipes `backend/.data/demo.sqlite`. The browser keeps its own simulated world: reload the page to restart it.
* Logs: `backend/.data/logs/{backend,frontend,ollama}.log`.
* Real-data replay needs the LaDe canonical tables under `backend/.data/canonical/lade` (built with `python -I -m dallal.data.cli build lade`); without them the panel says so.
