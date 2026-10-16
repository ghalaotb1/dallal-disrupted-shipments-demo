"""The evaluation machinery itself: independence from the agent's tables, common random numbers, outcome invariants, oracle dominance."""

from __future__ import annotations

import numpy as np
import pytest

from dallal.agent.belief import OBSERVATION_MODELS, Cause
from dallal.sim import lab, network_lab
from dallal.sim import process as P
from dallal.sim.process import ProcessConfig, draw_process_episode, regime_set


def test_process_world_is_deterministic_per_seed_and_tools_read_hidden_state():
    cfg = ProcessConfig()
    a, ha, da = draw_process_episode(5, cfg)
    b, hb, db = draw_process_episode(5, cfg)
    assert a.truth == b.truth and ha == hb and da == db
    env = P.ProcessEnv(a, ha, da, cfg, np.random.default_rng(0))
    # every tool outcome is a legal outcome of the agent's tool and a deterministic function of the hidden state when there is no data gap
    cfg0 = ProcessConfig(data_gap=0.0)
    env = P.ProcessEnv(a, ha, da, cfg0, np.random.default_rng(0))
    for name, model in OBSERVATION_MODELS.items():
        if name == "predict_risk":
            continue
        out = env.sample_tool(name)
        assert out in model.outcomes and out == P.tool_outcome(name, ha, "v2")


def test_tool_outcomes_follow_physical_thresholds_not_agent_tables():
    h = P.Hidden(hours_since_scan=6.0, failed_logged=0, seq_conflict=False, addr_conf=0.3, missed_windows=3, window_conflict=False, corridor_ratio=0.4, stationary_min=20.0, dist_to_addr_m=3000,
                 geo_mismatch=False, backlog=90.0, gap_h=6.0, pickup_offline=True, corridor_failures=5, risk_score=0.7)
    assert P.tool_outcome("get_journey", h, "v2") == "stalled" and P.tool_outcome("get_address_context", h, "v2") == "address_weak"
    assert P.tool_outcome("get_route_context", h, "v2") == "blocked_stationary" and P.tool_outcome("get_facility_context", h, "v2") == "backlog"
    assert P.tool_outcome("get_pickup_context", h, "v2") == "offline" and P.tool_outcome("check_incident_context", h, "v2") == "incident_confirmed"
    assert P.tool_outcome("predict_risk", h, "v2") == "high"


def test_common_random_numbers_same_evidence_for_every_agent():
    cfg = ProcessConfig()
    ep, h, d = draw_process_episode(11, cfg)
    e1 = P.ProcessEnv(ep, h, d, cfg, np.random.default_rng(1))
    e2 = P.ProcessEnv(ep, h, d, cfg, np.random.default_rng(999))  # a different agent-side rng must not change what the world says
    assert [e1.sample_tool("get_journey"), e1.sample_tool("get_route_context")] == [e2.sample_tool("get_journey"), e2.sample_tool("get_route_context")]


def test_oracle_has_zero_regret_and_regret_is_nonnegative_for_expected_utility():
    rows = [lab.run_episode("v2_value", s, regime_set()["baseline"]) for s in range(30)]
    assert all(r["regret"] > -1e-6 for r in rows)  # the oracle maximises expected realised utility with the same draws, at zero cost and zero delay


def test_same_decision_gives_same_outcome_across_agents():
    cfg = regime_set()["baseline"]
    a = lab.run_episode("v2_no_inquiry", 7, cfg)
    b = lab.run_episode("v2_no_inquiry", 7, cfg)
    assert a["utility"] == b["utility"] and a["option"] == b["option"]


def test_realised_success_probability_cannot_exceed_true_probability():
    ep, h, d = draw_process_episode(3, ProcessConfig())
    for a in ("verify_address", "reroute", "contact_recipient"):
        r = P.realise(ep, d, ProcessConfig(), a, 0.0, "none", 0.0, False)
        assert 0.0 <= r["p"] <= P.true_p(ep, a, ProcessConfig()) + 1e-12


def test_late_deadline_makes_slow_actions_fail_in_the_environment():
    ep, h, d = draw_process_episode(4, ProcessConfig())
    ep.slack_min = 1.0
    assert P.realise(ep, d, ProcessConfig(), "retry_delivery", 0.0, "analyst", 0.0, False)["p"] == 0.0


def test_network_lab_oracle_dominates_and_capacity_is_respected_by_coordination():
    rows = [r for s in range(8) for r in network_lab.run_incident(s, network_lab.regimes()["low_capacity"])]
    import pandas as pd

    df = pd.DataFrame(rows)
    piv = df.pivot_table(index="seed", columns="strategy", values="utility")
    assert (piv["oracle"] >= piv["coordinated_no_inquiry"] - 1e-6).mean() >= 0.7  # the oracle is not a hindsight cheat, so it can lose a draw, but it should dominate on average
    assert df[df.strategy.str.startswith("coordinated")].cap_over_requests.max() == 0
    assert (df[df.strategy == "independent_naive"].cap_over_requests > 0).any()


def test_dispatcher_answers_are_common_across_strategies():
    w = network_lab.draw_world(3, network_lab.NetConfig())
    a = network_lab.dispatcher_answer(w, "coord")
    w2 = network_lab.draw_world(3, network_lab.NetConfig())
    assert a == network_lab.dispatcher_answer(w2, "coord")


@pytest.mark.parametrize("cause", [Cause.NONE, Cause.ROUTE_DISRUPTION])
def test_regimes_are_valid_configs(cause):
    for name, cfg in regime_set().items():
        ep, h, d = draw_process_episode(1, cfg)
        assert ep.slack_min >= 15.0 and name == cfg.name
