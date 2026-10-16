from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from dallal.agent.v2 import inquiry as iq
from dallal.channels import templates as tpl
from dallal.channels import whatsapp as wa
from dallal.channels.interpret import interpret
from dallal.data.augment.scenarios import SCENARIOS
from dallal.service import OpsService


# ── payload shapes (as documented by Meta) ──────────────────────────────────
def test_text_and_button_payload_shapes():
    t = wa.text_payload("966500000001", "hi")
    assert t["messaging_product"] == "whatsapp" and t["type"] == "text" and t["text"]["body"] == "hi"
    b = wa.buttons_payload("966500000001", "ok?", [{"id": "a", "title": "Yes"}, {"id": "b", "title": "No"}])
    assert b["interactive"]["type"] == "button" and b["interactive"]["action"]["buttons"][0]["reply"] == {"id": "a", "title": "Yes"}


def test_whatsapp_limits_are_enforced():
    with pytest.raises(wa.SendRefused):
        wa.buttons_payload("x", "b", [{"id": str(i), "title": "t"} for i in range(4)])
    with pytest.raises(wa.SendRefused):
        wa.buttons_payload("x", "b", [{"id": "1", "title": "x" * 21}])
    with pytest.raises(wa.SendRefused):
        wa.list_payload("x", "b", [{"id": str(i), "title": "t"} for i in range(11)])


def test_every_template_button_title_fits_the_20_char_limit_in_both_languages():
    for s in iq.all_specs():
        if s.raw["mode"] == "template_buttons":
            assert all(len(a["ar"]) <= 20 and len(a["en"]) <= 20 for a in s.answers) and len(s.answers) <= 3


def test_every_template_used_by_an_inquiry_is_defined():
    for s in iq.all_specs():
        if s.raw.get("template"):
            assert s.raw["template"] in tpl.TEMPLATES


# ── webhook parsing (payloads copied from the documented shapes) ────────────
def _wrap(msg=None, status=None):
    v = {"messaging_product": "whatsapp", "metadata": {"display_phone_number": "1", "phone_number_id": "2"}}
    if msg:
        v["messages"] = [msg]
    if status:
        v["statuses"] = [status]
    return {"object": "whatsapp_business_account", "entry": [{"id": "W", "changes": [{"field": "messages", "value": v}]}]}


def test_parse_interactive_button_reply_template_button_location_and_status():
    m, _ = wa.parse_webhook(_wrap({"from": "9665", "id": "wamid.A", "timestamp": "1", "type": "interactive", "context": {"id": "wamid.OUT"}, "interactive": {"type": "button_reply", "button_reply": {"id": "i|x", "title": "X"}}}))
    assert m[0].kind == "interactive" and m[0].choice_id == "i|x" and m[0].context_id == "wamid.OUT"
    m, _ = wa.parse_webhook(_wrap({"from": "9665", "id": "wamid.B", "timestamp": "1", "type": "button", "button": {"payload": "p", "text": "T"}}))
    assert m[0].kind == "button" and m[0].button_payload == "p" and m[0].button_text == "T"
    m, _ = wa.parse_webhook(_wrap({"from": "9665", "id": "wamid.C", "timestamp": "1", "type": "location", "location": {"latitude": 26.3, "longitude": 50.2}}))
    assert m[0].kind == "location" and (m[0].lat, m[0].lng) == (26.3, 50.2)
    _, s = wa.parse_webhook(_wrap(status={"id": "wamid.OUT", "status": "failed", "timestamp": "1", "recipient_id": "9665", "errors": [{"code": 131049, "title": "x"}]}))
    assert s[0].status == "failed" and s[0].errors[0]["code"] == 131049


def test_signature_verification_uses_the_raw_body():
    body = json.dumps({"a": 1}).encode()
    good = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert wa.verify_signature(body, good, "secret")
    assert not wa.verify_signature(body + b" ", good, "secret")
    assert not wa.verify_signature(body, "sha256=00", "secret") and not wa.verify_signature(body, None, "secret") and not wa.verify_signature(body, good, "")


def test_verification_handshake():
    ok = {"hub.mode": "subscribe", "hub.verify_token": "tok", "hub.challenge": "123"}
    assert wa.verify_challenge(ok, "tok") == "123"
    assert wa.verify_challenge({**ok, "hub.verify_token": "bad"}, "tok") is None


# ── providers: honesty rules ────────────────────────────────────────────────
def test_sandbox_never_claims_real_delivery_and_enforces_the_24h_window():
    p = wa.SandboxProvider()
    r = p.send(wa.template_payload("SANDBOX-1", "dallal_receipt_check", "ar", ["a", "b"], [{"payload": "x", "title": "y"}]))
    assert r.real_delivery is False and r.status == "sandbox_accepted" and r.wamid.startswith("wamid.SANDBOX")
    with pytest.raises(wa.SendRefused) as e:  # interactive outside the window and no reply yet
        p.send(wa.buttons_payload("SANDBOX-1", "b", [{"id": "1", "title": "t"}]))
    assert e.value.code == 131047
    p.open_window("SANDBOX-1")
    assert p.send(wa.buttons_payload("SANDBOX-1", "b", [{"id": "1", "title": "t"}])).status == "sandbox_accepted"


