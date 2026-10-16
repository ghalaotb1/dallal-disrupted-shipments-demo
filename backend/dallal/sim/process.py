"""Process world (SYNTHETIC, independent of the agent): hidden physical state -> the signals real tools would read -> stochastic outcomes.

Why a second simulator. `dallal.sim.world` perturbs the agent's OWN likelihood tables, so the truth is a noisy copy of what the agent believes - useful
for robustness, weak as evidence. Here nothing is derived from the agent's tables or from utility.yaml:
  * each episode draws a latent cause, then CONTINUOUS hidden variables (hours since scan, address confidence, corridor speed ratio, stationary minutes,
    distance of the stop from the address, backlog size, ...) from cause-conditional distributions chosen independently and deliberately overlapping;
  * tools read those variables through the SAME thresholds the real tool code uses (stall 4 h, slow < 0.6, stationary >= 15 min ...), so tool outcomes are
    emergent and their likelihoods are NOT the tables the agent assumes;
  * people answer from the hidden state with their own reliability (and can be wrong, silent, or slow);
  * actions work with their own true success probabilities (a different table than the agent's `suitability`) and take lognormal time;
  * outcomes are REALISED (Bernoulli draws with common random numbers shared by every agent on the same episode), not expected values.
Environment knobs (`ProcessConfig`) move uncertainty, response behaviour, deadlines, evidence corruption, prior shift and the environment's own utility scale.
Everything is an assumption about a hypothetical operation: results are comparisons between decision systems, never forecasts of real performance.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from dallal.agent.belief import OBSERVATION_MODELS, Cause
from dallal.agent.v2 import inquiry as iq
from dallal.agent.v2.bayes import RISK_BAND_MODEL
from dallal.agent.v2.events import InquiryResponse, InquiryTimeout
from dallal.recovery.ranking import load_catalogue
from dallal.sim.world import Episode, SimEnv, TrueModel, draw_episode

C = Cause
MIX = {C.NONE: 0.20, C.ADDRESS_ISSUE: 0.15, C.RECIPIENT_UNAVAILABLE: 0.20, C.ATTEMPT_NOT_COMPLETED: 0.08, C.ROUTE_DISRUPTION: 0.12, C.FACILITY_BACKLOG: 0.09,
       C.PICKUP_POINT_UNAVAILABLE: 0.05, C.CUSTODY_ANOMALY: 0.05, C.UNKNOWN: 0.06}

# TRUE probability that an action works for a cause (independent of utility.yaml / actions.yaml `suitability`). Unlisted pairs: 0.04.
TRUE_P: dict[str, dict[Cause, float]] = {
    "verify_address": {C.ADDRESS_ISSUE: 0.80, C.RECIPIENT_UNAVAILABLE: 0.12}, "contact_recipient": {C.RECIPIENT_UNAVAILABLE: 0.70, C.ATTEMPT_NOT_COMPLETED: 0.35},
    "offer_window": {C.RECIPIENT_UNAVAILABLE: 0.65, C.ATTEMPT_NOT_COMPLETED: 0.50, C.ADDRESS_ISSUE: 0.15}, "retry_delivery": {C.ATTEMPT_NOT_COMPLETED: 0.60, C.RECIPIENT_UNAVAILABLE: 0.45},
    "redirect_pickup": {C.RECIPIENT_UNAVAILABLE: 0.55, C.ADDRESS_ISSUE: 0.35}, "reroute": {C.ROUTE_DISRUPTION: 0.80}, "reassign_courier": {C.ROUTE_DISRUPTION: 0.55, C.ATTEMPT_NOT_COMPLETED: 0.60},
    "branch_escalation": {C.FACILITY_BACKLOG: 0.75, C.CUSTODY_ANOMALY: 0.20}, "redirect_locker": {C.PICKUP_POINT_UNAVAILABLE: 0.70}, "correct_exception": {C.CUSTODY_ANOMALY: 0.10}}
WAIT_P = {C.NONE: 0.93, C.ADDRESS_ISSUE: 0.08, C.RECIPIENT_UNAVAILABLE: 0.30, C.ATTEMPT_NOT_COMPLETED: 0.15, C.ROUTE_DISRUPTION: 0.50, C.FACILITY_BACKLOG: 0.35,
          C.PICKUP_POINT_UNAVAILABLE: 0.20, C.CUSTODY_ANOMALY: 0.03, C.UNKNOWN: 0.20}
HEALTHY_ACTION_P = 0.95
APPROVAL_MIN = {"none": 1.0, "analyst": 10.0, "supervisor": 20.0}
ACTION_COST = {"verify_address": 3, "contact_recipient": 3, "offer_window": 4, "retry_delivery": 30, "redirect_pickup": 35, "reroute": 18, "reassign_courier": 70, "branch_escalation": 6,
               "redirect_locker": 35, "correct_exception": 4}


@dataclass
class ProcessConfig:
    """Environment knobs. Defaults are the 'baseline' regime; every field is an assumption about the hypothetical operation."""

    name: str = "baseline"
    data_gap: float = 0.06  # a database tool silently returns its uninformative default
    signal_noise: float = 1.0  # >1 blurs the cause-conditional distributions toward each other (higher uncertainty); <1 sharpens them
    prior_shift: dict[Cause, float] = field(default_factory=dict)  # multiplicative change of the cause mix (distribution shift)
    slack_scale: float = 1.0  # deadlines: <1 urgent, >1 flexible
    p_resp_scale: float = 1.0  # response probability of people
    latency_scale: float = 1.0  # delay of answers
    answer_noise: float = 0.12  # probability that a responder's answer is wrong / contradicts the truth
    tool_outage: tuple[str, ...] = ()  # tools that always return their uninformative default (unseen failure mode)
    unseen_behaviour: bool = False  # cause-conditional behaviour the agent never modelled: recipients away but address weak, couriers re-report stale statuses
    util_scale: float = 1.0  # multiplies the environment's value/fail stakes (sensitivity)
    action_scale: float = 1.0  # multiplies TRUE action success (sensitivity)
    comm_scale: float = 1.0  # multiplies the true cost/friction of a message (sensitivity)
    systemic_share: float = 0.0  # fraction of episodes that belong to a shared-cause incident (corridor failures high)
    shared_fault_prob: float = 0.0  # per episode and evidence family: a common-mode fault (stale feed) makes every tool of the family report the same misleading outcome (correlated errors)


def regime_set() -> dict[str, ProcessConfig]:
    return {
        "baseline": ProcessConfig("baseline"),
        "low_uncertainty": ProcessConfig("low_uncertainty", data_gap=0.0, signal_noise=0.55),
        "high_uncertainty": ProcessConfig("high_uncertainty", data_gap=0.22, signal_noise=1.7),
        "urgent_deadlines": ProcessConfig("urgent_deadlines", slack_scale=0.35),
        "flexible_deadlines": ProcessConfig("flexible_deadlines", slack_scale=2.5),
        "missing_or_delayed_responses": ProcessConfig("missing_or_delayed_responses", p_resp_scale=0.35, latency_scale=3.0),
        "contradictory_evidence": ProcessConfig("contradictory_evidence", answer_noise=0.40),
        "prior_shift_route_heavy": ProcessConfig("prior_shift_route_heavy", prior_shift={C.ROUTE_DISRUPTION: 3.5, C.FACILITY_BACKLOG: 2.0, C.NONE: 0.6}),
        "unseen_behaviour_and_outage": ProcessConfig("unseen_behaviour_and_outage", unseen_behaviour=True, tool_outage=("get_route_context", "get_journey")),
        "systemic_incidents": ProcessConfig("systemic_incidents", systemic_share=0.5),
        "correlated_evidence": ProcessConfig("correlated_evidence", shared_fault_prob=0.30),
    }


# ── hidden state ────────────────────────────────────────────────────────────────────────────────────────────────────────
def _mix(cfg: ProcessConfig) -> tuple[list[Cause], np.ndarray]:
    causes = list(MIX)
    p = np.array([MIX[c] * cfg.prior_shift.get(c, 1.0) for c in causes])
    return causes, p / p.sum()


def _blur(x: float, centre: float, k: float) -> float:
    """Pull a value toward a neutral centre (k>1: more overlap between causes) or push it away (k<1)."""
    return centre + (x - centre) * (1.0 / k)


@dataclass
class Hidden:
    hours_since_scan: float
    failed_logged: int
    seq_conflict: bool
    addr_conf: float
    missed_windows: int
    window_conflict: bool
    corridor_ratio: float
    stationary_min: float
    dist_to_addr_m: float
    geo_mismatch: bool
    backlog: float
    gap_h: float
    pickup_offline: bool
    corridor_failures: int
    risk_score: float


def draw_hidden(rng: np.random.Generator, cause: Cause, systemic: bool, cfg: ProcessConfig) -> Hidden:
    k = cfg.signal_noise
    mu_hours = {C.NONE: 0.2, C.ADDRESS_ISSUE: 0.3, C.RECIPIENT_UNAVAILABLE: 0.3, C.ATTEMPT_NOT_COMPLETED: 0.5, C.ROUTE_DISRUPTION: 1.1, C.FACILITY_BACKLOG: 2.0, C.PICKUP_POINT_UNAVAILABLE: 0.8,
                C.CUSTODY_ANOMALY: 0.9, C.UNKNOWN: 1.0}[cause]
    hours = float(rng.lognormal(_blur(mu_hours, 0.8, k), 0.6 * min(k, 1.4)))
    lam_fail = {C.NONE: .05, C.ADDRESS_ISSUE: 1.0, C.RECIPIENT_UNAVAILABLE: 1.2, C.ATTEMPT_NOT_COMPLETED: 1.5, C.ROUTE_DISRUPTION: .15, C.FACILITY_BACKLOG: .1, C.PICKUP_POINT_UNAVAILABLE: .5,
                C.CUSTODY_ANOMALY: .4, C.UNKNOWN: .5}[cause]
    failed = int(rng.poisson(max(_blur(lam_fail, 0.5, k), 0.01)))
    seq_conflict = bool(rng.random() < (0.55 if cause == C.CUSTODY_ANOMALY else 0.015))
    ab = {C.ADDRESS_ISSUE: (2.2, 3.5), C.UNKNOWN: (4, 3), C.CUSTODY_ANOMALY: (6, 2)}.get(cause, (7, 1.8))
    addr_conf = float(np.clip(_blur(rng.beta(*ab), 0.65, k), 0.01, 0.99))
    lam_mw = {C.RECIPIENT_UNAVAILABLE: 2.4, C.UNKNOWN: 1.2, C.ATTEMPT_NOT_COMPLETED: 0.8}.get(cause, 0.35)
    missed = int(rng.poisson(max(_blur(lam_mw, 0.9, k), 0.01)))
    window_conflict = bool(rng.random() < {C.ATTEMPT_NOT_COMPLETED: .35, C.CUSTODY_ANOMALY: .25}.get(cause, .05))
    cr = (2.0, 3.0) if cause == C.ROUTE_DISRUPTION else ((5, 3) if cause == C.UNKNOWN else (8, 2))
    corridor_ratio = float(np.clip(_blur(rng.beta(*cr), 0.7, k), 0.02, 1.2))
    st_mean = {C.ROUTE_DISRUPTION: 25, C.RECIPIENT_UNAVAILABLE: 20, C.ADDRESS_ISSUE: 18, C.ATTEMPT_NOT_COMPLETED: 10, C.FACILITY_BACKLOG: 12, C.NONE: 5, C.CUSTODY_ANOMALY: 8, C.UNKNOWN: 12,
               C.PICKUP_POINT_UNAVAILABLE: 8}[cause]
    stationary = float(rng.exponential(max(_blur(st_mean, 12, k), 1.0)))
    med_d = {C.RECIPIENT_UNAVAILABLE: 60, C.ADDRESS_ISSUE: 250, C.ATTEMPT_NOT_COMPLETED: 800, C.ROUTE_DISRUPTION: 4000, C.NONE: 3000}.get(cause, 1500)
    if cfg.unseen_behaviour and cause == C.RECIPIENT_UNAVAILABLE and rng.random() < 0.5:
        med_d, addr_conf = 300, float(rng.beta(2.5, 3))  # away recipient AND a poor address pin: a combination the agent never saw
    dist = float(rng.lognormal(np.log(med_d), 0.8))
    geo = bool(rng.random() < {C.ATTEMPT_NOT_COMPLETED: .45, C.CUSTODY_ANOMALY: .30}.get(cause, .03))
    backlog = float(rng.lognormal(np.log({C.FACILITY_BACKLOG: 90, C.ROUTE_DISRUPTION: 40}.get(cause, 28)), 0.45))
    gap = float(hours * rng.uniform(0.7, 1.1))
    pk_off = bool(rng.random() < {C.PICKUP_POINT_UNAVAILABLE: .93, C.UNKNOWN: .12}.get(cause, .03))
    cf = int(rng.poisson(5.0 if systemic else 0.4))
    z = -1.6 + 1.2 * (hours > 3) + 1.5 * (addr_conf < .55) + 1.0 * (missed >= 2) + 1.1 * (corridor_ratio < .6) + 0.9 * min(failed, 2) + rng.normal(0, 0.8)
    return Hidden(hours, failed, seq_conflict, addr_conf, missed, window_conflict, corridor_ratio, stationary, dist, geo, backlog, gap, pk_off, cf, float(1 / (1 + np.exp(-z))))


def tool_outcome(name: str, h: Hidden, engine: str) -> str:
    """The discrete outcome the real tool would return for these hidden variables (thresholds copied from dallal.tools.signals)."""
    if name == "get_journey":
        return "sequence_conflict" if h.seq_conflict else "stalled" if h.hours_since_scan > 4.0 else "failed_attempt_logged" if h.failed_logged >= 1 else "clean"
    if name == "get_address_context":
        return "address_weak" if h.addr_conf < 0.55 else "address_ok"
    if name == "get_recipient_context":
        return "window_conflict" if h.window_conflict else "history_of_missed_windows" if h.missed_windows >= 2 else "no_signal"
    if name == "get_route_context":
        if h.corridor_ratio < 0.5 and h.stationary_min >= 15:
            return "blocked_stationary"
        if h.geo_mismatch:
            return "attempt_geo_mismatch"
        if h.stationary_min >= 15:
            return "stationary_at_address" if h.dist_to_addr_m < 150 else "stationary_elsewhere"
        return "corridor_slow" if h.corridor_ratio < 0.6 else "normal"
    if name == "get_facility_context":
        return "backlog" if (h.backlog >= 40 and h.backlog >= 2.5 * 25) else "scan_gap" if h.gap_h > 4.0 else "normal"
    if name == "get_pickup_context":
        return "offline" if h.pickup_offline else "online"
    if name == "check_incident_context":
        return "incident_confirmed" if h.corridor_failures >= 4 else "subthreshold_cluster" if h.corridor_failures >= 2 else "no_cluster"
    if name == "predict_risk":
        if engine == "v2":
            return "high" if h.risk_score >= 0.6 else "elevated" if h.risk_score >= 0.25 else "low"
        if h.risk_score < 0.35:
            return "low"
        comp = {"driver_address": h.addr_conf < .55, "driver_recipient": h.missed_windows >= 2, "driver_route": h.corridor_ratio < .6, "driver_facility": h.gap_h > 4.0,
                "driver_custody": h.seq_conflict, "driver_pickup": h.pickup_offline}
        return next((k for k, v in comp.items() if v), "generic_high")
    raise KeyError(name)


FAULT_FAMILIES = {"get_journey": "scans", "get_facility_context": "scans", "get_address_context": "context", "get_recipient_context": "context"}
FAULT_OUTCOME = {"get_journey": "stalled", "get_facility_context": "scan_gap", "get_address_context": "address_weak", "get_recipient_context": "history_of_missed_windows"}


# ── people ───────────────────────────────────────────────────────────────────────────────────────────────────────────────
COURIER = {C.NONE: {"on_route_normal": .80, "delivered_handed": .15, "at_address_no_answer": .05}, C.ADDRESS_ISSUE: {"cannot_find_address": .75, "at_address_no_answer": .20, "never_reached": .05},
           C.RECIPIENT_UNAVAILABLE: {"at_address_no_answer": .85, "on_route_normal": .10, "cannot_find_address": .05}, C.ATTEMPT_NOT_COMPLETED: {"never_reached": .50, "at_address_no_answer": .30, "on_route_normal": .20},
           C.ROUTE_DISRUPTION: {"road_blocked": .80, "on_route_normal": .15, "never_reached": .05}, C.FACILITY_BACKLOG: {"parcel_missing": .50, "never_reached": .40, "on_route_normal": .10},
           C.PICKUP_POINT_UNAVAILABLE: {"on_route_normal": .60, "at_address_no_answer": .30, "never_reached": .10}, C.CUSTODY_ANOMALY: {"parcel_missing": .60, "delivered_handed": .30, "never_reached": .10},
           C.UNKNOWN: {"on_route_normal": .25, "at_address_no_answer": .25, "never_reached": .25, "road_blocked": .25}}
RECIPIENT_AVAIL = {C.RECIPIENT_UNAVAILABLE: {"avail_no": .50, "reschedule": .40, "avail_yes": .10}, "default": {"avail_yes": .75, "reschedule": .15, "avail_no": .10}}
LOCATION = {C.ADDRESS_ISSUE: {"loc_far": .60, "address_wrong_text": .25, "loc_unsure": .15}, "default": {"loc_match": .80, "loc_unsure": .15, "loc_far": .05}}
RECEIPT = {C.CUSTODY_ANOMALY: {"not_received": .75, "unsure": .15, "received": .10}, "default": {"received": .85, "unsure": .10, "not_received": .05}}
CORRIDOR = {C.ROUTE_DISRUPTION: {"blocked_long": .60, "slow_short": .35, "clear": .05}, "default": {"clear": .85, "slow_short": .12, "blocked_long": .03}}
BRANCH = {C.FACILITY_BACKLOG: {"backlog_confirmed": .85, "normal_ops": .10, "located_elsewhere": .05}, C.CUSTODY_ANOMALY: {"located_elsewhere": .60, "normal_ops": .30, "backlog_confirmed": .10},
          "default": {"normal_ops": .80, "backlog_confirmed": .10, "located_elsewhere": .10}}
BEHAVIOUR = {"ask_courier_status": COURIER, "ask_recipient_availability": RECIPIENT_AVAIL, "ask_recipient_location": LOCATION, "ask_recipient_receipt": RECEIPT, "ask_corridor_status": CORRIDOR, "ask_branch_backlog": BRANCH}
P_RESP_TRUE = {"courier": 0.88, "dispatcher": 0.82, "branch_supervisor": 0.75}  # recipients depend on responsiveness (below)
RESP_BY_CLASS = {"high": 0.80, "medium": 0.50, "low": 0.20}
LAT_MEDIAN_TRUE = {"courier": 6.0, "dispatcher": 7.0, "branch_supervisor": 12.0, "recipient": 22.0}


@dataclass
class Draws:
    """Common random numbers: the SAME uniforms are used by every agent on an episode, so differences are decisions, not luck."""

    u_action: dict[str, float]
    z_time: dict[str, float]
    u_wait: float
    u_escalate: float
    u_pick: float
    z_handoff: float


class ProcessEnv(SimEnv):
    """Drop-in replacement for SimEnv: same interface for the runtime and the simulated tools, different physics."""

    def __init__(self, ep: Episode, hidden: Hidden, draws: Draws, cfg: ProcessConfig, rng: np.random.Generator, engine: str = "v2"):
        super().__init__(ep, TrueModel(), rng, engine)
        self.hidden, self.draws, self.cfg = hidden, draws, cfg
        self.answers_given: list[dict[str, Any]] = []
        self._streams: dict[str, np.random.Generator] = {}

    def _rng(self, key: str) -> np.random.Generator:
        """Keyed random streams: the n-th use of `key` returns the same numbers for every agent on this episode (common random numbers for evidence)."""
        if key not in self._streams:
            self._streams[key] = np.random.default_rng([self.ep.seed, 9100, zlib.crc32(key.encode())])
        return self._streams[key]

    def sample_tool(self, name: str) -> str:
        fam = FAULT_FAMILIES.get(name)
        if fam and self.cfg.shared_fault_prob > 0 and self._rng(f"fault:{fam}").random() < self.cfg.shared_fault_prob:
            return FAULT_OUTCOME[name]  # common-mode fault: the family's tools fail TOGETHER and agree on a misleading story
        outs = (RISK_BAND_MODEL if (name == "predict_risk" and self.engine == "v2") else OBSERVATION_MODELS[name]).outcomes
        if name in self.cfg.tool_outage or (name != "check_incident_context" and self._rng(f"gap:{name}").random() < self.cfg.data_gap):
            return outs[0]
        return tool_outcome(name, self.hidden, self.engine)

    def answer(self, pend, spec: iq.InquirySpec, p_assumed: float):
        self.messages_sent += 1
        self.comm_cost += (spec.raw["cost"]["comm_sar"] + spec.raw["cost"]["friction_sar"]) * self.cfg.comm_scale
        tgt = spec.target
        p = (RESP_BY_CLASS[self.ep.facts["recipient_responsiveness"]] if tgt == "recipient" else P_RESP_TRUE[tgt]) * self.cfg.p_resp_scale
        r = self._rng(f"ans:{spec.id}")
        lat = float(np.exp(np.log(LAT_MEDIAN_TRUE[tgt] * self.cfg.latency_scale) + 0.7 * r.normal()))
        u_resp, u_noise, u_pick, u_stale = r.random(), r.random(), r.random(), r.random()
        if u_resp > min(p, 0.99) or lat > spec.raw["response"]["timeout_min"]:
            self.answers_given.append({"spec": spec.id, "answer": None, "lat": None})
            return InquiryTimeout(pend.inquiry_id)
        table = BEHAVIOUR[spec.id]
        dist = table.get(self.ep.truth, table.get("default"))
        if self.cfg.unseen_behaviour and spec.id == "ask_courier_status" and u_stale < 0.25:
            dist = COURIER[C.NONE]  # stale status: the courier reports the previous stop
        ids = [a["id"] for a in spec.answers]
        if u_noise < self.cfg.answer_noise:
            ans = ids[int(u_pick * len(ids)) % len(ids)]  # wrong or contradictory answer, uniformly over the closed set
        else:
            keys = list(dist)
            cum = np.cumsum([dist[k] for k in keys]) / sum(dist.values())
            ans = keys[int(np.searchsorted(cum, u_pick))]
        self.answers_given.append({"spec": spec.id, "answer": ans, "truth": self.ep.truth.value, "lat": lat})
        return InquiryResponse(pend.inquiry_id, ans, lat, {"sim": True})


def draw_process_episode(seed: int, cfg: ProcessConfig) -> tuple[Episode, Hidden, Draws]:
    rng = np.random.default_rng([seed, 7001])
    causes, p = _mix(cfg)
    cause = causes[int(rng.choice(len(causes), p=p))]
    systemic = bool(rng.random() < cfg.systemic_share)
    if systemic:
        cause = C.ROUTE_DISRUPTION
    ep = draw_episode(np.random.default_rng([seed, 7002]), systemic=systemic, forced_cause=cause, seed=seed)
    ep.slack_min = float(np.clip(ep.slack_min * cfg.slack_scale, 15.0, 1500.0))
    h = draw_hidden(np.random.default_rng([seed, 7003]), cause, systemic, cfg)
    r = np.random.default_rng([seed, 7004])
    names = list(load_catalogue()["actions"])
    d = Draws({a: float(r.random()) for a in names}, {a: float(r.normal()) for a in names}, float(r.random()), float(r.random()), float(r.random()), float(r.normal()))
    return ep, h, d


# ── realised outcomes (independent of the agent's utility model) ────────────────────────────────────────────────────────
def env_stakes(ep: Episode, cfg: ProcessConfig) -> tuple[float, float]:
    v = max(ep.facts.get("value") or 0.0, ep.facts.get("cod_amount") or 0.0) * 0.05
    mult = {"Standard": 1.0, "Express": 1.5, "Same-day": 2.0}.get(ep.facts["service_level"], 1.0)
    return (110.0 + v) * mult * cfg.util_scale, (190.0 + v) * mult * cfg.util_scale


def action_minutes(a: str, d: Draws, approval: str) -> float:
    cat = load_catalogue()["actions"][a]
    return float(cat["minutes_to_effect"] * np.exp(0.35 * d.z_time[a]) + APPROVAL_MIN[approval] * np.exp(0.3 * d.z_time[a]))


def feasible(ep: Episode, a: str) -> bool:
    return all(ep.preds.get(r, False) for r in load_catalogue()["actions"][a].get("requires", []))


def true_p(ep: Episode, a: str, cfg: ProcessConfig) -> float:
    if ep.truth == C.NONE:
        return HEALTHY_ACTION_P
    return float(min(0.99, TRUE_P.get(a, {}).get(ep.truth, 0.04) * cfg.action_scale))


def realise(ep: Episode, d: Draws, cfg: ProcessConfig, option: str, elapsed_min: float, approval: str, comm_cost: float, irreversible: bool, rng_pick: np.random.Generator | None = None) -> dict[str, Any]:
    """Result of taking `option` after `elapsed_min` minutes of investigation (plus approval/handoff time).

    Returns the REALISED outcome (`utility`, `success`: Bernoulli draw from the shared uniforms) and its low-variance expectation given the same physical draws
    (`exp_utility`, `p`: true success probability x 1[the action finishes before the deadline]). Time-to-effect is lognormal and shared across agents.
    """
    V, F = env_stakes(ep, cfg)
    cat = load_catalogue()["actions"]
    if option == "wait":
        p = WAIT_P[ep.truth]
        ok = d.u_wait < p
        return {"success": bool(ok), "utility": (V if ok else -F) - comm_cost, "p": p, "exp_utility": p * V - (1 - p) * F - comm_cost, "minutes": 0.0}
    if option == "escalate":
        feas = [a for a in cat if feasible(ep, a)]
        if not feas:
            p, cost = 0.1, 22.0
            ok = d.u_escalate < p
            return {"success": bool(ok), "utility": (V if ok else -F) - cost - comm_cost, "p": p, "exp_utility": p * V - (1 - p) * F - cost - comm_cost, "minutes": 0.0}
        best = max(feas, key=lambda a: true_p(ep, a, cfg))
        w = {a: 0.15 / len(feas) + (0.85 if a == best else 0.0) for a in feas}
        mins = {a: 20.0 * np.exp(0.4 * d.z_handoff) + action_minutes(a, d, "none") for a in feas}
        pa = {a: true_p(ep, a, cfg) * float(elapsed_min + mins[a] <= ep.slack_min) for a in feas}
        p = sum(w[a] * pa[a] for a in feas)
        exp_u = sum(w[a] * (pa[a] * V - (1 - pa[a]) * F - 12.0 - ACTION_COST[a]) for a in feas) - comm_cost
        pick = best if d.u_pick < 0.85 else feas[int(d.u_pick * 997) % len(feas)]
        ok = d.u_escalate < pa[pick]
        return {"success": bool(ok), "utility": (V if ok else -F) - 12.0 - ACTION_COST[pick] - comm_cost, "p": p, "exp_utility": exp_u, "minutes": float(mins[pick])}
    minutes = action_minutes(option, d, approval)
    pa = true_p(ep, option, cfg) * float(elapsed_min + minutes <= ep.slack_min)
    ok = d.u_action[option] < pa
    pen = 25.0 if irreversible else 0.0
    return {"success": bool(ok), "utility": (V if ok else -F) - ACTION_COST[option] - pen * (not ok) - comm_cost, "p": pa, "exp_utility": pa * V - (1 - pa) * F - ACTION_COST[option] - pen * (1 - pa) - comm_cost,
            "minutes": float(minutes)}


def oracle_expected_best(ep: Episode, d: Draws, cfg: ProcessConfig) -> tuple[str, dict[str, Any]]:
    """Zero-cost, zero-delay agent that knows the true cause and picks the option with the best EXPECTED realised utility, then lives with the same draws."""
    V, F = env_stakes(ep, cfg)
    cat = load_catalogue()["actions"]
    best, bu = "wait", WAIT_P[ep.truth] * V - (1 - WAIT_P[ep.truth]) * F
    for a in cat:
        if not feasible(ep, a):
            continue
        p = true_p(ep, a, cfg) * float(action_minutes(a, d, cat[a]["approval"]) <= ep.slack_min)  # the oracle also knows the physical times
        eu = p * V - (1 - p) * F - ACTION_COST[a]
        if eu > bu:
            best, bu = a, eu
    appr = "none" if best == "wait" else cat[best]["approval"]
    return best, realise(ep, d, cfg, best, 0.0, appr, 0.0, best != "wait" and not cat[best]["reversible"])
