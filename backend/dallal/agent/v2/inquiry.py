"""Inquiry catalogue -> observation models, response models, and bilingual messages."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from dallal.agent.belief import CAUSES, Cause, ObservationModel

SPEC = Path(__file__).with_name("inquiries.yaml")
NO_RESPONSE = "no_response"
RECIPIENT_RESPONSIVENESS = {"high": 1.25, "medium": 1.0, "low": 0.6}


@lru_cache(maxsize=1)
def catalogue() -> dict[str, Any]:
    return yaml.safe_load(SPEC.read_text())


@dataclass(frozen=True)
class InquirySpec:
    id: str
    raw: dict[str, Any]

    @property
    def target(self) -> str:
        return self.raw["target"]

    @property
    def scope(self) -> str:
        return self.raw["scope"]

    @property
    def answers(self) -> list[dict[str, str]]:
        return self.raw["answers"]

    @property
    def outcomes(self) -> tuple[str, ...]:
        return tuple(a["id"] for a in self.answers) + (NO_RESPONSE,)


def spec(inquiry_id: str) -> InquirySpec:
    return InquirySpec(inquiry_id, catalogue()["inquiries"][inquiry_id])


def all_specs() -> list[InquirySpec]:
    return [InquirySpec(i, r) for i, r in catalogue()["inquiries"].items()]


# ── applicability and the case-specific response model ────────────────────────────────────────────────────────────────
def contact_allowed_now(now: pd.Timestamp) -> bool:
    q = catalogue()["quiet_hours_local"]
    t = now.hour * 60 + now.minute
    s = int(q["start"][:2]) * 60 + int(q["start"][3:])
    e = int(q["end"][:2]) * 60 + int(q["end"][3:])
    return not (t >= s or t < e)  # window wraps past midnight


def predicates_for(facts: dict[str, Any], now: pd.Timestamp) -> dict[str, bool]:
    return {
        "recipient_contactable": bool(facts.get("recipient_opt_in")) and bool(facts.get("recipient_phone")) and contact_allowed_now(now)
        and (facts.get("recipient_messages_24h") or 0) < catalogue()["max_recipient_messages_24h"],
        "courier_contactable": bool(facts.get("courier_id")) and bool(facts.get("courier_phone", True)),
        "dispatcher_contactable": bool(facts.get("dispatcher_contactable", True)),
        "branch_contactable": bool(facts.get("origin_node_id")) and bool(facts.get("branch_contactable", True)),
        "corridor_known": bool(facts.get("corridor_id")),
        "delivered_scan_present": bool(facts.get("delivered")),
    }


def applicable(s: InquirySpec, facts: dict[str, Any], now: pd.Timestamp) -> bool:
    p = predicates_for(facts, now)
    return all(p.get(r, False) for r in s.raw.get("requires", []))


def response_prob(s: InquirySpec, facts: dict[str, Any]) -> float:
    base = s.raw["response"]["p"]
    if s.target == "recipient":
        base *= RECIPIENT_RESPONSIVENESS.get(facts.get("recipient_responsiveness") or "medium", 1.0)
    return float(min(0.97, max(0.03, base)))


def expected_latency_min(s: InquirySpec) -> float:
    r = s.raw["response"]
    return float(r["latency_median_min"] * math.exp(r["latency_sigma"] ** 2 / 2))


def cost_sar(s: InquirySpec, facts: dict[str, Any]) -> float:
    c = s.raw["cost"]
    fatigue = 0.0
    if s.target == "recipient":
        fatigue = 2.5 * (facts.get("recipient_messages_24h") or 0)
    return float(c["comm_sar"] + c["friction_sar"] + fatigue)


def observation_model(s: InquirySpec, p_resp: float) -> ObservationModel:
    """P(outcome | cause, systemic) over answers + no_response, for this case's response probability."""
    rows: dict[Cause, tuple[float, ...]] = {}
    factor = s.raw.get("response_cause_factor", {})
    for c in CAUSES:
        r = float(min(0.99, p_resp * factor.get(c.value, 1.0)))
        a = np.array(s.raw["likelihood"][c.value], dtype=float)
        a /= a.sum()
        rows[c] = tuple((r * a).tolist() + [1.0 - r])
    by_s = None
    s1 = s.raw.get("by_systemic_s1")
    if s1:
        by_s = (tuple([1.0] * len(s1) + [1.0]), tuple(list(s1) + [1.0]))
    return ObservationModel(s.outcomes, rows, by_s)


def variant_name(inquiry_id: str, p_resp: float) -> str:
    """Observation-source name that encodes the response probability, so a checkpoint can rebuild the identical table."""
    return f"{inquiry_id}|p={p_resp:.2f}"


def parse_variant(name: str) -> tuple[str, float] | None:
    if "|p=" not in name:
        return None
    base, p = name.split("|p=")
    return base, float(p)


# ── messages ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def render_question(s: InquirySpec, facts: dict[str, Any], lang: str = "ar") -> str:
    fmt = {"window": facts.get("window_text", "14:00-18:00"), "shipment": facts.get("shipment_id", ""), "corridor": facts.get("corridor_id", ""),
           "branch": facts.get("branch_name") or facts.get("origin_node_id", "")}
    return s.raw["question"][lang].format(**fmt)


def answer_labels(s: InquirySpec, lang: str = "ar") -> list[dict[str, str]]:
    return [{"id": a["id"], "title": a[lang], "title_en": a["en"]} for a in s.answers]
