from __future__ import annotations

import numpy as np

from dallal.agent.belief import OBSERVATION_MODELS
from dallal.ml import incident_backtest as ib
from dallal.ml.metrics import binary_report, ece
from dallal.ml.tasks import TASKS
from dallal.tools.builtin import build_registry


def test_every_task_has_honest_status_and_valid_agent_tool():
    reg = build_registry()
    ids = [t.id for t in TASKS]
    assert len(ids) == len(set(ids))
    for t in TASKS:
        assert t.status in {"baseline", "defined", "blocked_no_labels"}
        if t.agent_tool:
            assert t.agent_tool in reg
        if t.status == "blocked_no_labels":
            assert t.source == "none"
    assert {t.id for t in TASKS if t.status == "blocked_no_labels"} == {"cause_classification", "recovery_uplift"}


def test_every_informative_tool_has_an_observation_model():
    for spec in build_registry().all():
        assert (spec.name in OBSERVATION_MODELS) == spec.informative, spec.name


def test_metrics_perfect_and_random():
    y = np.array([0] * 90 + [1] * 10)
    assert binary_report(y, y.astype(float))["roc_auc"] == 1.0
    rng = np.random.default_rng(0)
    r = binary_report(y, rng.random(100))
    assert 0.2 < r["roc_auc"] < 0.8
    # a calibrated predictor has small ECE; a confidently wrong one has large ECE
    p = rng.random(20000)
    y_cal = (rng.random(20000) < p).astype(int)
    assert ece(y_cal, p) < 0.02
    assert ece(y_cal, 1 - p) > 0.3


def test_surge_detector_flags_a_surge_but_not_flat_noise():
    rng = np.random.default_rng(1)
    C = rng.poisson(2.0, size=(24 * 30, 3)).astype(float)
    mean, std = ib.baseline(C)
    clean = ib.alarms(C, mean, std, phi=1.0, z_star=5.0)
    C2 = C.copy()
    C2[24 * 20 + 5, 1] += 40
    assert ib.alarms(C2, mean, std, phi=1.0, z_star=5.0)[24 * 20 + 5, 1]
    assert clean[24 * 15:].sum() <= 2
