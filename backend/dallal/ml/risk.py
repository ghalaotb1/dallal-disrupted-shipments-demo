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
from dallal.ml.adapters import ADAPTERS, Outcome, abstain
from dallal.ml.pit import NullStore, PointInTimeStore, lade_store
from dallal.tools.bundle import Bundle
from dallal.tools.providers import HeuristicRiskModel, RiskModel, RiskScore


class TrainedRiskModel:
    model_id = "trained-registry"
    basis = "trained"

    def __init__(self, models: dict[str, registry.TrainedModel], fallback: RiskModel | None = None, stores: dict[str, PointInTimeStore] | None = None):
        self.models, self.fallback, self.stores = models, fallback or HeuristicRiskModel(), stores or {}

    def _store(self, mid: str, m: registry.TrainedModel) -> PointInTimeStore:
        if mid not in self.stores:
            self.stores[mid] = lade_store(m.card.extra) if mid.startswith("lade") else NullStore()
        return self.stores[mid]

    def considered(self, world: Bundle, shipment_id: str, facts: dict[str, Any]) -> tuple[list[dict[str, Any]], list[tuple[registry.TrainedModel, registry.Prediction, str | None]]]:
        explicit = (facts or {}).get("ml_features") or {}
        notes: list[dict[str, Any]] = []
        used: list[tuple[registry.TrainedModel, registry.Prediction, str | None]] = []
        for mid, m in self.models.items():
            if mid in explicit:  # a caller-supplied complete row (Model Lab, tests); still contract- and range-checked below
                out = Outcome(explicit[mid], as_of_used=None)
            else:
                ad = ADAPTERS.get(mid)
                out = ad.build(world, shipment_id, m.card, self._store(mid, m)) if ad else abstain("not_bridged", "no adapter registered for this model")
            if not out.ok:
                notes.append({"model": mid, "status": "abstained", "code": out.code, "detail": out.detail, "missing": out.missing})
                continue
            try:
                pred = m.predict(out.features)  # type: ignore[arg-type]
            except registry.ContractError as e:
                notes.append({"model": mid, "status": "abstained", "code": "contract_error", "detail": str(e), "missing": []})
                continue
            if pred is None:
                notes.append({"model": mid, "status": "abstained", "code": "out_of_training_range", "detail": "features outside the range the model was trained on", "missing": [],
                              "features_outside_training_range": m.out_of_domain_features(out.features)})  # type: ignore[arg-type]
                continue
            notes.append({"model": mid, "status": "scored", "code": "ok", "probability": round(pred.probability, 5), "band": pred.band, "features_as_of": out.as_of_used})
            used.append((m, pred, out.as_of_used))
        return notes, used

    def score(self, world: Bundle, shipment_id: str, facts: dict[str, Any]) -> RiskScore:
        notes, used = self.considered(world, shipment_id, facts)
        if not used:
            rs = self.fallback.score(world, shipment_id, facts)
            rs.meta = {**(rs.meta or {}), "source": "heuristic", "trained_models_considered": notes,
                       "why_heuristic": "every trained model abstained: " + "; ".join(f"{n['model']} [{n['code']}]" for n in notes)}
            return rs
        # Different targets are never averaged. The primary model is the one with the best held-out ranking; the rest are reported.
        m, pred, as_of = max(used, key=lambda mp: mp[0].card.metrics["test"]["roc_auc"])
        c = m.card
        try:
            h = self.fallback.score(world, shipment_id, facts)
            heuristic = {"score": h.score, "drivers": h.drivers[:3], "basis": h.basis}
        except Exception:  # noqa: BLE001 - the comparison is informational; it must never break the model path
            heuristic = None
        drivers = [{"family": "model", "label": f"P({c.target}) = {pred.probability:.1%} vs {c.base_rate_valid:.1%} base rate in the source data", "weight": round(pred.probability, 3)}]
        meta = {"source": "model", "target": c.target, "source_data": c.source, "calibration": c.calibration, "base_rate_source": c.base_rate_valid, "test_roc_auc": c.metrics["test"]["roc_auc"],
                "features_as_of": as_of, "caveats": c.caveats[:2], "heuristic_for_comparison": heuristic,
                "also_scored": [{"model": mm.card.model_id, "probability": round(pp.probability, 5), "band": pp.band} for mm, pp, _ in used if mm is not m], "trained_models_considered": notes}
        meta["source_name"] = meta.pop("source_data")
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
