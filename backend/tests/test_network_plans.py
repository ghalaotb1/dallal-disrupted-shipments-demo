from __future__ import annotations

import numpy as np
import pytest

from dallal.recovery import network as N
from dallal.service import OpsService


def make(seed: int, n: int = 12, scarce: bool = True, tight: bool = False) -> N.Problem:
    """tight=True: promises are close to what a reroute needs (40 min extra), so the blockage duration genuinely decides the plan."""
    rng = np.random.default_rng(seed)
    lo, hi = (38, 80) if tight else (35, 130)
    parcels = [N.Parcel(f"P{i}", f"V{i % 4}", float(rng.choice([120, 300, 900, 1850])), float(rng.uniform(lo, hi)), float(rng.uniform(10, 40)), str(rng.choice(["Standard", "Express"])), i > 6)
               for i in range(n)]
    spares = [N.Spare("S1", float(rng.uniform(18, 30)), 3 if scarce else 12), N.Spare("S2", float(rng.uniform(20, 35)), 2 if scarce else 12)]
    return N.Problem(parcels, spares, [N.PickupPoint("PP1", 22, 2 if scarce else 12)], alt_extra_min=40.0, short_min=15.0, long_min=100.0)


@pytest.mark.parametrize("seed", range(8))
def test_plan_respects_capacity_van_coupling_and_assigns_every_parcel(seed):
    pr = make(seed)
    for pl in (0.05, 0.5, 0.95):
        sol = N.solve(pr, pl)
        assert set(sol.assignments) == {p.id for p in pr.parcels}
        for s in pr.spares:
            assert sum(o == f"spare:{s.id}" for o in sol.assignments.values()) <= s.capacity
        for k in pr.pickups:
            assert sum(o == f"pickup:{k.id}" for o in sol.assignments.values()) <= k.capacity
        for v in {p.van for p in pr.parcels}:
            stays = {sol.assignments[p.id] for p in pr.parcels if p.van == v and sol.assignments[p.id] in ("wait", "reroute")}
            assert len(stays) <= 1, "one van cannot both wait and reroute"
            assert (v in sol.reroute_vans) == ("reroute" in stays) or not stays


@pytest.mark.parametrize("seed", range(10))
def test_coordination_never_does_worse_than_independent_decisions(seed):
    pr = make(seed)
    for pl in (0.2, 0.5, 0.8):
        assert N.compare(pr, pl, seed=seed)["utility_gain"] >= -1e-6


def test_coordination_gain_is_positive_when_capacity_is_scarce_and_the_cause_is_long():
    gains = [N.compare(make(s), 0.9, true_d=100.0, seed=s)["utility_gain"] for s in range(20)]
    assert np.mean(gains) > 0 and max(gains) > 0


def test_independent_agents_overbook_scarce_capacity():
    over = [N.compare(make(s), 0.9, true_d=100.0, seed=s)["independent"]["capacity_requests_over_cap"] for s in range(20)]
    assert sum(over) > 0


def test_posterior_moves_the_right_way():
    assert N.posterior_long(0.3, "blocked_long") > 0.8
    assert N.posterior_long(0.3, "slow_short") < 0.1
    assert N.posterior_long(0.3, "dont_know") == pytest.approx(0.3, abs=0.1)


def test_instant_free_certain_answer_has_non_negative_value():
    for s in range(6):
        v = N.cluster_inquiry_value(make(s), 0.4, p_response=1.0, latency_min=0.0, cost_sar=0.0)
        assert v["gross"] >= -1e-6, "free, instant evidence can never hurt (Blackwell)"


def test_asking_is_declined_when_the_hedge_is_already_right():
    nets = [N.cluster_inquiry_value(make(s), 0.9, p_response=0.95, latency_min=5, cost_sar=0.55)["net"] for s in range(8)]
    assert np.mean(nets) < 0, "a question that cannot change a hedged plan and delays it is not worth asking"


def test_blockage_duration_decides_the_plan_when_promises_are_tight():
    for seed in range(5):
        pr = make(seed, scarce=True, tight=True)
        short, long = N.solve(pr, 0.02).assignments, N.solve(pr, 0.98).assignments
        waits_short, waits_long = sum(o == "wait" for o in short.values()), sum(o == "wait" for o in long.values())
        assert waits_short > waits_long, "a short blockage should keep more parcels waiting than a long one"
        assert short != long


# ── service-level plan lifecycle ────────────────────────────────────────────
def snapshot(p_long: float, n: int = 10, contactable: bool = True) -> dict:
    return {"incidentId": "INC-T", "scope": "corridor", "scopeId": "DK-04", "now": 0, "belief": {"pLong": p_long}, "dispatcherContactable": contactable,
            "parcels": [{"id": f"P{i}", "van": f"V{i % 3}", "value": [120, 300, 900, 1850][i % 4], "slackMin": 42 + 4 * i, "remainingMin": 20} for i in range(n)],
            "resources": {"spares": [{"id": "S1", "etaMin": 20, "capacity": 3}, {"id": "S2", "etaMin": 28, "capacity": 2}], "pickups": [{"id": "PP1", "travelMin": 22, "capacity": 2}],
                          "alt": {"available": True, "extraMin": 40}}}


