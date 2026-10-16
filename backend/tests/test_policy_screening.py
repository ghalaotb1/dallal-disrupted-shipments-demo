"""Screening trigger, watch flag, and the out-of-pattern autonomy gate."""

from __future__ import annotations

import numpy as np

from dallal.agent.v2.runtime import AgentRuntimeV2
from dallal.data.augment.scenarios import SCENARIOS
from dallal.sim import lab
from dallal.sim.process import regime_set


def test_screening_trigger_consults_the_risk_model_first():
    b = SCENARIOS["healthy"](3)
    b.trigger = {"kind": "slow_task_watch"}
    res = AgentRuntimeV2(mode="no_inquiry").start(b)
    assert [s["tool"] for s in res.run.steps][:2] == ["get_shipment", "predict_risk"]


def test_p_unknown_gate_blocks_automation_but_not_other_decisions():
    cfg = regime_set()["baseline"]
    base = [lab.run_episode("v2_value", s, cfg) for s in range(200, 260)]
    strict = [lab.run_episode("v2_value", s, cfg, policy={"max_p_unknown": 0.0}) for s in range(200, 260)]
    assert sum(r["auto"] for r in strict) == 0 and sum(r["auto"] for r in base) > 0
    assert all(np.isfinite(r["utility"]) for r in strict)
