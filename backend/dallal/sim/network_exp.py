"""Network recovery experiment (SYNTHETIC; paired by episode seed): does coordination and one shared question beat the alternatives?

An episode is one shared-cause incident (a blocked corridor). The agents believe P(long blockage) = PRIOR; the truth is drawn from a
(possibly different) rate. Strategies, all scored by the same realised-utility function at the TRUE duration, including the decision delay
that waiting for an answer costs and every message sent:

    independent_naive        every parcel optimises alone on the prior and carries the whole shared cost; first-come capacity repair, losers are deferred
    independent_strong       as above, but shared fixed costs are split by the parcels that could share them and a lost capacity race falls back to the next-best option
    desk_greedy              a strong human desk: parcels worked highest stake first, each taking its best option given what is already committed (no joint optimisation)
    independent_inquiry      every parcel's own agent asks the dispatcher when ITS value of information is positive (N messages), then decides alone
    coordinated_no_inquiry   one joint MILP on the prior
    coordinated_inquiry      ONE value-gated question to the dispatcher with recourse (robust parcels acted on immediately), then re-plan jointly   <- proposal
    coordinated_always_ask   ablation: ask whatever the value of information says
    oracle                   knows the true duration, no delay, no message
Everything is in utility.yaml-style SAR-equivalents; resources, response rates and the answer model are ASSUMPTIONS (printed in the report).

Run: python -I -m dallal.sim.network_exp [episodes_per_regime]   -> docs/experiments/network_recovery.json
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from dallal.agent.v2 import inquiry as iq
from dallal.config import PATHS
from dallal.recovery import network as N

PRIOR = 0.30
STRATS = ("independent_naive", "independent_strong", "desk_greedy", "independent_inquiry", "coordinated_no_inquiry", "coordinated_inquiry", "coordinated_always_ask", "oracle")
SPEC = iq.spec("ask_corridor_status")
P_RESP = iq.response_prob(SPEC, {})
LATENCY = iq.expected_latency_min(SPEC)
COST = iq.cost_sar(SPEC, {})
TIMEOUT = float(SPEC.raw["response"]["timeout_min"])

REGIMES = {
    # name: (n parcels, slack range, spares (count, capacity), pickups, alt route prob, true P(long))
    "tight_scarce": dict(n=(8, 14), slack=(45, 110), spares=(1, 2), pickups=(0, 1), alt=0.4, p_true=0.30),
    "tight_ample": dict(n=(8, 14), slack=(45, 110), spares=(3, 4), pickups=(2, 3), alt=0.7, p_true=0.30),
    "loose": dict(n=(8, 14), slack=(160, 320), spares=(1, 3), pickups=(1, 2), alt=0.6, p_true=0.30),
    "tight_scarce_prior_wrong": dict(n=(8, 14), slack=(45, 110), spares=(1, 2), pickups=(0, 1), alt=0.4, p_true=0.60),
}


def draw_problem(rng: np.random.Generator, reg: dict[str, Any]) -> tuple[N.Problem, bool, float]:
    n = int(rng.integers(*reg["n"]))
    n_vans = int(rng.integers(2, 5))
    parcels = []
    for i in range(n):
        value = float(np.exp(rng.normal(5.8, 0.8)))  # median ~330 SAR, heavy right tail
        svc = rng.choice(["Standard", "Express", "Same-day"], p=[0.5, 0.3, 0.2])
        parcels.append(N.Parcel(f"P{i}", f"V{int(rng.integers(n_vans))}", value, float(rng.uniform(*reg["slack"])), float(rng.uniform(15, 60)), str(svc), bool(rng.random() < 0.4),
                                bool(svc != "Same-day"), bool(rng.random() < 0.85)))
    spares = [N.Spare(f"S{j}", float(rng.uniform(18, 40)), int(rng.integers(1, 4))) for j in range(int(rng.integers(reg["spares"][0], reg["spares"][1] + 1)))]
    pickups = [N.PickupPoint(f"K{j}", float(rng.uniform(15, 35)), int(rng.integers(2, 5))) for j in range(int(rng.integers(reg["pickups"][0], reg["pickups"][1] + 1)))]
    pr = N.Problem(parcels, spares, pickups, bool(rng.random() < reg["alt"]), float(rng.uniform(25, 55)))
    is_long = bool(rng.random() < reg["p_true"])
    d = pr.long_min * float(rng.uniform(0.7, 1.5)) if is_long else pr.short_min * float(rng.uniform(0.6, 1.6))
    return pr, is_long, d


def with_delay(pr: N.Problem, assign: dict[str, str], shift: dict[str, float]) -> N.Problem:
    """Parcels that start an option after waiting for an answer have less slack (a van that just waits at the blockage is not delayed by our deciding)."""
    return replace(pr, parcels=[replace(p, slack_min=p.slack_min - shift.get(p.id, 0.0)) if assign.get(p.id) != "wait" and shift.get(p.id, 0.0) else p for p in pr.parcels])


def score(pr, assign, vans, d, shift=None, n_msgs=0, delay_min=0.0) -> dict[str, Any]:
    r = N.realised_utility(with_delay(pr, assign, shift or {}), assign, set(vans), d)
    return {"utility": r["utility"] - COST * n_msgs - 0.0, "on_time": r["expected_on_time"], "cap_viol": r["capacity_violations"], "messages": n_msgs, "delay_min": delay_min,
            "deferred": sum(1 for o in assign.values() if o == "defer")}


def answer(rng: np.random.Generator, is_long: bool) -> tuple[str | None, float]:
    """(answer id or None, minutes until it arrives or the deadline) drawn from the TRUE response model."""
    if rng.random() > P_RESP:
        return None, TIMEOUT
    probs = N.LIK["long" if is_long else "short"]
    return str(rng.choice(N.ANSWERS, p=np.array(probs) / sum(probs))), float(np.exp(rng.normal(np.log(LATENCY), 0.5)))


def coordinated_with_question(pr: N.Problem, ans: str | None, lat: float, p_prior: float) -> tuple[dict[str, str], list[str], dict[str, float]]:
    commit = N.robust_commit(pr)
    shift = {p.id: (0.0 if p.id in commit else lat) for p in pr.parcels}
    post = N.posterior_long(p_prior, ans) if ans else p_prior
    plan = N.solve(pr, post, slack_shift=shift, fixed=commit)
    return plan.assignments, plan.reroute_vans, shift


def run_episode(seed: int, regime: str) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    pr, is_long, d = draw_problem(rng, REGIMES[regime])
    ans, lat = answer(np.random.default_rng(seed + 7), is_long)
    out: list[dict[str, Any]] = []

    def add(name: str, s: dict[str, Any]) -> None:
        out.append({"regime": regime, "seed": seed, "strategy": name, "is_long": is_long, "n_parcels": len(pr.parcels), **s})

    # oracle
    orc = N.solve(pr, 0.999 if is_long else 0.001)
    add("oracle", score(pr, orc.assignments, orc.reroute_vans, d))
    # independent, no question
    ind = N.independent_plan(pr, PRIOR, seed=seed)
    add("independent_naive", score(pr, ind.assignments, ind.reroute_vans, d))
    ind_sc = N.independent_plan(pr, PRIOR, seed=seed, share_fixed_costs=True, repair="next_best")
    add("independent_strong", score(pr, ind_sc.assignments, ind_sc.reroute_vans, d))
    gr = N.greedy_plan(pr, PRIOR)
    add("desk_greedy", score(pr, gr.assignments, gr.reroute_vans, d))
    # independent, every parcel's own agent decides whether to ask (single-parcel VOI), one message each
    p_by, shift_by, msgs, worst_delay = {}, {}, 0, 0.0
    for p in pr.parcels:
        sub = replace(pr, parcels=[p])
        v = N.cluster_inquiry_value(sub, PRIOR, p_response=P_RESP, latency_min=LATENCY, cost_sar=COST)
        if v["net"] >= 0.4:
            a_i, l_i = answer(np.random.default_rng(seed * 1000 + int(p.id[1:]) + 13), is_long)
            msgs += 1
            p_by[p.id] = N.posterior_long(PRIOR, a_i) if a_i else PRIOR
            shift_by[p.id] = l_i
            worst_delay = max(worst_delay, l_i)
        else:
            p_by[p.id], shift_by[p.id] = PRIOR, 0.0
    ind2 = N.independent_plan(pr, p_by, shift_by, seed=seed, share_fixed_costs=True, repair="next_best")
    add("independent_inquiry", score(pr, ind2.assignments, ind2.reroute_vans, d, shift_by, msgs, worst_delay))
    # coordinated, no question
    co = N.solve(pr, PRIOR)
    add("coordinated_no_inquiry", score(pr, co.assignments, co.reroute_vans, d))
    # coordinated, value-gated single question
    v = N.cluster_inquiry_value(pr, PRIOR, p_response=P_RESP, latency_min=LATENCY, cost_sar=COST)
    if v["net"] >= 0.4:
        a, rv, sh = coordinated_with_question(pr, ans, lat, PRIOR)
        add("coordinated_inquiry", score(pr, a, rv, d, sh, 1, lat) | {"asked": True})
    else:
        add("coordinated_inquiry", score(pr, co.assignments, co.reroute_vans, d) | {"asked": False})
    a, rv, sh = coordinated_with_question(pr, ans, lat, PRIOR)
    add("coordinated_always_ask", score(pr, a, rv, d, sh, 1, lat) | {"asked": True})
    return out


def ci(x: np.ndarray, n_boot: int = 1000, seed: int = 0) -> list[float]:
    rng = np.random.default_rng(seed)
    m = [rng.choice(x, len(x)).mean() for _ in range(n_boot)]
    return [round(float(np.quantile(m, 0.025)), 2), round(float(np.quantile(m, 0.975)), 2)]


def main(n: int) -> None:
    rows = [r for reg in REGIMES for s in range(n) for r in run_episode(s, reg)]
    df = pd.DataFrame(rows)
    orc = df[df.strategy == "oracle"].set_index(["regime", "seed"])["utility"]
    df["regret"] = df.apply(lambda r: orc[(r["regime"], r["seed"])] - r["utility"], axis=1)
    rep: dict[str, Any] = {"origin": "synthetic incidents; utilities in SAR-equivalents under stated assumptions; paired by seed", "episodes_per_regime": n,
                           "assumptions": {"prior_p_long": PRIOR, "dispatcher_response_prob": round(P_RESP, 3), "dispatcher_latency_min": LATENCY, "message_cost_sar": COST, "answer_likelihoods": N.LIK,
                                           "regimes": REGIMES, "pickup_accept": N.PICKUP_ACCEPT, "defer_fail_share": N.DEFER_FAIL_SHARE}, "regimes": {}}
    for reg in REGIMES:
        d = df[df.regime == reg]
        tab = {}
        for s in STRATS:
            x = d[d.strategy == s]
            tab[s] = {"mean_utility": round(float(x.utility.mean()), 1), "mean_regret": round(float(x.regret.mean()), 1), "mean_on_time_parcels": round(float(x.on_time.mean()), 2), "mean_messages": round(float(x.messages.mean()), 2),
                      "mean_deferred": round(float(x.deferred.mean()), 2), "mean_decision_delay_min": round(float(x.delay_min.mean()), 1)}
            if "asked" in x:
                tab[s]["asked_rate"] = round(float(x["asked"].fillna(False).astype(bool).mean()), 2)
        def u(name: str, d: pd.DataFrame = d) -> pd.Series:
            return d[d.strategy == name].set_index("seed").utility

        paired = {}
        for a_, b_ in (("independent_strong", "independent_naive"), ("coordinated_no_inquiry", "independent_strong"), ("coordinated_no_inquiry", "desk_greedy"), ("coordinated_inquiry", "desk_greedy"),
                       ("coordinated_inquiry", "independent_inquiry"), ("coordinated_inquiry", "coordinated_no_inquiry"), ("coordinated_inquiry", "coordinated_always_ask")):
            diff = (u(a_) - u(b_)).to_numpy()
            paired[f"{a_} minus {b_}"] = {"mean_gain": round(float(diff.mean()), 1), "ci95": ci(diff), "win_rate": round(float((diff > 1e-6).mean()), 2), "loss_rate": round(float((diff < -1e-6).mean()), 2)}
        rep["regimes"][reg] = {"strategies": tab, "paired": paired}
        print(reg, json.dumps({k: (v["mean_regret"], v["mean_messages"]) for k, v in tab.items()}))
    (PATHS.docs / "experiments").mkdir(parents=True, exist_ok=True)
    (PATHS.docs / "experiments" / "network_recovery.json").write_text(json.dumps(rep, indent=2) + "\n")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
