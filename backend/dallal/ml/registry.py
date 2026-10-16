"""Model artifacts, feature contracts and calibrated inference.

Rules this module enforces (each exists because of a way a risk model can quietly mislead):
  * a model is only ever asked about the features it was trained on - missing ones raise `ContractError`; nothing is imputed;
  * inputs outside the training range are reported (`out_of_range`) and, beyond a tolerance, make the model abstain rather than
    extrapolate into a regime it has never seen (a same-day Riyadh parcel is not a ten-day Brazilian order);
  * every output is a probability of THIS model's own target on the SOURCE population, calibrated on a later validation window.
    It is never presented as a probability of an SPL outcome, and never merged with a model of a different target;
  * artifacts carry their card (data window, split, metrics, caveats) and a content hash that is checked on load.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from dallal.config import PATHS

ARTIFACTS = PATHS.artifacts


class ContractError(ValueError):
    """The input does not satisfy the model's feature contract (missing / non-numeric / non-finite)."""


@dataclass
class FeatureSpec:
    name: str
    lo: float  # 0.5th percentile of the training data
    hi: float  # 99.5th percentile
    describe: str = ""


@dataclass
class ModelCard:
    model_id: str
    task_id: str
    target: str
    source: str
    licence: str
    unit: str
    as_of: str
    algorithm: str
    calibration: str
    features: list[FeatureSpec]
    split: dict[str, Any]
    metrics: dict[str, Any]
    baselines: dict[str, Any]
    base_rate_train: float
    base_rate_valid: float
    band_thresholds: dict[str, float]  # calibrated-probability cut points for low | elevated | high
    caveats: list[str]
    trained_at: str
    sha256: str = ""
    extrapolation_tolerance: float = 0.25  # fraction of range beyond [lo, hi] tolerated per feature before abstaining
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


class Calibrator:
    """Monotone map from raw model score to probability: isotonic or Platt, chosen on held-out validation data."""

    def __init__(self, kind: str, fitted: Any):
        self.kind, self.fitted = kind, fitted

    @staticmethod
    def _logit(p: np.ndarray) -> np.ndarray:
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p)).reshape(-1, 1)

    @classmethod
    def fit(cls, kind: str, raw: np.ndarray, y: np.ndarray) -> Calibrator:
        if kind == "isotonic":
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            iso.fit(raw, y)
            return cls(kind, iso)
        if kind == "platt":
            lr = LogisticRegression(C=1e6, max_iter=1000)
            lr.fit(cls._logit(raw), y)
            return cls(kind, lr)
        raise ValueError(kind)

    def __call__(self, raw: np.ndarray) -> np.ndarray:
        if self.kind == "isotonic":
            return np.asarray(self.fitted.predict(raw), dtype="float64")
        return self.fitted.predict_proba(self._logit(raw))[:, 1]


@dataclass
class Prediction:
    probability: float
    band: str
    raw_score: float
    out_of_range: list[str]
    model_id: str


class TrainedModel:
    def __init__(self, estimator: Any, calibrator: Calibrator, card: ModelCard):
        self.estimator, self.calibrator, self.card = estimator, calibrator, card

    @property
    def feature_names(self) -> list[str]:
        return [f.name for f in self.card.features]

    def _frame(self, rows: pd.DataFrame | list[dict[str, Any]] | dict[str, Any]) -> pd.DataFrame:
        df = pd.DataFrame([rows] if isinstance(rows, dict) else rows)
        missing = [n for n in self.feature_names if n not in df.columns or df[n].isna().any()]
        if missing:
            raise ContractError(f"{self.card.model_id} needs {missing}; refusing to impute")
        x = df[self.feature_names].apply(pd.to_numeric, errors="coerce")
        if not np.isfinite(x.to_numpy(dtype="float64")).all():
            raise ContractError(f"{self.card.model_id}: non-numeric or non-finite feature values")
        return x

    def out_of_range(self, x: pd.DataFrame) -> list[list[str]]:
        """Per row, the features outside the training range by more than the tolerance (abstain-worthy)."""
        bad: list[list[str]] = [[] for _ in range(len(x))]
        for f in self.card.features:
            span = max(f.hi - f.lo, 1e-9)
            v = x[f.name].to_numpy(dtype="float64")
            off = np.maximum(f.lo - v, v - f.hi) / span
            for i in np.flatnonzero(off > self.card.extrapolation_tolerance):
                bad[i].append(f.name)
        return bad

    def raw(self, x: pd.DataFrame) -> np.ndarray:
        return np.asarray(self.estimator.predict_proba(x)[:, 1], dtype="float64")

    def predict_proba(self, rows: pd.DataFrame | list[dict[str, Any]] | dict[str, Any]) -> np.ndarray:
        x = self._frame(rows)
        return self.calibrator(self.raw(x))

    def band_of(self, p: float) -> str:
        t = self.card.band_thresholds
        return "high" if p >= t["high"] else "elevated" if p >= t["elevated"] else "low"

    def predict(self, row: dict[str, Any]) -> Prediction | None:
        """One calibrated prediction, or None when the input is outside the domain this model was trained on."""
        x = self._frame(row)
        oor = self.out_of_range(x)[0]
        if oor:
            return None
        r = float(self.raw(x)[0])
        p = float(self.calibrator(np.array([r]))[0])
        return Prediction(p, self.band_of(p), r, oor, self.card.model_id)

    def out_of_domain_features(self, row: dict[str, Any]) -> list[str]:
        return self.out_of_range(self._frame(row))[0]


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def save(model: TrainedModel, root: Path | None = None) -> Path:
    d = (root or ARTIFACTS) / model.card.model_id
    d.mkdir(parents=True, exist_ok=True)
    blob = d / "model.joblib"
    joblib.dump({"estimator": model.estimator, "calibrator": model.calibrator}, blob, compress=3)
    model.card.sha256 = _hash(blob)
    (d / "card.json").write_text(json.dumps(model.card.to_json(), indent=2, default=str) + "\n")
    return d


def load(model_id: str, root: Path | None = None) -> TrainedModel:
    d = (root or ARTIFACTS) / model_id
    raw = json.loads((d / "card.json").read_text())
    raw["features"] = [FeatureSpec(**f) for f in raw["features"]]
    card = ModelCard(**raw)
    if _hash(d / "model.joblib") != card.sha256:
        raise ContractError(f"{model_id}: artifact hash mismatch; refusing to load")
    blob = joblib.load(d / "model.joblib")
    return TrainedModel(blob["estimator"], blob["calibrator"], card)


def available(root: Path | None = None) -> list[str]:
    d = root or ARTIFACTS
    return sorted(p.parent.name for p in d.glob("*/card.json")) if d.exists() else []
