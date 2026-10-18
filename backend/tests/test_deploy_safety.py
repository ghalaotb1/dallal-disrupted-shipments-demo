"""Fail-closed configuration, API protection, held-for-approval sends and restart durability."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from dallal.api.app import create_app
from dallal.api.security import RateLimiter, Settings
from dallal.channels import whatsapp as wa
from dallal.data.augment.scenarios import SCENARIOS
from dallal.service import OpsService
from dallal.store import Store

KEY = "k" * 32


def test_unsafe_configurations_refuse_to_start():
    assert Settings(env="staging").problems()  # no API key
    assert Settings(env="staging", api_key="short").problems()
    assert not Settings(env="staging", api_key=KEY).problems()
    assert any("simulated" in p for p in Settings(execution_mode="real").problems())
    cloud = Settings(whatsapp_mode="cloud")
    probs = " ".join(cloud.problems())
    assert "ALLOW_REAL_SEND" in probs and "ALLOWLIST" in probs and "APP_SECRET" in probs
    ok = Settings(env="staging", api_key=KEY, whatsapp_mode="cloud", allow_real_send=True, allowlist="966500000000", app_secret="s", verify_token="v")
    assert not ok.problems()
    with pytest.raises(RuntimeError, match="refusing to start"):
        Settings(env="production").enforce()


def _client(**kw) -> TestClient:
    st = Settings(env="staging", api_key=KEY, rate_per_min=1000, **kw)
    return TestClient(create_app(OpsService(Store(":memory:"), wa.SandboxProvider(), settings=st), start_ticker=False, settings=st))


def test_api_requires_key_except_health_and_hides_docs():
    c = _client()
    assert c.get("/v1/health").status_code == 200
    for path in ("/v1/runs", "/v1/meta", "/v1/ledger", "/v1/inquiries", "/v1/models", "/v1/plans", "/v1/sandbox/conversations"):
        assert c.get(path).status_code == 401, path
        assert c.get(path, headers={"X-API-Key": "wrong" * 8}).status_code == 401
    assert c.get("/v1/meta", headers={"X-API-Key": KEY}).status_code == 200
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404


def test_meta_reports_capabilities_honestly():
    m = _client().get("/v1/meta", headers={"X-API-Key": KEY}).json()
    assert m["execution"]["mode"] == "simulated" and m["whatsapp"]["mode"] == "sandbox" and m["whatsapp"]["real_send_enabled"] is False
    assert m["llm"]["available"] is False and m["llm"]["backend"] == "none"  # nothing configured -> LLM features are off, not pretended
    assert m["auth"]["api_key_required"] is True


def test_webhook_is_closed_in_sandbox_and_body_size_is_limited():
    c = _client()
    assert c.post("/v1/whatsapp/webhook", json={"entry": []}).status_code == 404  # unsigned inbound events could forge replies
    assert c.post("/v1/frontend/runs", content=b"x" * 600_000, headers={"X-API-Key": KEY, "Content-Type": "application/json"}).status_code == 413


def test_rate_limiter_blocks_after_budget():
    rl = RateLimiter(3)
    assert [rl.allow("a", 100.0) for _ in range(4)] == [True, True, True, False]
    assert rl.allow("a", 161.0) and rl.allow("b", 100.0)


class FakeCloud:
    mode = "cloud"

    def __init__(self):
        self.sent: list[dict] = []
        self.standing_sessions: set[str] = set()

    def send(self, payload, now=None):
        self.sent.append(payload)
        return wa.Receipt("cloud", "wamid.FAKE1", "accepted", False, payload, "accepted by the Cloud API; delivery unconfirmed until a status webhook arrives")


def _cloud_service(**kw) -> tuple[OpsService, FakeCloud]:
    prov = FakeCloud()
    st = Settings(whatsapp_mode="cloud", allow_real_send=True, allowlist="966500000000", app_secret="s", verify_token="v", **kw)
    return OpsService(Store(":memory:"), prov, time_scale=1.0, settings=st), prov


def _start(svc: OpsService) -> tuple[str, str]:
    r = svc.investigate(SCENARIOS["developing_disruption"](11), "ar")
    rid = r["run_id"] if "run_id" in r else r["run"]["run_id"]
    return rid, svc.view_run(rid)["inquiries_live"][0]["inquiry_id"]


def _drain(svc: OpsService, rid: str, held: bool = False) -> None:
    """Let every follow-up inquiry time out (the agent may ask a second question) until the run completes."""
    for _ in range(5):
        if svc.view_run(rid)["status"] != "awaiting_response":
            return
        cur = next(i for i in svc.view_run(rid)["inquiries_live"] if i["status"] == "awaiting")
        svc.expire(cur["inquiry_id"])


def test_cloud_messages_are_held_until_a_supervisor_approves():
    svc, prov = _cloud_service()
    rid, iid = _start(svc)
    assert prov.sent == []  # nothing left the process
    v = svc.view_run(rid)["inquiries_live"][0]
    assert v["status"] == "awaiting" and v["messages"][0]["status"] == "held_for_approval" and v["real_delivery"] is False
    with pytest.raises(PermissionError):
        svc.approve_send(iid, "analyst-1", "analyst")
    assert prov.sent == []
    svc.approve_send(iid, "supervisor-1", "supervisor")
    assert len(prov.sent) == 1
    m = svc.view_run(rid)["inquiries_live"][0]["messages"][0]
    assert m["status"] == "accepted" and svc.view_run(rid)["inquiries_live"][0]["real_delivery"] is False  # accepted != delivered
    assert any(e["kind"] == "send_approved" for e in svc.store.timeline())


def test_declined_or_expired_hold_never_sends_and_the_run_continues():
    svc, prov = _cloud_service()
    rid, iid = _start(svc)
    svc.decline_send(iid, "supervisor-1", "supervisor")
    assert prov.sent == [] and svc.view_run(rid)["inquiries_live"][0]["status"] == "send_refused"
    assert svc.view_run(rid)["status"] in ("completed", "awaiting_response")
    svc2, prov2 = _cloud_service()
    svc2.hold_expiry_s = 0.0
    rid2, _ = _start(svc2)
    svc2.tick(time.time() + 1)
    assert prov2.sent == [] and svc2.view_run(rid2)["inquiries_live"][0]["status"] == "send_refused"


def test_state_survives_a_restart(tmp_path):
    db = str(tmp_path / "ops.sqlite")
    a = OpsService(Store(db), wa.SandboxProvider(), time_scale=1.0, settings=Settings())
    rid, iid = _start(a)
    assert a.view_run(rid)["status"] == "awaiting_response"
    b = OpsService(Store(db), wa.SandboxProvider(), time_scale=1.0, settings=Settings())  # new process, same file
    assert b.view_run(rid)["inquiries_live"][0]["status"] == "awaiting"
    b.expire(iid)
    assert b.view_run(rid)["inquiries_live"][0]["status"] == "timed_out"  # resumed from the stored checkpoint in a new process
    _drain(b, rid)
    assert b.view_run(rid)["status"] == "completed"


def test_backup_is_a_consistent_copy(tmp_path):
    svc = OpsService(Store(str(tmp_path / "a.sqlite")), wa.SandboxProvider(), time_scale=1.0, settings=Settings())
    rid, _ = _start(svc)
    dest = svc.store.backup(tmp_path / "bk" / "copy.sqlite")
    assert Store(dest).get_run(rid) is not None


def test_demo_reset_is_dev_only_and_clears_state():
    dev = Settings(env="dev", rate_per_min=1000)
    svc = OpsService(Store(":memory:"), wa.SandboxProvider(), settings=dev)
    c = TestClient(create_app(svc, start_ticker=False, settings=dev))
    svc.store.x("INSERT INTO optouts(recipient_hash, ts) VALUES('h', 1)")
    out = c.post("/v1/admin/demo-reset")
    assert out.status_code == 200 and out.json()["cleared"]["optouts"] == 1
    assert svc.store.q("SELECT COUNT(*) AS n FROM optouts")[0]["n"] == 0
    assert _client().post("/v1/admin/demo-reset", headers={"X-API-Key": KEY}).status_code == 403  # staging: never
