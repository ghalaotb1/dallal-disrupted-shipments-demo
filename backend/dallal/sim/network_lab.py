"""Network recovery lab on an independent REALISATION model (SYNTHETIC). Paired by seed, common random numbers.

The solver plans with a smooth on-time model (`p_on_time`, sigmoid in slack) and point estimates; reality here is different and sampled:
blockage duration D is a continuous lognormal mixture, true remaining travel times are lognormal around the (noisy) estimates, spare-courier arrival,
alternative-route detour and pickup travel are lognormal, pickup acceptance is a Bernoulli draw, and a parcel is on time iff its sampled finish time is
within its promise. Decision delay (waiting for a dispatcher's answer) is applied to every option that has to START later; a van that simply waits at
the blockage is not delayed. Strategies share the same draws, so differences are decisions.

Measured per incident: realised utility (environment stakes), parcels protected (on time), SLA violations (late), interventions (non-wait actions),
messages, deferred parcels and capacity over-requests (before repair), plus regret against an oracle that knows D (zero delay, zero questions).
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from dallal.agent.v2 import inquiry as iq
from dallal.recovery import network as N

PRIOR = 0.30
SPEC = iq.spec("ask_corridor_status")
ANS = N.ANSWERS


@dataclass
class NetConfig:
    name: str = "baseline"
    n_parcels: tuple[int, int] = (8, 14)
    slack_scale: float = 1.0
    spares: tuple[int, int] = (1, 2)  # number of spare couriers
    spare_cap: tuple[int, int] = (1, 3)
    pickups: tuple[int, int] = (0, 2)
    p_long_true: float = 0.30
    p_resp: float = 0.85
    latency_median: float = 7.0
    answer_noise: float = 0.10  # dispatcher reports something other than the truth
    comm_scale: float = 1.0
    util_scale: float = 1.0
    travel_noise: float = 0.25
    estimate_noise: float = 0.20


def regimes() -> dict[str, NetConfig]:
    return {
        "baseline": NetConfig("baseline"),
        "low_capacity": NetConfig("low_capacity", spares=(1, 1), spare_cap=(1, 2), pickups=(0, 1)),
        "high_capacity": NetConfig("high_capacity", spares=(3, 4), spare_cap=(2, 4), pickups=(2, 3)),
        "urgent_deadlines": NetConfig("urgent_deadlines", slack_scale=0.55),
        "flexible_deadlines": NetConfig("flexible_deadlines", slack_scale=2.2),
        "small_incident": NetConfig("small_incident", n_parcels=(3, 5)),
        "large_incident": NetConfig("large_incident", n_parcels=(16, 22), spares=(2, 3)),
        "missing_or_delayed_response": NetConfig("missing_or_delayed_response", p_resp=0.35, latency_median=25.0),
        "contradictory_answers": NetConfig("contradictory_answers", answer_noise=0.45),
        "prior_wrong_long": NetConfig("prior_wrong_long", p_long_true=0.65),
        "prior_wrong_short": NetConfig("prior_wrong_short", p_long_true=0.08),
    }


STRATS = ("independent_naive", "independent_strong", "desk_greedy", "independent_inquiry", "coordinated_no_inquiry", "coordinated_inquiry", "coordinated_inquiry_adaptive", "coordinated_always_ask",
          "coordinated_inquiry_no_recourse", "oracle")


@dataclass
class World:
    pr: N.Problem
    D: float
    is_long: bool
    true_rem: dict[str, float]
    spare_eta: dict[str, float]
    pick_travel: dict[str, float]
    alt_extra: float
    pick_u: dict[str, float]
    V: dict[str, float]
    F: dict[str, float]
    z_spare_leg: dict[str, float]
    seed: int
    cfg: NetConfig
    streams: dict[str, np.random.Generator] = field(default_factory=dict)

    def rng(self, key: str) -> np.random.Generator:
        if key not in self.streams:
            self.streams[key] = np.random.default_rng([self.seed, 5100, zlib.crc32(key.encode())])
        return self.streams[key]


def draw_world(seed: int, cfg: NetConfig) -> World:
    r = np.random.default_rng([seed, 5001])
    n = int(r.integers(cfg.n_parcels[0], cfg.n_parcels[1] + 1))
    n_vans = int(np.clip(round(n / 4) + r.integers(-1, 2), 2, 6))
    parcels, true_rem, V, F, pick_u, zleg = [], {}, {}, {}, {}, {}
    for i in range(n):
        val = float(np.exp(r.normal(5.8, 0.8)))
        svc = str(r.choice(["Standard", "Express", "Same-day"], p=[0.5, 0.3, 0.2]))
        rem_true = float(r.uniform(15, 60))
        slack = float(r.uniform(45, 110) if svc != "Standard" else r.uniform(70, 200)) * cfg.slack_scale
        est = rem_true * float(np.exp(cfg.estimate_noise * r.normal()))
        pid = f"P{i}"
        parcels.append(N.Parcel(pid, f"V{int(r.integers(n_vans))}", val, slack, est, svc, bool(r.random() < 0.4), bool(svc != "Same-day"), bool(r.random() < 0.85)))
        true_rem[pid] = rem_true * float(np.exp(cfg.travel_noise * r.normal()))
        mult = {"Standard": 1.0, "Express": 1.5, "Same-day": 2.0}[svc]
        V[pid], F[pid] = (110.0 + 0.05 * val) * mult * cfg.util_scale, (190.0 + 0.05 * val) * mult * cfg.util_scale
        pick_u[pid], zleg[pid] = float(r.random()), float(r.normal())
    ns = int(r.integers(cfg.spares[0], cfg.spares[1] + 1))
    spares = [N.Spare(f"S{j}", float(r.uniform(18, 40)), int(r.integers(cfg.spare_cap[0], cfg.spare_cap[1] + 1))) for j in range(ns)]
    npk = int(r.integers(cfg.pickups[0], cfg.pickups[1] + 1))
    pickups = [N.PickupPoint(f"K{j}", float(r.uniform(15, 35)), int(r.integers(2, 5))) for j in range(npk)]
    alt_extra = float(r.uniform(25, 55))
    pr = N.Problem(parcels, spares, pickups, bool(r.random() < 0.7), alt_extra)
    is_long = bool(r.random() < cfg.p_long_true)
    D = float(np.exp(np.log(110.0) + 0.45 * r.normal())) if is_long else float(np.exp(np.log(18.0) + 0.5 * r.normal()))
    spare_eta = {s.id: s.eta_min * float(np.exp(0.3 * r.normal())) for s in spares}
    pick_travel = {k.id: k.travel_min * float(np.exp(0.3 * r.normal())) for k in pickups}
    return World(pr, D, is_long, true_rem, spare_eta, pick_travel, alt_extra * float(np.exp(0.3 * r.normal())), pick_u, V, F, zleg, seed, cfg)


def dispatcher_answer(w: World, key: str) -> tuple[str | None, float]:
    """(answer id or None, minutes until it arrives or the deadline). The n-th question with the same key gets the same draws for every strategy."""
    r = w.rng(key)
    u_resp, z_lat, u_noise, u_pick = r.random(), r.normal(), r.random(), r.random()
    lat = float(np.exp(np.log(w.cfg.latency_median) + 0.6 * z_lat))
    timeout = float(SPEC.raw["response"]["timeout_min"])
    if u_resp > w.cfg.p_resp or lat > timeout:
        return None, timeout
    if u_noise < w.cfg.answer_noise:
        return ANS[int(u_pick * len(ANS)) % len(ANS)], lat
    # truthful report, from a continuous truth: clear if it already cleared, slow if short, blocked if long
    truth = "clear" if w.D < 6 else "blocked_long" if w.is_long else "slow_short"
    return (truth if u_pick < 0.9 else "dont_know"), lat


def realise(w: World, assign: dict[str, str], reroute_vans: set[str], shift: dict[str, float], msgs_cost: float, n_msgs: int) -> dict[str, Any]:
    """Sampled outcome of a plan. `shift[pid]` = minutes before an option that must start later can begin (decision delay); `wait` is never delayed."""
    pr = w.pr
    util, on_time, late, deferred, interventions = 0.0, 0, 0, 0, 0
    spares_used = {o.split(":")[1] for o in assign.values() if o.startswith("spare:")}
    cap_over = 0
    for s in pr.spares:
        cap_over += max(0, sum(1 for o in assign.values() if o == f"spare:{s.id}") - s.capacity)
    for k in pr.pickups:
        cap_over += max(0, sum(1 for o in assign.values() if o == f"pickup:{k.id}") - k.capacity)
    for p in pr.parcels:
        o = assign[p.id]
        d0 = shift.get(p.id, 0.0)
        rem = w.true_rem[p.id]
        if o == "wait":
            finish = w.D + rem
        elif o == "reroute":
            finish = d0 + w.alt_extra + rem
            interventions += 1
        elif o.startswith("spare:"):
            j = o.split(":")[1]
            finish = d0 + w.spare_eta[j] + 0.7 * rem * float(np.exp(0.2 * w.z_spare_leg[p.id]))
            interventions += 1
        elif o.startswith("pickup:"):
            k = o.split(":")[1]
            accepted = w.pick_u[p.id] < N.PICKUP_ACCEPT * (1.0 if p.recipient_reachable else 0.3)
            finish = d0 + w.pick_travel[k] if accepted else 1e9
            interventions += 1
        else:  # defer with notice
            util += -N.DEFER_FAIL_SHARE * w.F[p.id] - 10.0
            deferred += 1
            late += 1
            interventions += 1
            continue
        ok = finish <= p.slack_min
        on_time += ok
        late += (not ok)
        util += w.V[p.id] if ok else -w.F[p.id]
    util -= 40.0 * len(spares_used) + 15.0 * len(reroute_vans) + 14.0 * sum(1 for o in assign.values() if o.startswith("pickup:")) + 0.3 * len(pr.parcels) + msgs_cost
    return {"utility": util, "protected": on_time, "late": late, "deferred": deferred, "interventions": interventions, "messages": n_msgs, "cap_over_requests": cap_over, "n": len(pr.parcels)}


def _ask_cost(w: World) -> float:
    return (SPEC.raw["cost"]["comm_sar"] + SPEC.raw["cost"]["friction_sar"]) * w.cfg.comm_scale


def _plan_cost_belief(w: World) -> float:
    return iq.cost_sar(SPEC, {})  # what the PLANNER believes a question costs


def run_incident(seed: int, cfg: NetConfig, stats: Any = None) -> list[dict[str, Any]]:
    w = draw_world(seed, cfg)
    pr = w.pr
    out: list[dict[str, Any]] = []
    P_RESP_BELIEF, LAT_BELIEF = iq.response_prob(SPEC, {}), iq.expected_latency_min(SPEC)
    cost_true = _ask_cost(w)

    def add(name: str, r: dict[str, Any], asked: bool = False) -> None:
        out.append({"regime": cfg.name, "seed": seed, "strategy": name, "is_long": w.is_long, "D": w.D, "asked": asked, **r})

    # oracle: knows D class, no delay, no question
    o = N.solve(pr, 0.999 if w.D > 60 else 0.001)
    add("oracle", realise(w, o.assignments, set(o.reroute_vans), {}, 0.0, 0))
    ind = N.independent_plan(pr, PRIOR, seed=seed)
    add("independent_naive", realise(w, ind.assignments, set(ind.reroute_vans), {}, 0.0, 0) | {"cap_over_requests": int(ind.utilities["_capacity_requests_over_cap"])})
    ind_s = N.independent_plan(pr, PRIOR, seed=seed, share_fixed_costs=True, repair="next_best")
    add("independent_strong", realise(w, ind_s.assignments, set(ind_s.reroute_vans), {}, 0.0, 0) | {"cap_over_requests": int(ind_s.utilities["_capacity_requests_over_cap"])})
    gr = N.greedy_plan(pr, PRIOR)
    add("desk_greedy", realise(w, gr.assignments, set(gr.reroute_vans), {}, 0.0, 0))
    # independent agents each deciding whether to ask the dispatcher about the same corridor
    p_by, shift_by, n_msgs = {}, {}, 0
    for i, p in enumerate(pr.parcels):
        v = N.cluster_inquiry_value(replace(pr, parcels=[p]), PRIOR, p_response=P_RESP_BELIEF, latency_min=LAT_BELIEF, cost_sar=_plan_cost_belief(w))
        if v["net"] >= 0.4:
            a_i, l_i = dispatcher_answer(w, f"ind:{i}")
            n_msgs += 1
            p_by[p.id] = N.posterior_long(PRIOR, a_i) if a_i else PRIOR
            shift_by[p.id] = l_i
        else:
            p_by[p.id], shift_by[p.id] = PRIOR, 0.0
    i2 = N.independent_plan(pr, p_by, shift_by, seed=seed, share_fixed_costs=True, repair="next_best")
    add("independent_inquiry", realise(w, i2.assignments, set(i2.reroute_vans), shift_by, cost_true * n_msgs, n_msgs))
    co = N.solve(pr, PRIOR)
    add("coordinated_no_inquiry", realise(w, co.assignments, set(co.reroute_vans), {}, 0.0, 0))

    def coordinated_with_answer(recourse: bool, gate: bool) -> tuple[dict[str, Any], bool]:
        v = N.cluster_inquiry_value(pr, PRIOR, p_response=P_RESP_BELIEF, latency_min=LAT_BELIEF, cost_sar=_plan_cost_belief(w))
        if gate and v["net"] < 0.4:
            return realise(w, co.assignments, set(co.reroute_vans), {}, 0.0, 0), False
        a, lat = dispatcher_answer(w, "coord")
        commit = N.robust_commit(pr) if recourse else {}
        shift = {p.id: (0.0 if p.id in commit else lat) for p in pr.parcels}
        post = N.posterior_long(PRIOR, a) if a else PRIOR
        plan = N.solve(pr, post, slack_shift=shift, fixed=commit)
        return realise(w, plan.assignments, set(plan.reroute_vans), shift, cost_true, 1), True

    r, asked = coordinated_with_answer(True, True)
    add("coordinated_inquiry", r, asked)
    if stats is not None:  # learned responsiveness + reliability (carried across incidents of one environment)
        from dallal.agent.v2.response_stats import ResponseStats

        rs, rel = stats
        ov = rs.overrides().get("ask_corridor_status", {})
        p_resp_l, lat_l = ov.get("p", P_RESP_BELIEF), (ov["latency_median"] * float(np.exp(SPEC.raw["response"]["latency_sigma"] ** 2 / 2)) if "latency_median" in ov else LAT_BELIEF)
        v = N.cluster_inquiry_value(pr, PRIOR, p_response=p_resp_l, latency_min=lat_l, cost_sar=_plan_cost_belief(w), reliability=rel.reliability)
        if v["net"] < 0.4:
            add("coordinated_inquiry_adaptive", realise(w, co.assignments, set(co.reroute_vans), {}, 0.0, 0), False)
        else:
            a, lat = dispatcher_answer(w, "coord")
            commit = N.robust_commit(pr)
            shift = {p.id: (0.0 if p.id in commit else lat) for p in pr.parcels}
            post = N.posterior_long(PRIOR, a, rel.reliability) if a else PRIOR
            plan = N.solve(pr, post, slack_shift=shift, fixed=commit)
            add("coordinated_inquiry_adaptive", realise(w, plan.assignments, set(plan.reroute_vans), shift, cost_true, 1), True)
            rs.update("ask_corridor_status", a is not None, lat if a is not None else None)
            if a is not None and a != "dont_know":
                rel.update((a == "blocked_long") == w.is_long)  # outcome feedback: the blockage's duration is observed afterwards
        _ = ResponseStats
    r, _ = coordinated_with_answer(True, False)
    add("coordinated_always_ask", r, True)
    r, asked = coordinated_with_answer(False, True)
    add("coordinated_inquiry_no_recourse", r, asked)
    return out


def _task(args: tuple) -> list[dict[str, Any]]:
    """One environment's incidents in order, so the adaptive strategy can learn from the incidents before it."""
    from dallal.agent.v2.response_stats import ReliabilityStats, ResponseStats

    cfg, seeds = args
    stats = (ResponseStats(), ReliabilityStats())
    return [r for sd in seeds for r in run_incident(sd, cfg, stats)]


def run_suite(cfgs: dict[str, NetConfig], n: int, start: int = 0, workers: int = 1) -> pd.DataFrame:
    tasks = [(c, list(range(start, start + n))) for c in cfgs.values()]
    if workers <= 1:
        rows = [r for t in tasks for r in _task(t)]
    else:
        import multiprocessing as mp

        with mp.get_context("spawn").Pool(workers) as pool:
            rows = [r for chunk in pool.map(_task, tasks, chunksize=1) for r in chunk]
    df = pd.DataFrame(rows)
    orc = df[df.strategy == "oracle"].set_index(["regime", "seed"])["utility"]
    df["regret"] = [orc[(a, b)] - u for a, b, u in zip(df.regime, df.seed, df.utility, strict=True)]
    df["protected_share"] = df.protected / df.n
    return df
