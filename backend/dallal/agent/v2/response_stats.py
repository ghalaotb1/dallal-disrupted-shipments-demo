"""Learned responsiveness: how often do people actually answer, and how fast?

The inquiry catalogue starts from expert-assumed response probabilities and latencies. Those numbers drive the value of asking: a question is worth less when
the answer is unlikely or late. In a real operation they are wrong somewhere, and value-based asking that trusts a wrong number asks too often. `ResponseStats`
turns the catalogue values into PRIORS and updates them from the outcomes of questions already asked (Beta posterior for the response probability, shrunk
log-latency for the median delay), so the agent asks less where people do not answer and more where they do. Nothing else about the agent changes.
"""

from __future__ import annotations

import contextlib
import math
from dataclasses import dataclass, field
from typing import Any

from dallal.agent.v2 import inquiry as iq


@dataclass
class ResponseStats:
    prior_strength: float = 8.0  # pseudo-observations behind the catalogue prior
    asked: dict[str, float] = field(default_factory=dict)
    answered: dict[str, float] = field(default_factory=dict)
    log_lat_sum: dict[str, float] = field(default_factory=dict)

    def update(self, spec_id: str, answered: bool, latency_min: float | None = None) -> None:
        self.asked[spec_id] = self.asked.get(spec_id, 0.0) + 1.0
        if answered:
            self.answered[spec_id] = self.answered.get(spec_id, 0.0) + 1.0
            if latency_min and latency_min > 0:
                self.log_lat_sum[spec_id] = self.log_lat_sum.get(spec_id, 0.0) + math.log(latency_min)

    def overrides(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for sid, n in self.asked.items():
            s = iq.spec(sid)
            p0, m0 = s.raw["response"]["p"], s.raw["response"]["latency_median_min"]
            k = self.prior_strength
            a = self.answered.get(sid, 0.0)
            out[sid] = {"p": (a * 1.0 + p0 * k) / (n + k), "latency_median": math.exp((self.log_lat_sum.get(sid, 0.0) + k * math.log(m0)) / (a + k))}
        return out

    @contextlib.contextmanager
    def apply(self):
        tok = iq.OVERRIDES.set(self.overrides())
        try:
            yield
        finally:
            iq.OVERRIDES.reset(tok)

    @classmethod
    def from_store(cls, store: Any, time_scale: float = 1.0, limit: int = 300) -> ResponseStats:
        """Build from the durable inquiry history (closed inquiries only). Latency is the real elapsed time scaled to operational minutes."""
        st = cls()
        rows = store.q("SELECT spec_id,status,asked_real,answered_real FROM inquiries WHERE status IN ('answered','timed_out') ORDER BY asked_real DESC LIMIT ?", (limit,))
        for r in rows:
            ok = r["status"] == "answered"
            lat = (r["answered_real"] - r["asked_real"]) / 60.0 * time_scale if ok and r["answered_real"] else None
            st.update(r["spec_id"], ok, lat)
        return st


@dataclass
class ReliabilityStats:
    """How often does a responder's answer agree with what the operation later establishes? Beta posterior around the catalogue's assumed reliability.
    Needs ground truth AFTER the fact (e.g. the blockage's observed duration), so it is fed from recorded outcomes, never from the answers themselves."""

    prior_reliability: float = 0.85
    prior_strength: float = 8.0
    agree: float = 0.0
    total: float = 0.0

    def update(self, agreed: bool) -> None:
        self.total += 1.0
        self.agree += float(agreed)

    @property
    def reliability(self) -> float:
        return (self.agree + self.prior_reliability * self.prior_strength) / (self.total + self.prior_strength)
