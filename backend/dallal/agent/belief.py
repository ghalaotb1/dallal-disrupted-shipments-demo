"""Belief state of the Dallal agent: a joint distribution over (root cause C, systemic flag S).

C is the single most likely root cause of the shipment's problem (or NONE when healthy). S says whether this shipment is
one symptom of a wider operational incident. Each investigative tool declares an *observation model* P(outcome | C, S).
The agent updates its belief with Bayes' rule when a tool returns an outcome, and chooses the next tool by exact expected
information gain (entropy reduction) per unit cost.

HONESTY NOTE — every probability table below is an EXPERT ASSUMPTION (`MODEL_BASIS`), not a fitted model. No public
dataset labels shipment root causes, so these cannot be learned from public data. They are explicit, versioned, tested for
internal consistency, and designed to be re-estimated from SPL exception/outcome logs. The agent's *machinery* (belief
update, EVOI planning, gating) is real and independent of the table values; the table values determine only how much
a given observation shifts the belief.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

MODEL_BASIS = "expert_assumption_v1"


class Cause(StrEnum):
    NONE = "none"
    ADDRESS_ISSUE = "address_issue"
    RECIPIENT_UNAVAILABLE = "recipient_unavailable"
    ATTEMPT_NOT_COMPLETED = "attempt_not_completed"
    ROUTE_DISRUPTION = "route_disruption"
    FACILITY_BACKLOG = "facility_backlog"
    PICKUP_POINT_UNAVAILABLE = "pickup_point_unavailable"
    CUSTODY_ANOMALY = "custody_anomaly"
    UNKNOWN = "unknown"


CAUSES: tuple[Cause, ...] = tuple(Cause)
CI = {c: i for i, c in enumerate(CAUSES)}

# P(S=1 | C): chance that a shipment with this cause is part of a wider incident.
P_SYSTEMIC_GIVEN_CAUSE = {
    Cause.NONE: 0.01, Cause.ADDRESS_ISSUE: 0.02, Cause.RECIPIENT_UNAVAILABLE: 0.02, Cause.ATTEMPT_NOT_COMPLETED: 0.05,
    Cause.ROUTE_DISRUPTION: 0.45, Cause.FACILITY_BACKLOG: 0.45, Cause.PICKUP_POINT_UNAVAILABLE: 0.30,
    Cause.CUSTODY_ANOMALY: 0.05, Cause.UNKNOWN: 0.10,
}

BASE_PRIOR = {
    Cause.NONE: 0.55, Cause.ADDRESS_ISSUE: 0.08, Cause.RECIPIENT_UNAVAILABLE: 0.10, Cause.ATTEMPT_NOT_COMPLETED: 0.04,
    Cause.ROUTE_DISRUPTION: 0.07, Cause.FACILITY_BACKLOG: 0.05, Cause.PICKUP_POINT_UNAVAILABLE: 0.02,
    Cause.CUSTODY_ANOMALY: 0.02, Cause.UNKNOWN: 0.07,
}

# What the human-recorded exception code suggests. Codes are known to be unreliable, so they are evidence, not truth.
CODE_TO_CAUSE = {
    "RECIPIENT_NOT_AVAILABLE": Cause.RECIPIENT_UNAVAILABLE, "ADDRESS_INCORRECT": Cause.ADDRESS_ISSUE,
    "ADDRESS_INCOMPLETE": Cause.ADDRESS_ISSUE, "PICKUP_POINT_CLOSED": Cause.PICKUP_POINT_UNAVAILABLE,
    "ROUTE_BLOCKED": Cause.ROUTE_DISRUPTION, "TRAFFIC_DELAY": Cause.ROUTE_DISRUPTION, "NO_SCAN": Cause.FACILITY_BACKLOG,
    "BRANCH_BACKLOG": Cause.FACILITY_BACKLOG, "DELIVERED_SCAN_CONFLICT": Cause.CUSTODY_ANOMALY,
}
RECORDED_CODE_BOOST = 4.0  # multiplicative prior boost for the cause a recorded code points at


def _row(**kw: float) -> dict[Cause, float]:
    return {Cause(k): v for k, v in kw.items()}


@dataclass(frozen=True)
class ObservationModel:
    """P(outcome | C, S) = normalise_o( by_cause[C][o] * by_systemic[S][o] )."""

    outcomes: tuple[str, ...]
    by_cause: dict[Cause, tuple[float, ...]] | None = None
    by_systemic: tuple[tuple[float, ...], tuple[float, ...]] | None = None
    # Correlation discount in (0, 1]: likelihoods are raised to this power before renormalising. Used for aggregate
    # signals (the risk score) that re-read evidence other tools also read, so they are not counted as independent.
    temper: float = 1.0

    def matrix(self) -> np.ndarray:
        """Return L[o, c, s]."""
        n = len(self.outcomes)
        L = np.ones((n, len(CAUSES), 2))
        if self.by_cause:
            for c, row in self.by_cause.items():
                r = np.array(row, dtype=float)
                L[:, CI[c], :] *= (r / r.sum())[:, None]
        if self.by_systemic:
            for s in (0, 1):
                r = np.array(self.by_systemic[s], dtype=float)
                L[:, :, s] *= (r / r.sum())[:, None]
        L = L ** self.temper
        L /= L.sum(axis=0, keepdims=True)
        return L


def _bc(**rows: tuple[float, ...]) -> dict[Cause, tuple[float, ...]]:
    return {Cause(k): v for k, v in rows.items()}


# Catch-all rule: `unknown` rows follow the background base rates of each outcome (rare outcomes stay rare under `unknown`).
# A flat row would make a rare, specific signal (e.g. a custody sequence conflict) look just as plausible under "unknown".
# Each tuple lists P(outcome | cause) in the order of `outcomes`. Rows need not sum to 1 (they are renormalised across
# outcomes per (C,S)); tests assert every outcome is possible under every cause (no hard zeros => no impossible beliefs).
OBSERVATION_MODELS: dict[str, ObservationModel] = {
    "get_journey": ObservationModel(
        ("clean", "failed_attempt_logged", "stalled", "sequence_conflict"),
        _bc(none=(.85, .04, .08, .03), address_issue=(.35, .55, .08, .02), recipient_unavailable=(.30, .62, .06, .02),
            attempt_not_completed=(.10, .70, .15, .05), route_disruption=(.35, .20, .43, .02),
            facility_backlog=(.20, .05, .72, .03), pickup_point_unavailable=(.40, .25, .30, .05),
            custody_anomaly=(.05, .15, .10, .70), unknown=(.40, .30, .25, .05)),
    ),
    "get_address_context": ObservationModel(
        ("address_ok", "address_weak"),
        _bc(none=(.90, .10), address_issue=(.08, .92), recipient_unavailable=(.85, .15), attempt_not_completed=(.88, .12),
            route_disruption=(.92, .08), facility_backlog=(.92, .08), pickup_point_unavailable=(.90, .10),
            custody_anomaly=(.90, .10), unknown=(.75, .25)),
    ),
    "get_recipient_context": ObservationModel(
        ("no_signal", "history_of_missed_windows", "window_conflict"),
        _bc(none=(.93, .05, .02), address_issue=(.85, .12, .03), recipient_unavailable=(.15, .75, .10),
            attempt_not_completed=(.35, .10, .55), route_disruption=(.85, .07, .08), facility_backlog=(.90, .05, .05),
            pickup_point_unavailable=(.80, .10, .10), custody_anomaly=(.55, .10, .35), unknown=(.60, .25, .15)),
    ),
    "get_route_context": ObservationModel(
        ("normal", "corridor_slow", "blocked_stationary", "attempt_geo_mismatch"),
        _bc(none=(.93, .04, .02, .01), address_issue=(.85, .05, .02, .08), recipient_unavailable=(.90, .04, .01, .05),
            attempt_not_completed=(.20, .10, .10, .60), route_disruption=(.12, .30, .55, .03),
            facility_backlog=(.85, .08, .02, .05), pickup_point_unavailable=(.85, .07, .02, .06),
            custody_anomaly=(.50, .05, .05, .40), unknown=(.60, .15, .15, .10)),
    ),
    "get_facility_context": ObservationModel(
        ("normal", "backlog", "scan_gap"),
        _bc(none=(.95, .03, .02), address_issue=(.93, .04, .03), recipient_unavailable=(.94, .03, .03),
            attempt_not_completed=(.90, .05, .05), route_disruption=(.85, .08, .07), facility_backlog=(.05, .55, .40),
            pickup_point_unavailable=(.80, .10, .10), custody_anomaly=(.70, .10, .20), unknown=(.65, .20, .15)),
    ),
    "get_pickup_context": ObservationModel(
        ("online", "offline"),
        _bc(none=(.97, .03), address_issue=(.97, .03), recipient_unavailable=(.97, .03), attempt_not_completed=(.97, .03),
            route_disruption=(.96, .04), facility_backlog=(.96, .04), pickup_point_unavailable=(.05, .95),
            custody_anomaly=(.96, .04), unknown=(.85, .15)),
    ),
    "predict_risk": ObservationModel(
        ("low", "generic_high", "driver_address", "driver_recipient", "driver_route", "driver_facility", "driver_custody", "driver_pickup"),
        _bc(none=(.76, .08, .03, .03, .03, .03, .02, .02), address_issue=(.15, .15, .55, .05, .04, .03, .02, .01),
            recipient_unavailable=(.15, .15, .04, .55, .04, .03, .02, .02), attempt_not_completed=(.15, .35, .05, .10, .10, .05, .15, .05),
            route_disruption=(.15, .15, .03, .03, .55, .05, .02, .02), facility_backlog=(.15, .15, .03, .03, .06, .55, .02, .01),
            pickup_point_unavailable=(.15, .15, .03, .03, .03, .03, .02, .56), custody_anomaly=(.15, .20, .03, .03, .04, .06, .45, .04),
            unknown=(.25, .40, .05, .06, .06, .06, .06, .06)),
        temper=0.6,  # aggregate score re-reads signals other tools read: discount to avoid double counting
    ),
    "check_incident_context": ObservationModel(
        ("no_cluster", "subthreshold_cluster", "incident_confirmed"),
        by_systemic=((.85, .14, .01), (.05, .20, .75)),
    ),
}

# Relative cost of running each information tool (latency / system load). Tuned so cheap model inference goes first
# only when it is actually informative.
TOOL_COST = {
    "get_journey": 1.0, "get_address_context": 1.0, "get_recipient_context": 1.0, "get_route_context": 1.5,
    "get_facility_context": 1.0, "get_pickup_context": 0.5, "predict_risk": 0.5, "check_incident_context": 1.5,
}


def entropy_bits(p: np.ndarray) -> float:
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum())


@dataclass
class Belief:
    joint: np.ndarray = field(default_factory=lambda: np.full((len(CAUSES), 2), 1 / (2 * len(CAUSES))))
    history: list[dict] = field(default_factory=list)

    @classmethod
    def from_prior(cls, p_cause: dict[Cause, float]) -> Belief:
        pc = np.array([p_cause[c] for c in CAUSES], dtype=float)
        pc /= pc.sum()
        ps1 = np.array([P_SYSTEMIC_GIVEN_CAUSE[c] for c in CAUSES])
        joint = np.stack([pc * (1 - ps1), pc * ps1], axis=1)
        return cls(joint=joint)

    # ── marginals ──
    def p_cause(self) -> dict[Cause, float]:
        m = self.joint.sum(axis=1)
        return {c: float(m[i]) for i, c in enumerate(CAUSES)}

    def p_systemic(self) -> float:
        return float(self.joint[:, 1].sum())

    def top(self) -> tuple[Cause, float, float]:
        """(most likely cause, its probability, margin over the runner-up)."""
        pc = sorted(self.p_cause().items(), key=lambda kv: -kv[1])
        return pc[0][0], pc[0][1], pc[0][1] - pc[1][1]

    def entropy(self) -> float:
        return entropy_bits(self.joint.ravel())

    # ── inference ──
    def update(self, tool: str, outcome: str) -> None:
        model = OBSERVATION_MODELS[tool]
        o = model.outcomes.index(outcome)
        before = self.snapshot()
        self.joint = self.joint * model.matrix()[o]
        self.joint /= self.joint.sum()
        self.history.append({"tool": tool, "outcome": outcome, "before": before, "after": self.snapshot()})

    def predictive(self, tool: str) -> np.ndarray:
        L = OBSERVATION_MODELS[tool].matrix()
        return np.einsum("ocs,cs->o", L, self.joint)

    def expected_information_gain(self, tool: str) -> float:
        """H(C,S) - E_o[ H(C,S | o) ] in bits — exact enumeration over the tool's outcomes."""
        L = OBSERVATION_MODELS[tool].matrix()
        h0 = self.entropy()
        exp_h = 0.0
        for o in range(L.shape[0]):
            w = L[o] * self.joint
            po = w.sum()
            if po > 0:
                exp_h += po * entropy_bits((w / po).ravel())
        return max(0.0, h0 - exp_h)

    def decision_class(self) -> tuple[str, str]:
        """Coarse class of what the agent would do from this belief alone: (incident status, case status).

        Used for decision-theoretic stopping: another tool is only worth calling if it could plausibly change this class.
        Thresholds mirror policy.py / actions.yaml limits.
        """
        top, p, margin = self.top()
        ps = self.p_systemic()
        inc = "incident" if ps >= 0.7 else "maybe_incident" if ps >= 0.25 else "no_incident"
        if top == Cause.NONE and p >= 0.8:
            case = "healthy"
        elif top in (Cause.UNKNOWN, Cause.CUSTODY_ANOMALY, Cause.NONE) or p < 0.55 or margin < 0.15:
            case = "escalate"
        elif p >= 0.8:
            case = "act_auto"
        else:
            case = "act_review"
        return inc, case

    def p_decision_change(self, tool: str) -> float:
        """Probability that observing `tool` moves the belief into a different decision class."""
        L = OBSERVATION_MODELS[tool].matrix()
        cur = self.decision_class()
        total = 0.0
        for o in range(L.shape[0]):
            w = L[o] * self.joint
            po = float(w.sum())
            if po <= 0:
                continue
            nxt = Belief(joint=w / po)
            if nxt.decision_class() != cur:
                total += po
        return total

    def snapshot(self) -> dict:
        pc = self.p_cause()
        top = sorted(pc.items(), key=lambda kv: -kv[1])[:4]
        return {"top": [(c.value, round(p, 4)) for c, p in top], "p_systemic": round(self.p_systemic(), 4),
                "entropy_bits": round(self.entropy(), 4)}


def check_models() -> None:
    """Internal-consistency assertions run by the tests."""
    for name, m in OBSERVATION_MODELS.items():
        L = m.matrix()
        assert np.allclose(L.sum(axis=0), 1.0), name
        assert (L > 0).all(), f"{name} has an impossible outcome under some (C,S)"
        if m.by_cause:
            assert set(m.by_cause) == set(CAUSES), f"{name} missing causes"
            assert all(len(r) == len(m.outcomes) for r in m.by_cause.values()), name
    assert math.isclose(sum(BASE_PRIOR.values()), 1.0)