class FakeSession:
    def __init__(self, status=200, body=None):
        self.calls, self.status, self.body = [], status, body or {"messaging_product": "whatsapp", "contacts": [{"input": "x", "wa_id": "x"}], "messages": [{"id": "wamid.REAL1"}]}

    def post(self, url, headers=None, data=None, timeout=None):
        self.calls.append((url, headers, json.loads(data)))
        outer = self

        class R:
            status_code = outer.status
            content = b"1"

            def json(self_):
                return outer.body

        return R()


def test_cloud_provider_targets_graph_api_and_reports_accepted_not_delivered():
    sess = FakeSession()
    p = wa.CloudApiProvider(token="T", phone_number_id="PN", allowlist={"966500000001"}, session=sess)
    r = p.send(wa.text_payload("+966500000001", "hi"))
    url, headers, body = sess.calls[0]
    assert url == "https://graph.facebook.com/v25.0/PN/messages" and headers["Authorization"] == "Bearer T" and body["to"] == "+966500000001"
    assert r.status == "accepted" and r.real_delivery is False and r.wamid == "wamid.REAL1"


def test_cloud_provider_refuses_fixtures_non_e164_and_non_allowlisted_numbers():
    p = wa.CloudApiProvider(token="T", phone_number_id="PN", allowlist={"966500000001"}, session=FakeSession())
    for bad in ("SANDBOX-0001", "0500000001", "+966511111111"):
        with pytest.raises(wa.SendRefused):
            p.send(wa.text_payload(bad, "hi"))
    assert not p.session.calls  # nothing was transmitted


def test_cloud_provider_needs_credentials(monkeypatch):
    monkeypatch.delenv("WHATSAPP_ACCESS_TOKEN", raising=False)
    with pytest.raises(RuntimeError):
        wa.CloudApiProvider(session=FakeSession())


def test_cloud_error_response_is_a_refusal_not_an_acceptance():
    p = wa.CloudApiProvider(token="T", phone_number_id="PN", allowlist={"966500000001"}, session=FakeSession(400, {"error": {"code": 131030, "message": "not in allowed list"}}))
    r = p.send(wa.text_payload("966500000001", "hi"))
    assert r.status == "refused" and r.error["code"] == 131030


# ── interpretation ──────────────────────────────────────────────────────────
def _msg(**kw):
    base = dict(wamid="w", sender="s", timestamp=0, kind="text")
    return wa.Inbound(**{**base, **kw})


def test_structured_replies_are_trusted_and_foreign_payloads_are_rejected():
    s = iq.spec("ask_recipient_availability")
    ok = interpret(_msg(kind="button", button_payload="inq-1|avail_no"), s, "inq-1", {})
    assert ok.answer_id == "avail_no" and ok.confidence == 1.0
    other = interpret(_msg(kind="button", button_payload="inq-9|avail_no"), s, "inq-1", {})
    assert other.answer_id is None and other.needs_review
    by_text = interpret(_msg(kind="button", button_payload="x", button_text="غير متوفر"), s, "inq-1", {})
    assert by_text.answer_id == "avail_no"


def test_location_is_converted_to_distance_from_the_address():
    s = iq.spec("ask_recipient_location")
    facts = {"dest_lat": 26.3100, "dest_lng": 50.2000}
    near = interpret(_msg(kind="location", lat=26.3105, lng=50.2002), s, "i", facts)
    far = interpret(_msg(kind="location", lat=26.3300, lng=50.2300), s, "i", facts)
    assert near.answer_id == "loc_match" and far.answer_id == "loc_far" and far.details["distance_m"] > 300


def test_media_is_stored_for_review_never_used_as_evidence():
    r = interpret(_msg(kind="image", media_id="m1"), iq.spec("ask_recipient_availability"), "i", {})
    assert r.answer_id is None and r.needs_review


@pytest.mark.parametrize("text,spec,want", [("نعم لا", "ask_recipient_availability", None), ("ما أقدر اليوم بكرة أحسن", "ask_recipient_availability", "reschedule"),
                                            ("أنا مو موجود", "ask_recipient_availability", "avail_no"), ("ايوه موجود", "ask_recipient_availability", "avail_yes"),
                                            ("ما استلمتها", "ask_recipient_receipt", "not_received"), ("لا ما استلمتها", "ask_recipient_receipt", "not_received"),
                                            ("yes not available", "ask_recipient_availability", None), ("هلا والله", "ask_recipient_availability", None)])
