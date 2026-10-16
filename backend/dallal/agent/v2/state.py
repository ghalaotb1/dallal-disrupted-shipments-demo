"""Durable case state for v2 runs: JSON-serialisable so a run can pause for an answer and resume in another process."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from dallal.agent.state import CaseState, Evidence, ToolCall
from dallal.agent.v2.bayes import EnsembleBelief, ModelBook


def _json_safe(o: Any) -> Any:
    return json.loads(json.dumps(o, default=_default))


def _default(o: Any) -> Any:
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


@dataclass
class PendingInquiry:
    inquiry_id: str
    spec_id: str
    variant: str  # observation-source name incl. response probability
    target: str
    scope: str
    lang: str
    question: str
    answers: list[dict[str, str]]
    mode: str
    template: str | None
    asked_at_min: float  # virtual minutes since as_of
    timeout_min: float
    p_response: float
    recipient_ref: str  # opaque handle/phone (sandbox ids never route to a real phone)
    receipt: dict[str, Any] = field(default_factory=dict)
    net_voi_at_ask: float = 0.0
    needs_review: bool = False


@dataclass
class CaseStateV2(CaseState):
    virtual_min: float = 0.0  # minutes elapsed since as_of (tool + answer latency)
    asked: list[str] = field(default_factory=list)  # inquiry spec ids already asked in this run
    pending: PendingInquiry | None = None
    inquiries: list[dict[str, Any]] = field(default_factory=list)  # audit log of every inquiry and its outcome
    engine: str = "v2"
    mode: str = "value"
    late: list[dict[str, Any]] = field(default_factory=list)
    utility_table: list[dict[str, Any]] = field(default_factory=list)
    stability: float | None = None

    @property
    def now(self) -> pd.Timestamp:
        return pd.Timestamp(self.as_of) + pd.Timedelta(minutes=self.virtual_min)

    def info_calls(self) -> int:
        return sum(1 for c in self.calls if c.outcome is not None and not c.tool.startswith("ask_"))


def state_to_json(st: CaseStateV2) -> dict[str, Any]:
    calls = []
    for c in st.calls:
        calls.append({"index": c.index, "tool": c.tool, "args": c.args, "reason": c.reason, "status": c.status, "summary": c.summary, "facts": c.facts,
                      "outcome": c.outcome, "belief_after": c.belief_after, "planner_table": c.planner_table, "duration_ms": c.duration_ms,
                      "provenance": c.provenance, "phase": getattr(c, "phase", None), "source": getattr(c, "source", None),
                      "t_min": getattr(c, "t_min", 0.0), "data": _json_safe(getattr(c, "data", {}))})
    return _json_safe({
        "subject_id": st.subject_id, "trigger": st.trigger, "as_of": st.as_of.isoformat(), "facts": st.facts, "belief": st.belief.to_json() if st.belief else None,
        "calls": calls, "evidence": [vars(e) for e in st.evidence], "incident": st.incident, "diagnosis": st.diagnosis, "ranked_actions": st.ranked_actions,
        "policy": st.policy, "escalation": st.escalation, "budget": st.budget, "virtual_min": st.virtual_min, "asked": st.asked,
        "pending": None if st.pending is None else vars(st.pending), "inquiries": st.inquiries, "mode": st.mode, "late": st.late,
        "utility_table": st.utility_table, "stability": st.stability,
    })


def state_from_json(d: dict[str, Any], book: ModelBook) -> CaseStateV2:
    st = CaseStateV2(d["subject_id"], d["trigger"], pd.Timestamp(d["as_of"]), budget=d["budget"])
    st.facts = d["facts"]
    if st.facts and st.facts.get("promised_end_ts") is not None:
        st.facts["promised_end_ts"] = pd.Timestamp(st.facts["promised_end_ts"])
    st.belief = EnsembleBelief.from_json(d["belief"], book) if d["belief"] else None
    for c in d["calls"]:
        tc = ToolCall(c["index"], c["tool"], c["args"], c["reason"], c["status"], c["summary"], c["facts"], c["outcome"], c["belief_after"], c["planner_table"],
                      c["duration_ms"], c["provenance"])
        tc.phase, tc.source, tc.data, tc.t_min = c["phase"], c["source"], c["data"], c.get("t_min", 0.0)  # type: ignore[attr-defined]
        st.calls.append(tc)
    st.evidence = [Evidence(**e) for e in d["evidence"]]
    st.incident, st.diagnosis, st.ranked_actions, st.policy, st.escalation = d["incident"], d["diagnosis"], d["ranked_actions"], d["policy"], d["escalation"]
    st.virtual_min, st.asked, st.inquiries, st.mode, st.late = d["virtual_min"], d["asked"], d["inquiries"], d["mode"], d["late"]
    st.pending = PendingInquiry(**d["pending"]) if d["pending"] else None
    st.utility_table, st.stability = d["utility_table"], d["stability"]
    return st