def test_plan_asks_once_for_the_whole_incident_and_replans_on_the_shared_answer():
    svc = OpsService(time_scale=60)
    plan = svc.plans.create(snapshot(0.2))
    assert plan["status"] == "awaiting_evidence" and len(plan["inquiries"]) == 1
    assert plan["inquiries"][0]["scope"] == "corridor" and plan["inquiries"][0]["delivery_mode"] == "sandbox" and plan["inquiries"][0]["real_delivery"] is False
    before = plan["solution"]["assignments"]
    svc.sandbox_reply(plan["inquiries"][0]["inquiry_id"], "button", answer_id="blocked_long")
    after = svc.plans.view(plan["plan_id"])
    assert after["status"] == "ready" and after["p_long"] > 0.7
    assert after["solution"]["assignments"] != before, "one answer must change the response for several shipments"
    assert sum(a != b for a, b in zip(after["solution"]["assignments"].values(), before.values(), strict=False)) >= 2


def test_plan_does_not_ask_when_the_prior_already_favours_a_long_blockage():
    plan = OpsService(time_scale=60).plans.create(snapshot(0.9))
    assert plan["status"] == "ready" and plan["evidence"]["asked"] is False and plan["inquiries"] == []


def test_plan_without_a_reachable_dispatcher_plans_on_the_prior():
    plan = OpsService(time_scale=60).plans.create(snapshot(0.2, contactable=False))
    assert plan["status"] == "ready" and not plan["evidence"]["asked"]


def test_timeout_resolves_the_plan_on_the_prior():
    svc = OpsService(time_scale=60)
    plan = svc.plans.create(snapshot(0.2))
    svc.expire(plan["inquiries"][0]["inquiry_id"])
    done = svc.plans.view(plan["plan_id"])
    assert done["status"] == "ready" and done["evidence"]["answer"]["id"] is None and done["p_long"] == pytest.approx(0.2)


def test_plan_approval_is_supervisor_only_and_execution_is_simulated_and_logged():
    svc = OpsService(time_scale=60)
    plan = svc.plans.create(snapshot(0.9))
    with pytest.raises(PermissionError):
        svc.plans.decide(plan["plan_id"], "approve", "analyst-1", "analyst")
    out = svc.plans.decide(plan["plan_id"], "approve", "supervisor-1", "supervisor")
    assert out["status"] == "executed_simulated" and len(out["executed"]) == 10
    rows = svc.store.ledger()
    assert sum(r["table"] == "action" for r in rows) == 10
    assert all(r["assignment"] == "human" and r["approval_level"] == "supervisor" for r in rows if r["table"] == "action")
    assert all(r["kind"] == "pending" for r in rows if r["table"] == "outcome"), "outcomes are never fabricated"


def test_cannot_approve_before_the_shared_answer_arrives_but_can_reject():
    svc = OpsService(time_scale=60)
    plan = svc.plans.create(snapshot(0.2))
    with pytest.raises(ValueError):
        svc.plans.decide(plan["plan_id"], "approve", "s", "supervisor")
    assert svc.plans.decide(plan["plan_id"], "reject", "s", "supervisor")["status"] == "rejected"


def test_plan_view_carries_the_coordinated_vs_independent_comparison():
    plan = OpsService(time_scale=60).plans.create(snapshot(0.9))
    c = plan["comparison"]
    assert c["gain"] >= 0 and c["messages_coordinated"] <= c["messages_independent_equivalent"]


def test_greedy_desk_respects_capacity_and_van_consistency():
    pr = N.Problem([N.Parcel(f"P{i}", "V0" if i < 3 else "V1", 400.0, 50.0, 30.0, "Express") for i in range(6)], [N.Spare("S1", 20.0, 2)], [N.PickupPoint("K1", 20.0, 1)], True, 40.0)
    g = N.greedy_plan(pr, 0.9)
    assert sum(1 for o in g.assignments.values() if o == "spare:S1") <= 2 and sum(1 for o in g.assignments.values() if o == "pickup:K1") <= 1
    for v in ("V0", "V1"):  # a van cannot both reroute and have a parcel that waits on it
        on_van = {g.assignments[p.id] for p in pr.parcels if p.van == v}
        assert not ({"wait", "reroute"} <= on_van)


def test_independent_next_best_repair_never_defers_when_waiting_is_possible():
    pr = N.Problem([N.Parcel(f"P{i}", f"V{i % 2}", 500.0, 40.0, 30.0, "Same-day") for i in range(8)], [N.Spare("S1", 20.0, 1)], [], False, 40.0)
    naive = N.independent_plan(pr, 0.9)
    strong = N.independent_plan(pr, 0.9, share_fixed_costs=True, repair="next_best")
    assert sum(o == "defer" for o in strong.assignments.values()) <= sum(o == "defer" for o in naive.assignments.values())
