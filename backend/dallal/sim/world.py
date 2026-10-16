"""Generative evaluation world (SYNTHETIC, misspecified relative to the agent).

Why this exists: the earlier scenario suite was authored alongside the agent, so a high pass rate said little. Here a latent truth is
drawn first; every tool / inquiry then answers by sampling from TRUE likelihood tables that differ from the agent's assumed ones
(`sigma_true` multiplicative noise), plus silent data gaps and different true response rates / latencies. Interventions succeed with
TRUE probabilities (also perturbed). The agent therefore has to be robust to being wrong about its own model — and we can measure
decision quality against ground truth, not against an expectation I wrote.

What it is NOT: evidence about real SPL operations. Prevalences, effect sizes, costs and response behaviour are assumptions.
Results are labelled SYNTHETIC wherever reported.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from dallal.agent.belief import CAUSES, CI, OBSERVATION_MODELS, Cause
from dallal.agent.v2 import inquiry as iq
from dallal.agent.v2.bayes import RISK_BAND_MODEL
from dallal.agent.v2.events import InquiryResponse, InquiryTimeout
from dallal.recovery.ranking import load_catalogue
from dallal.tools.base import ToolRegistry, ToolResult, ToolSpec

# What operations see when the agent is called: a mix of true problems and false alarms.
EPISODE_CAUSE_MIX = {Cause.NONE: 0.22, Cause.ADDRESS_ISSUE: 0.17, Cause.RECIPIENT_UNAVAILABLE: 0.20, Cause.ATTEMPT_NOT_COMPLETED: 0.08,
                     Cause.ROUTE_DISRUPTION: 0.10, Cause.FACILITY_BACKLOG: 0.08, Cause.PICKUP_POINT_UNAVAILABLE: 0.05, Cause.CUSTODY_ANOMALY: 0.04, Cause.UNKNOWN: 0.06}
CAUSE_TO_CODE = {Cause.RECIPIENT_UNAVAILABLE: "RECIPIENT_NOT_AVAILABLE", Cause.ADDRESS_ISSUE: "ADDRESS_INCORRECT", Cause.ROUTE_DISRUPTION: "ROUTE_BLOCKED",
                 Cause.FACILITY_BACKLOG: "NO_SCAN", Cause.PICKUP_POINT_UNAVAILABLE: "PICKUP_POINT_CLOSED", Cause.CUSTODY_ANOMALY: "DELIVERED_SCAN_CONFLICT"}


def _perturb(L: np.ndarray, sigma: float, rng: np.random.Generator) -> np.ndarray:
    T = L * np.exp(rng.normal(0.0, sigma, L.shape))
    return T / T.sum(axis=0, keepdims=True)


@dataclass
class TrueModel:
    """One fixed 'true world' per experiment, IDENTICAL for every agent compared (all randomness is name-seeded and engine-independent)."""

    sigma_true: float = 0.5
    data_gap: float = 0.08  # chance a database tool silently returns its uninformative default
    seed: int = 1234
    tables: dict[str, np.ndarray] = field(default_factory=dict)
    effect_noise: np.ndarray | None = None
    resp_factor: dict[str, float] = field(default_factory=dict)
    lat_factor: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        models = dict(OBSERVATION_MODELS)
        models["predict_risk_band"] = RISK_BAND_MODEL  # v2 consumes calibrated bands; v1 keeps its driver-family model under "predict_risk"
        for n, m in models.items():
            self.tables[n] = _perturb(m.matrix(), self.sigma_true, np.random.default_rng([self.seed, 1, zlib.crc32(n.encode())]))
        for s in iq.all_specs():
            r = np.random.default_rng([self.seed, 3, zlib.crc32(s.id.encode())])
            self.resp_factor[s.id], self.lat_factor[s.id] = float(np.exp(r.normal(0, 0.25))), float(np.exp(r.normal(0, 0.25)))
        self.effect_noise = np.exp(np.random.default_rng([self.seed, 2]).normal(0, 0.2, size=len(CAUSES)))  # true effectiveness = assumed x noise per cause

    def inquiry_table(self, s: iq.InquirySpec, p_resp_assumed: float) -> np.ndarray:
        """True P(outcome | c, s) over answers + no_response (rebuilt from the assumed table, perturbed with the inquiry's own seed)."""
        rng = np.random.default_rng([self.seed, 4, zlib.crc32(s.id.encode())])
        m = iq.observation_model(s, min(0.97, p_resp_assumed * self.resp_factor[s.id]))
        return _perturb(m.matrix(), self.sigma_true * 0.8, rng)


@dataclass
class Episode:
    truth: Cause
    systemic: bool
    facts: dict[str, Any]
    preds: dict[str, bool]
    trigger: dict[str, Any]
    slack_min: float
    seed: int


def draw_episode(rng: np.random.Generator, *, systemic: bool = False, forced_cause: Cause | None = None, seed: int = 0) -> Episode:
    causes = list(EPISODE_CAUSE_MIX)
    cause = forced_cause or causes[rng.choice(len(causes), p=np.array([EPISODE_CAUSE_MIX[c] for c in causes]))]
    failed = int(rng.choice([0, 1, 2, 3], p=[0.35, 0.35, 0.20, 0.10])) if cause in (Cause.RECIPIENT_UNAVAILABLE, Cause.ADDRESS_ISSUE, Cause.ATTEMPT_NOT_COMPLETED) else 0
    value = float(np.exp(rng.normal(np.log(260), 0.9)))
    cod = value if rng.random() < 0.25 else None
    # The human-recorded code is informative but unreliable (30% wrong).
    code = None
    if cause != Cause.NONE and rng.random() < 0.75:
        code = CAUSE_TO_CODE.get(cause)
        if code is None or rng.random() < 0.30:
            code = str(rng.choice(list(CAUSE_TO_CODE.values())))
    trig = {"kind": "exception_recorded" if code else str(rng.choice(["risk_alert", "scheduled_scan"], p=[0.7, 0.3]))}
    resp = str(rng.choice(["high", "medium", "low"], p=[0.3, 0.5, 0.2]))
    has_pp = rng.random() < 0.5
    facts = {"shipment_id": f"SIM-{seed}", "service_level": str(rng.choice(["Standard", "Express", "Same-day"], p=[0.7, 0.2, 0.1])), "payment_type": "COD" if cod else "Prepaid",
             "cod_amount": cod, "value": value, "origin_node_id": "sim:hub", "courier_id": "sim:courier", "corridor_id": "SIM-C1", "pickup_point_id": "sim:pp" if has_pp else None,
             "alt_pickup_online": has_pp and rng.random() < 0.6, "alt_route_available": bool(rng.random() < 0.7), "spare_courier_available": bool(rng.random() < 0.7),
             "recorded_code": code, "failed_attempts": failed, "delivered": cause == Cause.CUSTODY_ANOMALY, "origin": "synthetic", "scenario_id": f"sim-episode-{seed}",
             "recipient_phone": "SANDBOX-SIM", "recipient_opt_in": bool(rng.random() < 0.85), "recipient_responsiveness": resp, "recipient_messages_24h": int(rng.random() < 0.15),
             "dispatcher_contactable": True, "branch_contactable": True, "courier_phone": True, "window_text": "14:00-18:00", "dest_lat": 26.3, "dest_lng": 50.2,
             "promised_end_ts": None}
    cat = load_catalogue()["actions"]
    preds = {"recipient_reachable": bool(facts["recipient_opt_in"]), "pickup_online": has_pp and rng.random() < 0.8, "alt_pickup_online": bool(facts["alt_pickup_online"]),
             "alt_route": bool(facts["alt_route_available"]), "spare_courier": bool(facts["spare_courier_available"])}
    _ = cat
    return Episode(cause, systemic, facts, preds, trig, float(rng.uniform(45, 480)), seed)


DEFAULT_AS_OF = pd.Timestamp("2026-03-10 14:00")


class SimEnv:
    """The 'world' the tools and the runtime see inside an episode."""

    def __init__(self, ep: Episode, tm: TrueModel, rng: np.random.Generator, engine: str = "v2", as_of: pd.Timestamp | None = None):
        as_of = as_of if as_of is not None else DEFAULT_AS_OF
        self.ep, self.tm, self.rng, self.as_of, self.engine = ep, tm, rng, as_of, engine
        ep.facts["promised_end_ts"] = as_of + pd.Timedelta(minutes=ep.slack_min)
        self.subject_id = ep.facts["shipment_id"]
        self.trigger = ep.trigger
        self.scenario_id = f"sim-episode-{ep.seed}"
        self.messages_sent = 0
        self.comm_cost = 0.0

    def action_predicates(self, facts: dict[str, Any]) -> dict[str, bool]:
        return self.ep.preds

    # ── tool channel ──
    def sample_tool(self, name: str) -> str:
        band = name == "predict_risk" and self.engine == "v2"
        T = self.tm.tables["predict_risk_band" if band else name]
        c, s = CI[self.ep.truth], int(self.ep.systemic)
        outs = (RISK_BAND_MODEL if band else OBSERVATION_MODELS[name]).outcomes
        if name != "check_incident_context" and self.rng.random() < self.tm.data_gap:
            return outs[0]  # silent data gap: the tool returns its uninformative default
        p = T[:, c, s]
        return outs[int(self.rng.choice(len(p), p=p / p.sum()))]

    # ── inquiry channel ──
    def answer(self, pend, spec: iq.InquirySpec, p_assumed: float) -> InquiryResponse | InquiryTimeout:
        c, s = CI[self.ep.truth], int(self.ep.systemic)
        self.messages_sent += 1
        self.comm_cost += spec.raw["cost"]["comm_sar"]
        T = self.tm.inquiry_table(spec, p_assumed)
        p = T[:, c, s]
        o = int(self.rng.choice(len(p), p=p / p.sum()))
        outs = spec.outcomes
        if outs[o] == iq.NO_RESPONSE:
            return InquiryTimeout(pend.inquiry_id)
        r = spec.raw["response"]
        lat = float(self.rng.lognormal(np.log(r["latency_median_min"] * self.tm.lat_factor[spec.id]), r["latency_sigma"]))
        if lat > r["timeout_min"]:
            return InquiryTimeout(pend.inquiry_id)
        return InquiryResponse(pend.inquiry_id, outs[o], lat, {"sim": True})

    # ── outcomes of decisions ──
    def true_success(self, option_success: np.ndarray) -> float:
        return float(np.clip(option_success[CI[self.ep.truth]] * self.tm.effect_noise[CI[self.ep.truth]], 0.0, 0.99))


def _sim_get_shipment(ctx, a):
    return ToolResult("ok", f"{ctx.world.subject_id} loaded", ["simulated"], data={"facts": dict(ctx.world.ep.facts)}, provenance={"data_origin": "synthetic"})


def _make_sim_tool(name: str, engine: str):
    def fn(ctx, a):
        o = ctx.world.sample_tool(name)
        data = {"risk": {"band": o, "score": 0.0, "level": o, "drivers": []}} if name == "predict_risk" and engine == "v2" else {}
        if name == "check_incident_context" and o == "incident_confirmed":
            ctx.state.incident = {"scope": "corridor", "scope_id": "SIM-C1", "observed": 4, "baseline_mean": 0.4, "baseline_std": 0.6, "z": 6.0, "members": [], "exposed": []}
        return ToolResult("ok", f"[sim] {name} -> {o}", [], outcome=o, data=data, provenance={"data_origin": "synthetic"})

    return fn


def sim_registry(base: ToolRegistry, engine: str) -> ToolRegistry:
    """Replace evidence-tool bodies by samplers over the simulated truth; keep specs, preconditions and decision tools."""
    specs = []
    for s in base.all():
        if s.name == "get_shipment":
            s = ToolSpec(s.name, s.description, s.kind, s.input_schema, _sim_get_shipment, s.cost, s.informative, s.requires, s.requires_doc)
        elif s.informative:
            s = ToolSpec(s.name, s.description, s.kind, s.input_schema, _make_sim_tool(s.name, engine), s.cost, s.informative, s.requires, s.requires_doc)
        specs.append(s)
    return ToolRegistry(specs)
