"""Trained, calibrated risk models behind the agent's `predict_risk` tool.

The provider only scores a case for which the caller supplies a model's full feature row (`facts["ml_features"][model_id]`).
Building such a row from an operational bundle is a data-adapter job that depends on the source system; until an SPL adapter
exists the three public-data models are exercised through the Model Lab and real-data replays, and cases without a usable row
fall back to the transparent heuristic - with the reason recorded in the tool result. Nothing is imputed, nothing extrapolated.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from dallal.ml import registry
from dallal.tools.bundle import Bundle
from dallal.tools.providers import HeuristicRiskModel, RiskModel, RiskScore


class TrainedRiskModel:
    model_id = "trained-registry"
    basis = "trained"

    def __init__(self, models: dict[str, registry.TrainedModel], fallback: RiskModel | None = None):
        self.models, self.fallback = models, fallback or HeuristicRiskModel()

    def considered(self, ml_features: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[tuple[registry.TrainedModel, registry.Prediction]]]:
        notes: list[dict[str, Any]] = []
        used: list[tuple[registry.TrainedModel, registry.Prediction]] = []
        for mid, m in self.models.items():
            row = ml_features.get(mid)
            if row is None:
                notes.append({"model": mid, "status": "no_feature_row", "needs": m.feature_names})
                continue
            try:
                pred = m.predict(row)
            except registry.ContractError as e:
                notes.append({"model": mid, "status": "contract_error", "detail": str(e)})
                continue
            if pred is None:
                notes.append({"model": mid, "status": "out_of_domain", "features_outside_training_range": m.out_of_domain_features(row)})
                continue
            notes.append({"model": mid, "status": "scored", "probability": round(pred.probability, 5), "band": pred.band})
            used.append((m, pred))
        return notes, used

    def score(self, world: Bundle, shipment_id: str, facts: dict[str, Any]) -> RiskScore:
        notes, used = self.considered((facts or {}).get("ml_features") or {})
        if not used:
            rs = self.fallback.score(world, shipment_id, facts)
            rs.meta = {**(rs.meta or {}), "trained_models_considered": notes, "why_heuristic": "no trained model had a usable in-domain feature row"}
            return rs
        # Different targets are never averaged. The primary model is the one with the best held-out ranking; the rest are reported.
        m, pred = max(used, key=lambda mp: mp[0].card.metrics["test"]["roc_auc"])
        c = m.card
        drivers = [{"family": "model", "label": f"P({c.target}) = {pred.probability:.1%} vs {c.base_rate_valid:.1%} base rate in the source data", "weight": round(pred.probability, 3)}]
        meta = {"target": c.target, "source": c.source, "calibration": c.calibration, "base_rate_source": c.base_rate_valid, "test_roc_auc": c.metrics["test"]["roc_auc"],
                "caveats": c.caveats[:2], "also_scored": [{"model": mm.card.model_id, "probability": round(pp.probability, 5), "band": pp.band} for mm, pp in used if mm is not m],
                "trained_models_considered": notes}
        return RiskScore(score=round(pred.probability, 4), drivers=drivers, model_id=c.model_id, basis=f"trained:{c.model_id}", band=pred.band, probability=pred.probability, meta=meta)


@lru_cache(maxsize=1)
def default_risk_model() -> RiskModel:
    ids = registry.available()
    if not ids:
        return HeuristicRiskModel()
    models = {}
    for i in ids:
        try:
            models[i] = registry.load(i)
        except Exception:  # noqa: BLE001 - a corrupt artifact must never take the agent down; it just is not used
            continue
    return TrainedRiskModel(models) if models else HeuristicRiskModel()
