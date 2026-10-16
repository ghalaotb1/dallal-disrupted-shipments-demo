"""Mutable per-case agent state: what the agent knows, believes, has asked, and has decided so far."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from dallal.agent.belief import Belief, Cause


@dataclass
class Evidence:
    id: str
    label: str
    detail: str
    stance: str  # supports | contradicts | context
    source_tool: str
    cause: str | None = None


@dataclass
class ToolCall:
    index: int
    tool: str
    args: dict[str, Any]
    reason: str
    status: str = "ok"
    summary: str = ""
    facts: list[str] = field(default_factory=list)
    outcome: str | None = None
    belief_after: dict | None = None
    planner_table: list[dict] = field(default_factory=list)
    duration_ms: float = 0.0
    provenance: dict = field(default_factory=dict)


@dataclass
class CaseState:
    subject_id: str
    trigger: dict[str, Any]
    as_of: pd.Timestamp
    facts: dict[str, Any] | None = None  # filled by get_shipment
    belief: Belief | None = None
    calls: list[ToolCall] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    incident: dict[str, Any] | None = None  # set by check_incident_context when confirmed
    diagnosis: dict[str, Any] | None = None  # set by analyze_disruption
    ranked_actions: list[dict[str, Any]] = field(default_factory=list)
    policy: dict[str, Any] | None = None
    escalation: dict[str, Any] | None = None
    budget: int = 10

    @property
    def called(self) -> set[str]:
        return {c.tool for c in self.calls}

    def info_calls(self) -> int:
        """Number of information-gathering calls so far (the quantity the investigation budget bounds)."""
        return sum(1 for c in self.calls if c.outcome is not None)

    def outcomes(self) -> dict[str, str]:
        return {c.tool: c.outcome for c in self.calls if c.outcome}

    def top_cause(self) -> tuple[Cause, float, float]:
        assert self.belief is not None
        return self.belief.top()

    def add_evidence(self, tool: str, label: str, detail: str, stance: str, cause: str | None = None) -> None:
        self.evidence.append(Evidence(f"ev{len(self.evidence) + 1}", label, detail, stance, tool, cause))