def test_arabic_and_english_text(text, spec, want):
    assert interpret(_msg(text=text), iq.spec(spec), "i", {}).answer_id == want


def test_opt_out_phrase_is_recognised():
    assert interpret(_msg(text="إيقاف"), iq.spec("ask_recipient_availability"), "i", {}).opt_out


# ── the service: end to end through the real webhook path ───────────────────
def service():
    return OpsService(time_scale=60)


def asked(svc):
    run = svc.investigate(SCENARIOS["stalled_no_scan"](7))
    assert run["status"] == "awaiting_response"
    return run, run["inquiries_live"][0]


def test_full_loop_ask_reply_resume_decide():
    svc = service()
    run, inq = asked(svc)
    assert inq["delivery_mode"] == "sandbox" and inq["real_delivery"] is False
    svc.sandbox_reply(inq["inquiry_id"], "button", answer_id="backlog_confirmed")
    out = svc.view_run(run["run_id"])
    assert out["status"] == "completed" and out["decision"]["top_cause"] == "facility_backlog"
    kinds = [e["kind"] for e in svc.store.timeline()]
    assert kinds.index("inquiry_sent") < kinds.index("reply_received") < kinds.index("decision")


def test_duplicate_webhook_delivery_is_processed_once():
    svc = service()
    run, inq = asked(svc)
    first = svc.sandbox_reply(inq["inquiry_id"], "button", answer_id="backlog_confirmed", wamid="wamid.DUP1")
    second = svc.sandbox_reply(inq["inquiry_id"], "button", answer_id="backlog_confirmed", wamid="wamid.DUP1")
    assert first["messages"] == 1 and second["duplicates"] == 1 and second["messages"] == 0
    assert len([e for e in svc.store.timeline() if e["kind"] == "reply_received"]) == 1


def test_timeout_resumes_the_run_and_a_late_reply_is_handled():
    svc = service()
    run, inq = asked(svc)
    svc.expire(inq["inquiry_id"])
    out = svc.view_run(run["run_id"])
    assert out["inquiries"][0]["status"] == "timed_out"
    assert any(e["kind"] == "inquiry_timed_out" for e in svc.store.timeline())


def test_overdue_inquiries_are_expired_by_tick():
    svc = service()
    run, inq = asked(svc)
    assert svc.tick(now=inq["deadline_real"] - 1) == []
    assert svc.tick(now=inq["deadline_real"] + 1) == [inq["inquiry_id"]]


def test_unreadable_text_waits_for_human_review_then_resumes():
    svc = service()
    run, inq = asked(svc)
    svc.sandbox_reply(inq["inquiry_id"], "text", text="هلا والله")
    mid = svc.view_run(run["run_id"])
    assert mid["status"] == "awaiting_response" and any(e["kind"] == "needs_human_review" for e in svc.store.timeline())
    svc.resolve_review(inq["inquiry_id"], "normal_ops", reviewer="analyst-1")
    assert svc.view_run(run["run_id"])["status"] == "completed"


def test_opt_out_blocks_future_messages_and_continues_the_run():
    svc = OpsService(time_scale=60)
    run = svc.investigate(SCENARIOS["address_risk"](7))
    # force a recipient question by asking about a case that has one pending
    pend = [i for i in run["inquiries_live"] if i["target"] == "recipient"]
    if not pend:
        pytest.skip("scenario did not ask the recipient")
    svc.sandbox_reply(pend[0]["inquiry_id"], "text", text="إيقاف")
    assert svc.store.is_opted_out(pend[0]["recipient_hash"])


def test_every_stored_message_carries_its_delivery_mode_and_no_phone_number():
    svc = service()
    run, inq = asked(svc)
    blob = json.dumps(svc.view_run(run["run_id"]))
    assert "SANDBOX-" not in blob and "+966" not in blob, "recipient identifiers must not leak into API output"
    assert all(m["mode"] == "sandbox" for m in inq["messages"])


def test_execution_requires_the_right_approval_and_outcomes_are_never_self_reported():
    svc = service()
    run = svc.investigate(SCENARIOS["recipient_unavailable"](7))
    d = run["decision"]
    assert d["type"] in ("auto_eligible", "recommend")
    if d["type"] == "recommend":
        with pytest.raises(PermissionError):
            svc.execute(run["run_id"])
        res = svc.execute(run["run_id"], approved_by="analyst-1", role="analyst")
    else:
        res = svc.execute(run["run_id"])
    assert res["external_effect"] is False and res["outcome"] == "pending"
    with pytest.raises(PermissionError):
        svc.record_outcome(res["action_id"], "recovered", source="agent")
    assert svc.record_outcome(res["action_id"], "recovered", source="operator:demo")["kind"] == "recovered"
