"""Tool framework: typed specs the planner reasons over, results the runtime consumes, providers that can be swapped.

A tool never *invents* facts. It reads the case world (canonical tables) or calls a provider (risk model, address
validator, executor) and returns structured facts plus — for information tools — a discrete `outcome` that the runtime
feeds into the agent's Bayesian belief.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from dallal.agent.state import CaseState

Status = Literal["ok", "warn", "alert"]
Kind = Literal["read", "analysis", "action"]


@dataclass
class ToolResult:
    status: Status
    summary: str
    facts: list[str] = field(default_factory=list)
    outcome: str | None = None  # discrete signal for belief update (information tools only)
    data: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)


class Providers(Protocol):
    """Swappable back-ends. Defaults live in dallal.tools.providers; production versions implement the same methods."""

    risk: Any
    executor: Any


@dataclass
class ToolContext:
    world: Any  # dallal.tools.bundle.Bundle (or any object with the same query surface)
    state: CaseState
    providers: Providers


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    kind: Kind
    input_schema: dict[str, Any]
    fn: Callable[[ToolContext, dict[str, Any]], ToolResult]
    cost: float = 1.0
    informative: bool = False  # has an ObservationModel -> planned by expected information gain
    requires: Callable[[CaseState], bool] = lambda s: True
    requires_doc: str = "none"  # human-readable precondition, shown to the planner / LLM
    side_effect: Literal["none", "simulated", "external"] = "none"

    def to_anthropic(self) -> dict[str, Any]:
        """Tool definition in Anthropic tool-use format."""
        return {"name": self.name, "description": f"{self.description} [precondition: {self.requires_doc}]",
                "input_schema": self.input_schema}


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]):
        self._specs = {s.name: s for s in specs}

    def __getitem__(self, name: str) -> ToolSpec:
        return self._specs[name]

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def all(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def eligible(self, state: CaseState, *, informative_only: bool = False) -> list[ToolSpec]:
        out = []
        for s in self._specs.values():
            if s.name in state.called or (informative_only and not s.informative):
                continue
            if s.requires(state):
                out.append(s)
        return out
