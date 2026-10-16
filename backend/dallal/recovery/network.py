"""Coordinated network recovery for a shared-cause incident.

PROBLEM  Several parcels are affected (or exposed) by one operational cause, e.g. a blocked corridor. Each parcel has options:
           wait with its van | reroute its van | reassign to a spare courier | redirect to a pickup point | defer to a later day
         but the options are COUPLED:
           * a van carries several parcels and can only wait OR reroute (one decision per van);
           * spare couriers and pickup points have capacity, and a spare courier has a fixed dispatch cost shared by its parcels;
           * the blockage duration is uncertain, and one answer from the dispatcher informs every parcel at once.
METHOD   One mixed-integer program maximises expected utility (SAR-equivalent, utility.yaml scale) over all parcels jointly. Expectation is
         taken over a belief on the blockage duration. A cluster-level value-of-information step decides whether asking the dispatcher ONCE is
         worth its cost and delay, by re-solving the plan for every possible answer.
BASELINE Independent per-shipment decisions (each parcel optimises alone, blind to capacity, van coupling and shared costs), followed by the
         repair a real operation would need (first-come capacity, any-request van reroute). The comparison quantifies what coordination buys.

SCIENTIFIC STATUS  Utilities, travel times, capacities and acceptance rates are ASSUMPTIONS supplied by the caller; the optimisation and the
comparisons are exact for those inputs. Nothing here is learned from outcomes.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from dallal.agent.v2.utility import params

SIGMA_MIN = 10.0  # softness of the on-time boundary, minutes
PICKUP_ACCEPT = 0.75  # share of recipients who actually collect within the promise (assumption)
DEFER_FAIL_SHARE = 0.4  # a planned deferral with notice costs less than an unplanned failure (assumption)


@dataclass
class Parcel:
    id: str
    van: str
    value: float
    slack_min: float  # minutes until the delivery promise
    remaining_min: float  # unobstructed minutes still needed on its current van
    service: str = "Standard"
    exposed: bool = False  # not yet failing, but on the affected corridor
    pickup_ok: bool = True
    recipient_reachable: bool = True


@dataclass
class Spare:
    id: str
    eta_min: float  # minutes before the spare can start
    capacity: int
    fixed_cost: float = 40.0


@dataclass
class PickupPoint:
    id: str
    travel_min: float
    capacity: int
    online: bool = True
    per_parcel_cost: float = 14.0


@dataclass
class Problem:
    parcels: list[Parcel]
    spares: list[Spare] = field(default_factory=list)
    pickups: list[PickupPoint] = field(default_factory=list)
    alt_route_available: bool = True
    alt_extra_min: float = 18.0
    reroute_cost_per_van: float = 15.0
    notify_cost: float = 0.3
    short_min: float = 20.0
    long_min: float = 120.0


def sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def stakes_of(p: Parcel) -> tuple[float, float]:
    u = params()["value"]
    mult = u["service_multiplier"].get(p.service, 1.0)
    stake = p.value * u["stake_factor"]
    return (u["on_time_sar"] + stake) * mult, (u["fail_cost_sar"] + stake) * mult


def p_on_time(slack: float, t: float) -> float:
    return sig((slack - t) / SIGMA_MIN)


def option_utilities(pr: Problem, slack_shift: float | dict[str, float], p_long: float) -> dict[str, dict[str, float]]:
    """Expected utility of each option for each parcel (excluding SHARED costs: reroute/spare fixed costs are in the program).

    `slack_shift` is the decision delay in minutes: a float for everyone, or a per-parcel dict (parcels committed immediately have 0).
    """
    out: dict[str, dict[str, float]] = {}
    p_short = 1.0 - p_long
    for p in pr.parcels:
        V, L = stakes_of(p)
        shift = slack_shift.get(p.id, 0.0) if isinstance(slack_shift, dict) else slack_shift
        slack = p.slack_min - shift  # options that must START later lose the decision delay...
        u: dict[str, float] = {}

        def eu(prob: float, V: float = V, L: float = L) -> float:
            return V * prob - L * (1 - prob)

        # ...but a van that simply waits at the blockage is not delayed by our deciding: the blockage clears on its own clock.
        u["wait"] = (p_short * eu(p_on_time(p.slack_min, p.remaining_min + pr.short_min)) + p_long * eu(p_on_time(p.slack_min, p.remaining_min + pr.long_min))
                     - pr.notify_cost)
        if pr.alt_route_available:
            u["reroute"] = eu(p_on_time(slack, p.remaining_min + pr.alt_extra_min)) - pr.notify_cost
        for s in pr.spares:
            u[f"spare:{s.id}"] = eu(p_on_time(slack, s.eta_min + 0.7 * p.remaining_min)) - 5.0 - pr.notify_cost
        if p.pickup_ok and p.recipient_reachable:
            for k in pr.pickups:
                if k.online:
                    u[f"pickup:{k.id}"] = eu(PICKUP_ACCEPT * p_on_time(slack, k.travel_min)) - k.per_parcel_cost - pr.notify_cost
        u["defer"] = -L * DEFER_FAIL_SHARE - 10.0 - pr.notify_cost
        out[p.id] = u
    return out


@dataclass
class PlanResult:
    assignments: dict[str, str]  # parcel id -> option
    reroute_vans: list[str]
    spares_used: list[str]
    objective: float
    solve_ms: float
    utilities: dict[str, float]  # per parcel chosen-option expected utility
    resource_use: dict[str, int]
    status: str = "optimal"


def solve(pr: Problem, p_long: float, slack_shift: float | dict[str, float] = 0.0, fixed: dict[str, str] | None = None) -> PlanResult:
    """Joint MILP. Variables: x[i,o] (parcel i takes option o), z[v] (van v reroutes), y[j] (spare j dispatched).

    `fixed` pins parcels to options already committed (second-stage recourse after a question: the robust part was acted on immediately).
    """
    t0 = time.perf_counter()
    U = option_utilities(pr, slack_shift, p_long)
    if fixed:
        for pid, o in fixed.items():
            U[pid] = {o: U[pid][o]}
    vans = sorted({p.van for p in pr.parcels})
    idx: dict[tuple[str, str], int] = {}
    cols: list[tuple[str, str]] = []
    for p in pr.parcels:
        for o in U[p.id]:
            idx[(p.id, o)] = len(cols)
            cols.append((p.id, o))
    zi = {v: len(cols) + k for k, v in enumerate(vans)}
    yi = {s.id: len(cols) + len(vans) + k for k, s in enumerate(pr.spares)}
    n = len(cols) + len(vans) + len(pr.spares)
    c = np.zeros(n)
    for (pid, o), j in idx.items():
        c[j] = -U[pid][o]  # minimise negative utility
    for v in vans:
        c[zi[v]] = pr.reroute_cost_per_van
    for s in pr.spares:
        c[yi[s.id]] = s.fixed_cost
    rows, lb, ub = [], [], []

    def add(coefs: dict[int, float], lo: float, hi: float) -> None:
        r = np.zeros(n)
        for j, w in coefs.items():
            r[j] = w
        rows.append(r)
        lb.append(lo)
        ub.append(hi)

    for p in pr.parcels:  # exactly one option per parcel
        add({idx[(p.id, o)]: 1.0 for o in U[p.id]}, 1, 1)
    for p in pr.parcels:  # van coupling: waiting needs z=0, rerouting needs z=1 (a pinned option still obeys it)
        if (p.id, "wait") in idx:
            add({idx[(p.id, "wait")]: 1.0, zi[p.van]: 1.0}, -np.inf, 1)
        if (p.id, "reroute") in idx:
            add({idx[(p.id, "reroute")]: 1.0, zi[p.van]: -1.0}, -np.inf, 0)
    for s in pr.spares:  # capacity and dispatch linking
        members = {idx[(p.id, f"spare:{s.id}")]: 1.0 for p in pr.parcels if (p.id, f"spare:{s.id}") in idx}
        add({**members, yi[s.id]: -float(s.capacity)}, -np.inf, 0)
    for k in pr.pickups:
        members = {idx[(p.id, f"pickup:{k.id}")]: 1.0 for p in pr.parcels if (p.id, f"pickup:{k.id}") in idx}
        if members:
            add(members, -np.inf, float(k.capacity))
    res = milp(c, constraints=LinearConstraint(np.array(rows), lb, ub), integrality=np.ones(n), bounds=Bounds(0, 1))
    if not res.success:
        raise RuntimeError(f"plan infeasible: {res.message}")
    x = np.round(res.x).astype(int)
    assign = {pid: o for (pid, o), j in idx.items() if x[j] == 1}
    return PlanResult(assign, [v for v in vans if x[zi[v]]], [s.id for s in pr.spares if x[yi[s.id]]], float(-res.fun), (time.perf_counter() - t0) * 1000,
                      {pid: U[pid][o] for pid, o in assign.items()}, _usage(assign))


def _usage(assign: dict[str, str]) -> dict[str, int]:
    use: dict[str, int] = {}
    for o in assign.values():
        if ":" in o:
            use[o] = use.get(o, 0) + 1
    return use


def realised_utility(pr: Problem, assign: dict[str, str], reroute_vans: set[str], d_min: float) -> dict[str, Any]:
    """Utility of an ACTUAL set of decisions when the true blockage lasts d_min (shared costs counted once, capacity violations reported)."""
    total, on_time = 0.0, 0.0
    spares_used = {o.split(":")[1] for o in assign.values() if o.startswith("spare:")}
    cap_viol = 0
    for s in pr.spares:
        used = sum(1 for o in assign.values() if o == f"spare:{s.id}")
        cap_viol += max(0, used - s.capacity)
    for k in pr.pickups:
        used = sum(1 for o in assign.values() if o == f"pickup:{k.id}")
        cap_viol += max(0, used - k.capacity)
    for p in pr.parcels:
        V, L = stakes_of(p)
        o = assign[p.id]
        if o == "wait":
            prob = p_on_time(p.slack_min, p.remaining_min + d_min)
            cost = 0.0
        elif o == "reroute":
            prob = p_on_time(p.slack_min, p.remaining_min + pr.alt_extra_min)
            cost = 0.0
        elif o.startswith("spare:"):
            s = next(x for x in pr.spares if x.id == o.split(":")[1])
            prob, cost = p_on_time(p.slack_min, s.eta_min + 0.7 * p.remaining_min), 5.0
        elif o.startswith("pickup:"):
            k = next(x for x in pr.pickups if x.id == o.split(":")[1])
            prob, cost = PICKUP_ACCEPT * p_on_time(p.slack_min, k.travel_min), k.per_parcel_cost
        else:
            total += -L * DEFER_FAIL_SHARE - 10.0 - pr.notify_cost
            continue
        total += V * prob - L * (1 - prob) - cost - pr.notify_cost
        on_time += prob
    total -= pr.reroute_cost_per_van * len(reroute_vans)
    total -= sum(s.fixed_cost for s in pr.spares if s.id in spares_used)
    return {"utility": total, "expected_on_time": on_time, "capacity_violations": cap_viol}


# ── independent baseline ──────────────────────────────────────────────────────────────────────────────────────────────
def independent_plan(pr: Problem, p_long: float | dict[str, float], slack_shift: float | dict[str, float] = 0.0, seed: int = 0, share_fixed_costs: bool = False, repair: str = "defer") -> PlanResult:
    """Each parcel optimises alone: blind to capacity, to the van's other parcels, and to costs shared with other parcels.

    The operational repair a real desk would apply is then simulated: first-come capacity (random order), a van reroutes if ANY of its parcels
    asked for it (the dispatcher cannot split a van), and parcels that lose a capacity race fall back to 'defer'.
    """
    t0 = time.perf_counter()
    if isinstance(p_long, dict):  # each lone agent holds its own belief (e.g. it asked, or did not ask, the dispatcher on its own)
        U = {}
        for p in pr.parcels:
            U.update(option_utilities(replace(pr, parcels=[p]), slack_shift.get(p.id, 0.0) if isinstance(slack_shift, dict) else slack_shift, p_long[p.id]))
    else:
        U = option_utilities(pr, slack_shift, p_long)
    rng = np.random.default_rng(seed)
    want: dict[str, str] = {}
    for p in pr.parcels:
        best, bu = "defer", -1e18
        for o, u in U[p.id].items():
            if share_fixed_costs:  # the stronger desk: knows how many parcels share the van / the spare's capacity, but not what the others will choose
                per_van = pr.reroute_cost_per_van / max(1, sum(1 for q in pr.parcels if q.van == p.van))
                sp = next((s for s in pr.spares if o.startswith("spare:") and s.id == o.split(":")[1]), None)
                full = u - (per_van if o == "reroute" else 0.0) - (sp.fixed_cost / max(1, min(sp.capacity, len(pr.parcels))) if sp else 0.0)
            else:
                full = u - (pr.reroute_cost_per_van if o == "reroute" else 0.0) - (next(s.fixed_cost for s in pr.spares if s.id == o.split(":")[1]) if o.startswith("spare:") else 0.0)
            if full > bu:
                best, bu = o, full  # a lone parcel must carry the whole shared cost: it cannot see anyone to split it with
        want[p.id] = best
    cap = {f"spare:{s.id}": s.capacity for s in pr.spares} | {f"pickup:{k.id}": k.capacity for k in pr.pickups}
    final: dict[str, str] = {}
    order = list(pr.parcels)
    rng.shuffle(order)
    for p in order:
        o = want[p.id]
        if o in cap:
            if cap[o] > 0:
                cap[o] -= 1
                final[p.id] = o
            elif repair == "next_best":  # lost the capacity race: fall back to the best option that needs no scarce capacity
                alts = {k: u for k, u in U[p.id].items() if k not in cap and k != "defer"}
                final[p.id] = max(alts, key=alts.get) if alts else "defer"  # type: ignore[arg-type]
            else:
                final[p.id] = "defer"
        else:
            final[p.id] = o
    reroute = {p.van for p in pr.parcels if want[p.id] == "reroute"}
    for p in pr.parcels:  # van-level consistency: a rerouted van carries all its still-on-van parcels
        if final[p.id] in ("wait", "reroute"):
            final[p.id] = "reroute" if p.van in reroute else "wait"
    conflicts = sum(1 for v in {p.van for p in pr.parcels} if len({want[p.id] for p in pr.parcels if p.van == v and want[p.id] in ("wait", "reroute")}) > 1)
    res = PlanResult(final, sorted(reroute), sorted({o.split(":")[1] for o in final.values() if o.startswith("spare:")}), 0.0, (time.perf_counter() - t0) * 1000, {}, _usage(final), "independent")
    res.utilities = {"_conflicting_van_decisions": float(conflicts), "_capacity_requests_over_cap": float(sum(1 for p in pr.parcels if want[p.id] in cap) - sum(1 for p in pr.parcels if final[p.id] in cap))}
    return res


def greedy_plan(pr: Problem, p_long: float | dict[str, float], slack_shift: float | dict[str, float] = 0.0) -> PlanResult:
    """A strong human-desk heuristic: work through the parcels from highest stake down, each taking its best option given what is already
    committed (capacity left, spares already dispatched, vans already rerouted - shared costs are free once paid). No lookahead, no joint optimisation."""
    t0 = time.perf_counter()
    if isinstance(p_long, dict):
        U = {}
        for p in pr.parcels:
            U.update(option_utilities(replace(pr, parcels=[p]), slack_shift.get(p.id, 0.0) if isinstance(slack_shift, dict) else slack_shift, p_long[p.id]))
    else:
        U = option_utilities(pr, slack_shift, p_long)
    cap = {f"spare:{s.id}": s.capacity for s in pr.spares} | {f"pickup:{k.id}": k.capacity for k in pr.pickups}
    spare_fixed = {f"spare:{s.id}": s.fixed_cost for s in pr.spares}
    dispatched: set[str] = set()
    rerouted: set[str] = set()
    waiting: set[str] = set()
    final: dict[str, str] = {}
    for p in sorted(pr.parcels, key=lambda q: -stakes_of(q)[0]):
        best, bu = "defer", -1e18
        for o, u in U[p.id].items():
            if o in cap and cap[o] <= 0:
                continue
            if o == "reroute" and p.van in waiting:
                continue  # an earlier parcel on this van already chose to wait there
            if o == "wait" and p.van in rerouted:
                continue  # the van has already been rerouted
            full = u
            if o == "reroute" and p.van not in rerouted:
                full -= pr.reroute_cost_per_van
            if o in spare_fixed and o not in dispatched:
                full -= spare_fixed[o]
            if full > bu:
                best, bu = o, full
        final[p.id] = best
        if best in cap:
            cap[best] -= 1
        if best in spare_fixed:
            dispatched.add(best)
        if best == "reroute":
            rerouted.add(p.van)
        if best == "wait":
            waiting.add(p.van)
    res = PlanResult(final, sorted(rerouted), sorted({o.split(":")[1] for o in final.values() if o.startswith("spare:")}), 0.0, (time.perf_counter() - t0) * 1000, {}, _usage(final), "greedy")
    return res


# ── cluster-level value of information ────────────────────────────────────────────────────────────────────────────────
ANSWERS = ("clear", "slow_short", "blocked_long", "dont_know")
# P(answer | true duration class). 'clear' means the blockage already cleared (duration ~0).
LIK = {"short": (0.10, 0.75, 0.05, 0.10), "long": (0.02, 0.08, 0.83, 0.07)}


def lik(reliability: float = 1.0) -> dict[str, tuple[float, ...]]:
    """Answer likelihoods when the responder reports the truth-driven answer only with probability `reliability` (otherwise uninformative). reliability=1 is the catalogue table."""
    r = float(min(1.0, max(0.0, reliability)))
    u = 1.0 / len(ANSWERS)
    return {k: tuple(r * x + (1 - r) * u for x in v) for k, v in LIK.items()}


def posterior_long(p_long: float, answer: str, reliability: float = 1.0) -> float:
    a = ANSWERS.index(answer)
    L = lik(reliability)
    num = p_long * L["long"][a]
    den = num + (1 - p_long) * L["short"][a]
    return float(num / den) if den > 0 else p_long


def robust_commit(pr: Problem) -> dict[str, str]:
    """Options that are optimal whether the blockage is short or long and need no waiting (spare / pickup / reroute): act on them NOW."""
    a, b = solve(pr, 0.02).assignments, solve(pr, 0.98).assignments
    return {pid: o for pid, o in a.items() if b[pid] == o and o != "wait" and o != "defer"}


def cluster_inquiry_value(pr: Problem, p_long: float, *, p_response: float, latency_min: float, cost_sar: float, n_asked: int = 1, reliability: float = 1.0) -> dict[str, Any]:
    """Net value of asking the dispatcher once, with RECOURSE.

    Without asking: one joint plan on the prior, executed now. With asking: parcels whose best option is the same under both extremes are
    committed immediately (no delay); the rest wait for the answer (and lose the decision delay unless they simply wait at the blockage),
    then the remaining plan is re-solved on the posterior for each possible answer. No answer: the deadline passes and we plan on the prior later.
    """
    now = solve(pr, p_long)
    commit = robust_commit(pr) if latency_min > 0 else {}  # with an instant answer there is nothing to pre-commit
    shift = {p.id: (0.0 if p.id in commit else latency_min) for p in pr.parcels}
    shift_silent = {p.id: (0.0 if p.id in commit else latency_min * 1.6) for p in pr.parcels}
    exp_u, detail = 0.0, {}
    for a in ANSWERS:
        L = lik(reliability)
        pa = p_long * L["long"][ANSWERS.index(a)] + (1 - p_long) * L["short"][ANSWERS.index(a)]
        pl = posterior_long(p_long, a, reliability)
        plan = solve(pr, pl, slack_shift=shift, fixed=commit)
        detail[a] = {"p": round(pa * p_response, 4), "posterior_long": round(pl, 3), "objective": round(plan.objective, 2)}
        exp_u += p_response * pa * plan.objective
    silent = solve(pr, p_long, slack_shift=shift_silent, fixed=commit)
    exp_u += (1 - p_response) * silent.objective
    detail["no_response"] = {"p": round(1 - p_response, 4), "objective": round(silent.objective, 2)}
    gross = exp_u - now.objective
    return {"gross": float(gross), "cost": float(cost_sar * n_asked), "net": float(gross - cost_sar * n_asked), "plan_now_objective": round(now.objective, 2), "by_answer": detail,
            "committed_now": commit}


def compare(pr: Problem, p_long: float, true_d: float | None = None, seed: int = 0) -> dict[str, Any]:
    """Coordinated vs independent under the same belief, scored at the true duration if known (else at the belief-weighted duration)."""
    co = solve(pr, p_long)
    ind = independent_plan(pr, p_long, seed=seed)
    ds = [(pr.short_min, 1 - p_long), (pr.long_min, p_long)] if true_d is None else [(true_d, 1.0)]

    def score(assign: dict[str, str], vans: list[str]) -> dict[str, Any]:
        rs = [(w, realised_utility(pr, assign, set(vans), d)) for d, w in ds]
        return {"utility": sum(w * r["utility"] for w, r in rs), "expected_on_time": sum(w * r["expected_on_time"] for w, r in rs), "capacity_violations": rs[0][1]["capacity_violations"]}

    s_co, s_ind = score(co.assignments, co.reroute_vans), score(ind.assignments, ind.reroute_vans)
    return {"coordinated": {**s_co, "solve_ms": round(co.solve_ms, 2), "assignments": co.assignments, "reroute_vans": co.reroute_vans, "spares_used": co.spares_used},
            "independent": {**s_ind, "assignments": ind.assignments, "reroute_vans": ind.reroute_vans, "conflicting_van_decisions": int(ind.utilities["_conflicting_van_decisions"]),
                            "capacity_requests_over_cap": int(ind.utilities["_capacity_requests_over_cap"])},
            "utility_gain": s_co["utility"] - s_ind["utility"]}
