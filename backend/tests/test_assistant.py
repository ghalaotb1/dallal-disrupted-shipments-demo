"""The operator assistant: retrieval from live facts, grounding checks and graceful degradation. The model itself is stubbed (live checks run against Ollama)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from dallal import assistant, llm
from dallal.api.app import create_app
from dallal.api.security import Settings
from dallal.channels import whatsapp as wa
from dallal.service import OpsService
from dallal.store import Store

SNAP = {
    "now": "15:10",
    "kpis": {"active_parcels": 24, "at_risk": 10, "disrupted": 2},
    "drivers": [
        {"id": "turki", "name": "Turki", "name_ar": "تركي", "vehicle": "DMM-212", "corridor": "DM-07", "done": 2, "total": 6, "held": False,
         "parcels": [{"id": "DL-20655", "seq": 3, "district": "Al Badi", "health": "disrupted", "headline": "Delivery attempt failed", "exception": "Recipient not available", "value": 520, "service": "Standard"}]},
        {"id": "salem", "name": "Salem", "name_ar": "سالم", "vehicle": "DMM-114", "corridor": "DK-04", "done": 3, "total": 6, "held": True, "note": "Slow traffic", "parcels": []},
    ],
    "cases": [{"id": "B", "label": "Customer not answering", "parcel_id": "DL-20655", "driver_id": "turki", "status": "Resolved by Dallal", "run_id": "run-aaaaaaaa"}],
    "plans": [],
    "events": [{"at": "15:02", "text": "Turki: nobody answered for DL-20655"}],
}
RUN = {"run_id": "run-aaaaaaaa", "subject_id": "DL-20655", "status": "completed",
       "decision": {"type": "auto_eligible", "action_title": "Contact recipient to confirm availability", "top_cause": "recipient_unavailable", "posterior": 0.91, "robust_effectiveness": 0.76},
       "belief_trajectory": [{"after": "get_shipment", "top": [["recipient_unavailable", 0.64]]}, {"after": "ask:x", "top": [["recipient_unavailable", 0.91]]}],
       "steps": [{"tool": "get_journey", "summary": "1 failed attempt(s) logged"}],
       "inquiries_live": [{"target": "courier", "question_en": "Parcel DL-20655: what is the delivery status?", "status": "answered", "outcome": "at_address_no_answer", "answers": [{"id": "at_address_no_answer", "title_en": "At address, nobody answered"}]}]}


def test_mentions_in_arabic_and_english():
    assert assistant.mentions("لماذا تأخر تركي؟", SNAP)["drivers"] == ["turki"]
    assert assistant.mentions("where is dl-20655 and DMM-114", SNAP) == {"parcels": ["DL-20655"], "drivers": ["salem"]}


def test_context_is_built_from_agent_records_and_marks_pending():
    ctx, known = assistant.build_context(SNAP, [RUN], [], [], assistant.mentions("DL-20655", SNAP))
    assert "RUN run-aaaaaaaa - parcel DL-20655, driver Turki" in ctx
    assert "before the question customer not available 64%; after the reply customer not available 91%" in ctx
    assert "At address, nobody answered" in ctx and "nothing sent to a phone" in ctx and "Dallal resolves it alone" in ctx
    assert "DL-20655" in known and "run-aaaaaaaa" in known


def test_grounding_check_flags_unknown_identifiers():
    _, known = assistant.build_context(SNAP, [RUN], [], [], {"parcels": [], "drivers": []})
    assert assistant.verify("DL-20655 is handled (run-aaaaaaaa).", known) == []
    assert assistant.verify("DL-99999 was delivered", known) == ["DL-99999"]
    assert assistant.verify("belief rose to 91%", known, "belief 64% then 91%") == []
    assert assistant.verify("belief rose to 77%", known, "belief 64% then 91%") == ["77%"]
    assert assistant.verify("ارتفعت إلى ٩١٪", known, "belief 91%") == []


def _client(**kw):
    st = Settings(env="dev", rate_per_min=1000)
    svc = OpsService(Store(":memory:"), wa.SandboxProvider(), settings=st)
    return TestClient(create_app(svc, start_ticker=False, settings=st))


def _events(res):
    return [json.loads(line) for line in res.text.splitlines() if line.strip()]


def test_chat_streams_and_reports_grounding(monkeypatch):
    monkeypatch.setattr(llm, "capabilities", lambda max_age_s=30.0: {"available": True, "models": ["qwen3.5:4b"], "backend": "ollama"})
    monkeypatch.setattr(llm, "chat_stream", lambda model, msgs, **kw: iter(["Turki's DL-20655 ", "failed at the door."]))
    ev = _events(_client().post("/v1/assistant/chat", json={"question": "ماذا حدث للطرد DL-20655؟", "history": [], "snapshot": SNAP}))
    kinds = [e["type"] for e in ev]
    assert kinds[:2] == ["start", "context"] and kinds[-1] == "done" and "delta" in kinds
    assert ev[1]["sources"][0] == {"type": "parcel", "id": "DL-20655", "label": "DL-20655"}
    assert ev[-1]["grounded"] is True


def test_invented_parcel_is_flagged_and_unavailable_model_degrades(monkeypatch):
    monkeypatch.setattr(llm, "capabilities", lambda max_age_s=30.0: {"available": True, "models": ["qwen3.5:4b"], "backend": "ollama"})
    monkeypatch.setattr(llm, "chat_stream", lambda model, msgs, **kw: iter(["DL-77777 was delivered."]))
    done = _events(_client().post("/v1/assistant/chat", json={"question": "status?", "history": [], "snapshot": SNAP}))[-1]
    assert done["grounded"] is False and done["violations"] == ["DL-77777"]
    monkeypatch.setattr(llm, "capabilities", lambda max_age_s=30.0: {"available": False, "models": [], "backend": "ollama"})
    last = _events(_client().post("/v1/assistant/chat", json={"question": "status?", "history": [], "snapshot": SNAP}))[-1]
    assert last["type"] == "error" and last["code"] == "llm_unavailable"
    monkeypatch.setattr(llm, "capabilities", lambda max_age_s=30.0: {"available": True, "models": ["other"], "backend": "ollama"})
    assert _events(_client().post("/v1/assistant/chat", json={"question": "status?", "history": [], "snapshot": SNAP}))[-1]["code"] == "model_missing"
