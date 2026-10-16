"""Action / decision / outcome ledger: the data contract for future learning.

Everything is written in the canonical `decision`, `action`, `outcome` table shapes (origin carried from the case). Fields
a causal/uplift learner needs and that this phase already logs:
  * `assignment`   how the action was chosen (rule / agent / human / randomized)
  * `propensity`   probability of the chosen action given context — REQUIRED when assignment == randomized
  * `context_snapshot_id` + `basis`  the belief and evidence the chooser saw, frozen at decision time (no hindsight)
  * `policy_id`    which policy version acted
  * `outcome`      initially `pending`; resolved later by real systems — this phase NEVER fabricates an outcome
Identification note: deterministic rule/agent assignment has no overlap between treated/untreated for a given context, so
effects are NOT identifiable from this log alone. A small randomised pilot on low-risk, reversible actions is the
recommended next step to make uplift modelling possible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from dallal.data.schema import Action, Decision, Outcome, validate_frame


@dataclass
class Ledger:
    origin: str  # carried from the case: "synthetic" | "demo" | "observed"
    scenario_id: str | None
    decisions: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    outcomes: list[dict[str, Any]] = field(default_factory=list)

    def _prov(self, key: str) -> dict[str, Any]:
        return {"origin": self.origin, "source_id": "dallal-agent", "source_record_id": key, "adapter_version": "ledger-1.0",
                "scenario_id": self.scenario_id, "generator_seed": None}

    def log_decision(self, run_id: str, subject_id: str, outcome_type: str, ts: pd.Timestamp, basis: dict, policy_version: str,
                     decided_by: str = "agent") -> str:
        did = f"dec:{run_id}"
        self.decisions.append({"decision_id": did, "run_id": run_id, "subject_type": "shipment", "subject_id": subject_id,
                               "decided_by": decided_by, "outcome_type": outcome_type, "ts": ts, "basis": basis,
                               "policy_version": policy_version, **self._prov(did)})
        return did

    def log_action(self, run_id: str, subject_id: str, kind: str, ts: pd.Timestamp, *, executed: bool, approval: str,
                   assignment: str = "agent", params: dict | None = None, snapshot: str | None = None) -> str:
        aid = f"act:{run_id}:{kind}"
        self.actions.append({"action_id": aid, "subject_type": "shipment", "subject_id": subject_id, "kind": kind, "proposed_ts": ts,
                             "executed_ts": ts if executed else pd.NaT, "assignment": assignment, "propensity": None,
                             "policy_id": "recovery-policy-v1", "approval_level": approval, "context_snapshot_id": snapshot,
                             "params": params, **self._prov(aid)})
        return aid

    def log_pending_outcome(self, action_id: str, decision_id: str | None, ts: pd.Timestamp) -> None:
        oid = f"out:{action_id}"
        self.outcomes.append({"outcome_id": oid, "action_id": action_id, "decision_id": decision_id, "observed_ts": pd.NaT,
                              "kind": "pending", "delay_minutes": None, "cost_sar": None, **self._prov(oid)})

    def frames(self) -> dict[str, pd.DataFrame]:
        out = {}
        for name, rows, model in (("decision", self.decisions, Decision), ("action", self.actions, Action), ("outcome", self.outcomes, Outcome)):
            df = pd.DataFrame(rows, columns=list(model.model_fields)) if rows else pd.DataFrame(columns=list(model.model_fields))
            if rows:
                validate_frame(name, df)
            out[name] = df
        return out

    def append_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            for name, rows in (("decision", self.decisions), ("action", self.actions), ("outcome", self.outcomes)):
                for r in rows:
                    fh.write(json.dumps({"table": name, **r}, default=str) + "\n")
