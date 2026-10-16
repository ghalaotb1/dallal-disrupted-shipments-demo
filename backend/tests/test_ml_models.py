"""Model registry: feature contract, abstention, hash check, calibration, provider fallback. Uses a tiny synthetic fit - no dataset needed."""

import json

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from dallal.data.augment.scenarios import SCENARIOS
from dallal.ml import registry
from dallal.ml.risk import TrainedRiskModel
from dallal.tools.providers import HeuristicRiskModel


def _toy(tmp_path, n: int = 4000):
    rng = np.random.default_rng(0)
    x = pd.DataFrame({"a": rng.normal(size=n), "b": rng.uniform(0, 10, n)})
    y = (rng.uniform(size=n) < 1 / (1 + np.exp(-(1.5 * x["a"] - 2.5)))).astype(int)
    est = LogisticRegression().fit(x, y)
    raw = est.predict_proba(x)[:, 1]
    cal = registry.Calibrator.fit("isotonic", raw, y)
    p = cal(raw)
    card = registry.ModelCard(
        "toy_v1", "toy", "toy target", "synthetic", "n/a", "row", "now", "logreg", "isotonic",
        [registry.FeatureSpec(n, float(np.quantile(x[n], .005)), float(np.quantile(x[n], .995))) for n in ("a", "b")],
        {}, {"test": {"roc_auc": 0.8}}, {}, float(y.mean()), float(y.mean()), {"elevated": float(np.quantile(p, .85)), "high": float(np.quantile(p, .95))}, [], "t")
    m = registry.TrainedModel(est, cal, card)
    registry.save(m, tmp_path)
    return m


def test_roundtrip_and_hash_check(tmp_path):
    _toy(tmp_path)
    m = registry.load("toy_v1", tmp_path)
    assert 0 <= m.predict({"a": 1.0, "b": 5.0}).probability <= 1  # type: ignore[union-attr]
    (tmp_path / "toy_v1" / "model.joblib").write_bytes(b"tampered")
    with pytest.raises(registry.ContractError, match="hash"):
        registry.load("toy_v1", tmp_path)


def test_missing_feature_is_refused_not_imputed(tmp_path):
    m = _toy(tmp_path)
    with pytest.raises(registry.ContractError, match="refusing to impute"):
        m.predict({"a": 1.0})
    with pytest.raises(registry.ContractError):
        m.predict({"a": 1.0, "b": float("nan")})


def test_out_of_range_input_abstains(tmp_path):
    m = _toy(tmp_path)
    assert m.predict({"a": 0.0, "b": 5.0}) is not None
    assert m.predict({"a": 0.0, "b": 500.0}) is None  # far outside the training range
    assert m.out_of_domain_features({"a": 0.0, "b": 500.0}) == ["b"]


def test_calibration_is_close_in_sample(tmp_path):
    m = _toy(tmp_path)
    rng = np.random.default_rng(1)
    x = pd.DataFrame({"a": rng.normal(size=20000), "b": rng.uniform(0, 10, 20000)})
    y = (rng.uniform(size=20000) < 1 / (1 + np.exp(-(1.5 * x["a"] - 2.5)))).astype(int)
    p = m.predict_proba(x)
    assert abs(p.mean() - y.mean()) < 0.01


def test_provider_scores_with_a_feature_row_and_falls_back_without(tmp_path):
    m = _toy(tmp_path)
    prov = TrainedRiskModel({"toy_v1": m}, HeuristicRiskModel())
    w = SCENARIOS["healthy"](3)
    rs = prov.score(w, w.subject_id, {"ml_features": {"toy_v1": {"a": 2.0, "b": 5.0}}})
    assert rs.basis == "trained:toy_v1" and rs.probability is not None and rs.band in {"low", "elevated", "high"}
    fb = prov.score(w, w.subject_id, {})
    assert fb.basis == "prototype-heuristic" and fb.meta["trained_models_considered"][0]["status"] == "no_feature_row"
    ood = prov.score(w, w.subject_id, {"ml_features": {"toy_v1": {"a": 0.0, "b": 900.0}}})
    assert ood.basis == "prototype-heuristic" and ood.meta["trained_models_considered"][0]["status"] == "out_of_domain"


@pytest.mark.realdata
def test_shipped_artifacts_load_and_match_their_cards():
    ids = registry.available()
    if not ids:
        pytest.skip("no artifacts")
    for i in ids:
        m = registry.load(i)
        t = m.card.metrics["test"]
        assert t["roc_auc"] > 0.6 and t["brier"] <= t["brier_prevalence_baseline"] * 1.02  # no worse than the base-rate forecast
        assert json.loads(json.dumps(m.card.to_json(), default=str))["sha256"] == m.card.sha256
