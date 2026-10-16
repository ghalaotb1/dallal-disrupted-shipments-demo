"""Structured, auditable run records. One JSON document per run + JSON-line logging of every step."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger("dallal.agent")


def _default(o: Any) -> Any:
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    if hasattr(o, "item"):
        return o.item()
    if isinstance(o, set):
        return sorted(o)
    return str(o)


@dataclass
class AgentRun:
    run_id: str
    subject_id: str
    scenario_id: str | None
    data_origin: str | None
    planner: str
    trigger: dict[str, Any]
    as_of: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    decision: dict[str, Any] = field(default_factory=dict)
    belief_trajectory: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    diagnosis: dict[str, Any] | None = None
    actions: list[dict[str, Any]] = field(default_factory=list)
    escalation: dict[str, Any] | None = None
    deviations: list[dict[str, Any]] = field(default_factory=list)  # LLM choices overridden by gates
    model_basis: str = "expert_assumption_v1"
    engine: str = "v1"
    status: str = "completed"  # completed | awaiting_response (v2 runs can pause for an answer)
    inquiries: list[dict[str, Any]] = field(default_factory=list)  # v2: every question asked, its channel mode and its outcome
    utility_table: list[dict[str, Any]] = field(default_factory=list)  # v2: expected utility of each option at the final belief
    virtual_minutes: float = 0.0  # v2: elapsed operational time (tool + answer latency)

    @property
    def tool_path(self) -> list[str]:
        return [s["tool"] for s in self.steps]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tool_path"] = self.tool_path
        return d

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, default=_default) + "\n")


def log_step(run_id: str, step: dict[str, Any]) -> None:
    log.info(json.dumps({"event": "tool_call", "run_id": run_id, **{k: step[k] for k in ("index", "tool", "status", "summary", "outcome")}}, default=_default))
