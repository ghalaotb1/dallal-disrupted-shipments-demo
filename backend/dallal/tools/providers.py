"""Swappable back-ends behind the tools.

Today: a transparent heuristic risk model and a SIMULATED action executor. Tomorrow: a trained model and real SPL service
clients implementing the same two methods. The agent and tools never import a concrete provider.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from dallal.tools import signals as sg
from dallal.tools.bundle import Bundle


@dataclass
class RiskScore:
    score: float  # 0..1
    drivers: list[dict[str, Any]]  # [{family, label, weight}] strongest first
    model_id: str
    basis: str  # "prototype-heuristic" | "trained:<artifact id>"
    band: str | None = None  # low | elevated | high, relative to the model's own calibrated base rate; derived from score if absent
    probability: float | None = None  # calibrated probability of the model's target, only for trained+calibrated models
    meta: dict | None = None  # target definition, domain caveats, applicability


class RiskModel(Protocol):
    def score(self, world: Bundle, shipment_id: str, facts: dict[str, Any]) -> RiskScore: ...


class HeuristicRiskModel:
    """Noisy-OR over transparent operational signals. NOT a trained model and never presented as one.

    A trained gradient-boosted model (see docs/ml/TASKS.md) replaces this by implementing `RiskModel.score`; the
    `predict_risk` tool and the agent do not change.
    """

    model_id = "heuristic-noisy-or-v1"
    basis = "prototype-heuristic"

    def score(self, world: Bundle, shipment_id: str, facts: dict[str, Any]) -> RiskScore:
        parts: list[tuple[str, str, float]] = []
        a = sg.address_signals(world, shipment_id)
        if a["weak"]:
            parts.append(("address", f"address confidence {a['confidence']:.2f}" if a["confidence"] is not None else "weak address history",
                          min(0.9, 0.25 + 0.6 * max(0.0, 0.8 - (a["confidence"] or 0.8)) + 0.1 * min(a["past_failures"], 3))))
        r = sg.recipient_signals(world, shipment_id)
        if r["missed"]:
            parts.append(("recipient", f"{r['missed_windows']} missed delivery window(s)", min(0.5, 0.15 * max(1, r["missed_windows"]) + 0.1)))
        j = sg.journey_signals(world, shipment_id)
        rt = sg.route_signals(world, shipment_id, facts)
        if rt["corridor_ratio"] is not None and rt["corridor_ratio"] < sg.SLOW_RATIO:
            p = 0.30 if rt["corridor_ratio"] >= sg.BLOCKED_RATIO else 0.45
            if rt["stationary_min"] >= sg.STATIONARY_MIN_FLAG:
                p += 0.2
            parts.append(("route", f"corridor at {rt['corridor_ratio']:.0%} of typical speed", p))
        f = sg.facility_signals(world, facts)
        if f.get("backlog"):
            parts.append(("facility", f"branch backlog {f['backlog_parcels']} parcels", 0.40))
        if f.get("scan_gap"):
            parts.append(("facility", f"no scan for {f['gap_hours']:.1f} h at branch", 0.40))
        if j["stalled"]:
            parts.append(("facility", f"no scan for {j['hours_since_scan']:.1f} h", 0.35))
        pk = sg.pickup_signals(world, facts)
        if pk["offline"]:
            parts.append(("pickup", "assigned pickup point offline", 0.50))
        if j["sequence_conflict"]:
            parts.append(("custody", j["conflict_detail"] or "conflicting custody scans", 0.60))
        if facts.get("recorded_code"):
            parts.append(("code", f"recorded exception {facts['recorded_code']}", 0.25))
        prod = 1.0
        for _, _, p in parts:
            prod *= 1 - p
        parts.sort(key=lambda x: -x[2])
        drivers = [{"family": fam, "label": lab, "weight": round(p, 3)} for fam, lab, p in parts[:5]]
        return RiskScore(score=round(1 - prod, 4), drivers=drivers, model_id=self.model_id, basis=self.basis)


@dataclass
class ExecResult:
    status: str  # "simulated_ok"
    detail: str
    external_effect: bool = False


class ActionExecutor(Protocol):
    def execute(self, tool: str, subject_id: str, params: dict[str, Any]) -> ExecResult: ...


@dataclass
class SimulatedExecutor:
    """Records what a real executor WOULD do. No message is sent, nothing leaves the process, and no outcome is invented."""

    log: list[dict[str, Any]] = field(default_factory=list)

    def execute(self, tool: str, subject_id: str, params: dict[str, Any]) -> ExecResult:
        self.log.append({"tool": tool, "subject_id": subject_id, "params": params})
        return ExecResult("simulated_ok", f"[simulated] {tool} for {subject_id}")


@dataclass
class DefaultProviders:
    risk: RiskModel = field(default_factory=HeuristicRiskModel)
    executor: ActionExecutor = field(default_factory=SimulatedExecutor)
