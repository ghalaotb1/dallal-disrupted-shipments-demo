# Dallal backend

Data foundation, ML baselines and the agent for Dallal (دلّال). Python ≥ 3.11. Full documentation lives in [`../docs`](../docs):
[dataset report](../docs/data/DATASET_DECISION_REPORT.md) · [schema](../docs/data/CANONICAL_SCHEMA.md) · [augmentation](../docs/data/AUGMENTATION.md) ·
[ML tasks + baselines](../docs/ml/TASKS_AND_BASELINES.md) · [agent architecture](../docs/architecture/AGENT_ARCHITECTURE.md) · [eval traces](../docs/architecture/EVAL_TRACES.md)

```bash
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"          # add ,llm for the Anthropic planner, ,api for FastAPI
python -I -m dallal.data.cli list                                            # audited datasets and decisions
python -I -m dallal.data.cli fetch selected --all                            # download + sha256-verify into .data/raw (git-ignored)
python -I -m dallal.data.cli verify lade amazon_lmrrc                        # compare with registry/datasets.lock.json
python -I -m dallal.data.cli build olist amazon_lmrrc lade route_deviation spl_open_data ocel_order_management labels
python -I -m dallal.data.eda                                                 # profile -> docs/data/eda_summary.json
python -W ignore -I -m dallal.ml.baselines                                   # -> docs/ml/baselines.json
python -W ignore -I -m dallal.ml.incident_backtest                           # -> docs/ml/incident_backtest.json
python -I -m pytest -q
python -I evals/run_cases.py && python -I evals/render_traces.py             # agent evaluation + traces
dallal-agent address_risk                                                    # one case; --frontend for the UI-shaped run; --llm for the Anthropic planner
```

* **Secrets:** none are stored. `ANTHROPIC_API_KEY` is read from the environment only, and only by `--llm`. The default planner is offline.
* **Data:** `.data/` is git-ignored. Downloaded files are treated as untrusted input (parsed, never executed); run Python with `-I` as above.
* **Licenses:** Amazon and Olist are non-commercial; see `registry/datasets.yaml` for each source's terms.
* **Layout:** `dallal/data` (registry, schema, adapters, labels, leakage, splits, augment) · `dallal/ml` (tasks, features, baselines, backtest) · `dallal/agent` (belief, planner, policy, runtime, ledger, trace, llm) · `dallal/tools` (specs, signals, providers, bundle) · `dallal/recovery` (action catalogue + ranking) · `evals/` · `tests/`.
