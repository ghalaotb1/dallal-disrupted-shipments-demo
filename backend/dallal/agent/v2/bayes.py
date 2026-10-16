"""Ensemble belief over (root cause C, systemic S) with *uncertain* likelihood tables.

Why this replaces the single-table Belief (v1)
----------------------------------------------
v1 treats the hand-set observation tables as exact. They are expert assumptions, so a posterior of 0.93 mixes real evidence with
table error, and decisions made right at a threshold (e.g. 'auto-act if >= 0.8') inherit that error silently.

v2 keeps K plausible versions of every likelihood table (log-normal perturbations of the nominal table, particle 0 = nominal).
Each particle carries its own posterior over (C, S); particles are re-weighted by how well they predicted the evidence seen so
far (proper Bayesian model averaging). Consequences:
  * posteriors are averaged over table uncertainty (less overconfident than the nominal table alone);
  * predictive distributions for the *next* observation include that uncertainty (value-of-information is honest about it);
  * decision robustness is measurable: how often does the best action change across particles?
  * correlated evidence from the same data family is tempered instead of being counted as independent.

All tables remain expert assumptions (`expert_assumption_v1`); this class does not make them data-driven, it makes the agent
aware that they are not.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field

import numpy as np

from dallal.agent.belief import CAUSES, OBSERVATION_MODELS, P_SYSTEMIC_GIVEN_CAUSE, Cause, ObservationModel

NC, NS = len(CAUSES), 2

# Evidence families: tools that read overlapping underlying data. A later member of a family is discounted (exponent) because
# it is not independent of the earlier one.
FAMILY = {"get_journey": "scans", "get_facility_context": "scans", "get_route_context": "telemetry", "check_incident_context": "incident",
          "predict_risk": "model", "get_address_context": "context", "get_recipient_context": "context", "get_pickup_context": "network"}
FAMILY_EXPONENT = 0.65


class ModelBook:
    """Nominal + perturbed likelihood tables for every evidence source (tools and inquiries).

    Perturbation noise is seeded per source NAME, so the same book (same k/sigma/seed) rebuilds identical tables in any order or
    process — required for resuming a checkpointed run.
    """

    def __init__(self, models: dict[str, ObservationModel], k: int = 24, sigma: float = 0.35, seed: int = 0):
        self.models, self.k, self.sigma, self.seed = {}, k, sigma, seed
        self.tables: dict[str, np.ndarray] = {}
        self._temper_cache: dict[tuple[str, float], np.ndarray] = {}
        for name, m in models.items():
            self.register(name, m)

    def register(self, name: str, model: ObservationModel) -> None:
        rng = np.random.default_rng([self.seed, zlib.crc32(name.encode())])
        L = model.matrix()  # [O,C,S]
        noise = np.exp(rng.normal(0.0, self.sigma, size=(self.k, *L.shape)))
        noise[0] = 1.0  # particle 0 is the nominal table
        T = L[None] * noise
        T /= T.sum(axis=1, keepdims=True)
        self.models[name], self.tables[name] = model, T
        self._temper_cache = {k: v for k, v in self._temper_cache.items() if k[0] != name}

    def ensure(self, name: str) -> None:
        """Lazily create the table for an inquiry variant name like 'ask_courier_status|p=0.85'."""
        if name in self.tables:
            return
        from dallal.agent.v2 import inquiry as iq

        parsed = iq.parse_variant(name)
        if parsed is None:
            raise KeyError(name)
        base, p = parsed
        self.register(name, iq.observation_model(iq.spec(base), p))

    def outcomes(self, name: str) -> tuple[str, ...]:
        self.ensure(name)
        return self.models[name].outcomes

    def tempered(self, name: str, exponent: float) -> np.ndarray:
        self.ensure(name)
        if exponent == 1.0:
            return self.tables[name]
        key = (name, exponent)
        if key not in self._temper_cache:
            T = self.tables[name] ** exponent
            self._temper_cache[key] = T / T.sum(axis=1, keepdims=True)
        return self._temper_cache[key]

    def config(self) -> dict:
        return {"k": self.k, "sigma": self.sigma, "seed": self.seed}


def default_book(extra: dict[str, ObservationModel] | None = None, **kw) -> ModelBook:
    models = dict(OBSERVATION_MODELS)
    models["predict_risk"] = RISK_BAND_MODEL  # v2 consumes calibrated risk BANDS, not heuristic driver families
    models.update(extra or {})
    return ModelBook(models, **kw)


def _rows(**kw: tuple[float, ...]) -> dict[Cause, tuple[float, ...]]:
    return {Cause(k): v for k, v in kw.items()}


# P(risk band | cause): a calibrated failure-risk score says little about WHICH cause, a lot about 'healthy vs not'.
RISK_BAND_MODEL = ObservationModel(
    ("low", "elevated", "high"),
    _rows(none=(.84, .13, .03), address_issue=(.30, .38, .32), recipient_unavailable=(.32, .38, .30), attempt_not_completed=(.30, .36, .34),
          route_disruption=(.28, .36, .36), facility_backlog=(.30, .36, .34), pickup_point_unavailable=(.30, .36, .34),
          custody_anomaly=(.25, .35, .40), unknown=(.40, .35, .25)),
    temper=0.7,
)


@dataclass
class EnsembleBelief:
    book: ModelBook
    joint: np.ndarray  # [K,C,S], each particle's posterior sums to 1
    logw: np.ndarray  # [K]
    observed: list[tuple[str, str]] = field(default_factory=list)

    # ── construction ──
    @classmethod
    def from_prior(cls, book: ModelBook, p_cause: dict[Cause, float]) -> EnsembleBelief:
        pc = np.array([p_cause[c] for c in CAUSES], dtype=float)
        pc /= pc.sum()
        ps1 = np.array([P_SYSTEMIC_GIVEN_CAUSE[c] for c in CAUSES])
        j = np.stack([pc * (1 - ps1), pc * ps1], axis=1)
        return cls(book, np.repeat(j[None], book.k, axis=0), np.zeros(book.k))

    def copy(self) -> EnsembleBelief:
        return EnsembleBelief(self.book, self.joint.copy(), self.logw.copy(), list(self.observed))

    # ── marginals ──
    def weights(self) -> np.ndarray:
        w = np.exp(self.logw - self.logw.max())
        return w / w.sum()

    def mix(self) -> np.ndarray:
        return np.tensordot(self.weights(), self.joint, axes=(0, 0))  # [C,S]

    def p_cause_vec(self) -> np.ndarray:
        return self.mix().sum(axis=1)

    def p_cause(self) -> dict[Cause, float]:
        v = self.p_cause_vec()
        return {c: float(v[i]) for i, c in enumerate(CAUSES)}

    def p_systemic(self) -> float:
        return float(self.mix()[:, 1].sum())

    def top(self) -> tuple[Cause, float, float]:
        v = self.p_cause_vec()
        o = np.argsort(-v)
        return CAUSES[o[0]], float(v[o[0]]), float(v[o[0]] - v[o[1]])

    def entropy(self) -> float:
        p = self.mix().ravel()
        p = p[p > 0]
        return float(-(p * np.log2(p)).sum())

    def particle_cause(self) -> np.ndarray:
        """[K,C] per-particle cause marginals (for robustness statistics)."""
        return self.joint.sum(axis=2)

    # ── inference ──
    def exponent_for(self, name: str) -> float:
        fam = FAMILY.get(name)
        if fam and any(FAMILY.get(n) == fam for n, _ in self.observed):
            return FAMILY_EXPONENT
        return 1.0

    def predictive(self, name: str) -> np.ndarray:
        T = self.book.tempered(name, self.exponent_for(name))  # [K,O,C,S]
        w = self.weights()
        return np.einsum("k,koc s,kcs->o".replace(" ", ""), w, T, self.joint)

    def after(self, name: str, outcome: str) -> EnsembleBelief:
        b = self.copy()
        b.update(name, outcome)
        return b

    def update(self, name: str, outcome: str) -> None:
        o = self.book.outcomes(name).index(outcome)
        T = self.book.tempered(name, self.exponent_for(name))[:, o]  # [K,C,S]
        lik = (self.joint * T).sum(axis=(1, 2))  # per-particle marginal likelihood of this observation
        self.joint = self.joint * T / np.maximum(lik, 1e-300)[:, None, None]
        self.logw = self.logw + np.log(np.maximum(lik, 1e-300))
        self.observed.append((name, outcome))

    # ── robustness ──
    def weighted_quantile(self, values: np.ndarray, q: float) -> float:
        o = np.argsort(values)
        cw = np.cumsum(self.weights()[o])
        return float(values[o][np.searchsorted(cw, q)])

    def snapshot(self) -> dict:
        pc = sorted(self.p_cause().items(), key=lambda kv: -kv[1])[:4]
        return {"top": [(c.value, round(p, 4)) for c, p in pc], "p_systemic": round(self.p_systemic(), 4), "entropy_bits": round(self.entropy(), 4),
                "effective_particles": round(float(1.0 / np.sum(self.weights() ** 2)), 2)}

    # ── durable state ──
    def to_json(self) -> dict:
        return {"book": self.book.config(), "joint": self.joint.tolist(), "logw": self.logw.tolist(), "observed": self.observed}

    @classmethod
    def from_json(cls, d: dict, book: ModelBook) -> EnsembleBelief:
        assert d["book"] == book.config(), "belief was produced with a different model book"
        return cls(book, np.array(d["joint"]), np.array(d["logw"]), [tuple(x) for x in d["observed"]])
