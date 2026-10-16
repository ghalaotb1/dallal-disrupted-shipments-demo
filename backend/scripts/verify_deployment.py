#!/usr/bin/env python3
"""Smoke-test a deployed Dallal backend (and optionally the Vercel frontend proxy). Standard library only; prints a PASS/FAIL table; exits 1 on any failure.

  python backend/scripts/verify_deployment.py --backend https://dallal-staging.onrender.com --key "$DALLAL_API_KEY" [--frontend https://dallal-sa.vercel.app]
  python backend/scripts/verify_deployment.py ... --check-run run-abc12345      # after a restart: proves a run survived it

It exercises the same endpoints the UI uses: health, auth, capabilities, an agent run that asks a (sandbox) question, a sandbox reply, approval roles,
the outcome ledger, trained-model scoring and the coordinated-plan lifecycle. It creates simulated records only; nothing is sent to a phone.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

RESULTS: list[tuple[str, bool, str]] = []


def call(base: str, method: str, path: str, key: str | None = None, body: dict | None = None, timeout: float = 60.0) -> tuple[int, dict | list | str]:
    req = urllib.request.Request(base.rstrip("/") + path, method=method, data=None if body is None else json.dumps(body).encode(), headers={"Content-Type": "application/json", "User-Agent": "dallal-verify"})
    if key:
        req.add_header("X-API-Key", key)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw[:1] in "[{" else raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  - {detail}" if detail else ""), flush=True)
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True)
    ap.add_argument("--key", default="")
    ap.add_argument("--frontend", default="")
    ap.add_argument("--check-run", default="")
    ap.add_argument("--expect-env", default="staging")
    a = ap.parse_args()
    B, K = a.backend, a.key or None

    s, h = call(B, "GET", "/v1/health")
    check("backend health is public and reports a working database", s == 200 and isinstance(h, dict) and h.get("ok") is True, f"env={h.get('env') if isinstance(h, dict) else h}")
    if a.expect_env != "dev":
        s, _ = call(B, "GET", "/v1/meta")
        check("API refuses requests without a key", s == 401, f"status {s}")
        s, _ = call(B, "GET", "/v1/runs", "wrong-key-wrong-key-wrong-key")
        check("API refuses a wrong key", s == 401, f"status {s}")
        s, _ = call(B, "GET", "/docs")
        check("interactive API docs are not exposed", s in (404, 401), f"status {s}")
    s, m = call(B, "GET", "/v1/meta", K)
    if not check("capabilities readable with the key", s == 200 and isinstance(m, dict)):
        return 1
    assert isinstance(m, dict)
    check(f"environment is {a.expect_env}", m.get("env") == a.expect_env, str(m.get("env")))
    check("operational actions are simulated", (m.get("execution") or {}).get("mode") == "simulated")
    wa = m.get("whatsapp") or {}
    check("WhatsApp is sandbox (no real messages possible) or cloud with approval hold", wa.get("mode") == "sandbox" or wa.get("send_requires_supervisor_approval") is True, json.dumps(wa))
    llm = m.get("llm") or {}
    print(f"INFO  language model: backend={llm.get('backend')} available={llm.get('available')} interpreter_active={llm.get('interpreter_active')}")
    print(f"INFO  persistence: {json.dumps(m.get('persistence'))}")

    if a.check_run:
        s, r = call(B, "GET", f"/v1/runs/{a.check_run}", K)
        return 0 if check("run created before the restart is still there", s == 200, f"status {s}") else 1

    s, models = call(B, "GET", "/v1/models", K)
    check("trained models are served", s == 200 and isinstance(models, list) and len(models) >= 3, f"{len(models) if isinstance(models, list) else models} models")
    s, sc = call(B, "POST", "/v1/models/lade_slow_task_v1/score", K, {"features": {"hour": 11, "dow": 5, "aoi_type": 14, "open_tasks_courier": 3, "accept_dist_m": 350, "aoi_past_logdur": 4.0, "aoi_past_n": 800,
                                                                                    "courier_past_logdur": 3.96, "courier_past_n": 1900, "region_past_logdur": 4.1, "region_past_n": 20000}})
    check("model scores a complete in-range row", s == 200 and isinstance(sc, dict) and sc.get("abstained") is False, str(sc.get("probability") if isinstance(sc, dict) else sc))
    s, sc2 = call(B, "POST", "/v1/models/lade_slow_task_v1/score", K, {"features": {"hour": 11}})
    check("model refuses an incomplete row (no imputation)", s == 422, f"status {s}")

    s, run = call(B, "POST", "/v1/scenarios/developing_disruption/run?seed=11", K, {})
    ok = s == 200 and isinstance(run, dict) and run["run"].get("status") == "awaiting_response"
    check("agent investigates and pauses to ask the courier", ok, f"status {s}")
    if not ok:
        return 1
    assert isinstance(run, dict)
    rid = run["run"]["run_id"]
    inq = run["run"]["inquiries_live"][0]
    check("the question is a sandbox message that was not delivered to any phone", inq["delivery_mode"] == "sandbox" and inq["real_delivery"] is False and inq["messages"][0]["status"].startswith("sandbox"))
    s, rep = call(B, "POST", "/v1/sandbox/reply", K, {"inquiry_id": inq["inquiry_id"], "kind": "button", "answer_id": "at_address_no_answer"})
    s2, final = call(B, "GET", f"/v1/runs/{rid}", K)
    fr = (final.get("run") or {}) if isinstance(final, dict) else {}
    check("reply updates beliefs and completes the run", s == 200 and s2 == 200 and fr.get("status") == "completed", f"decision={(fr.get('decision') or {}).get('type')}")
    s, _ = call(B, "POST", f"/v1/runs/{rid}/execute", K, {"approved_by": "verify", "role": "none"})
    check("execution without approval is refused (403)", s == 403, f"status {s}")
    s, ex = call(B, "POST", f"/v1/runs/{rid}/execute", K, {"approved_by": "verify-analyst", "role": "analyst"})
    check("analyst-approved action is executed as SIMULATED", s == 200 and isinstance(ex, dict) and ex.get("status") == "executed_simulated" and ex.get("external_effect") is False, str(ex)[:120])
    s, led = call(B, "GET", "/v1/ledger?limit=20", K)
    check("decision and action are in the outcome ledger", s == 200 and isinstance(led, list) and any(r.get("table") == "action" for r in led))

    snap = {"incidentId": "INC-VERIFY", "scope": "corridor", "scopeId": "DK-04", "now": 0, "belief": {"pLong": 0.3}, "dispatcherContactable": True,
            "parcels": [{"id": f"P{i}", "van": f"V{i % 3}", "value": 400 + 120 * i, "slackMin": 70 + 6 * i, "remainingMin": 35, "service": "Express", "exposed": i > 4, "pickupOk": True, "reachable": True} for i in range(8)],
            "resources": {"spares": [{"id": "S1", "etaMin": 22, "capacity": 2}], "pickups": [{"id": "K1", "travelMin": 25, "capacity": 2, "online": True}], "alt": {"available": True, "extraMin": 40}}}
    s, plan = call(B, "POST", "/v1/frontend/incidents/plan", K, {"snapshot": snap, "lang": "ar"})
    pid = plan.get("plan_id") if isinstance(plan, dict) else None
    check("coordinated plan is created for a shared-cause incident", s == 200 and pid is not None and len(plan["solution"]["per_parcel"]) == 8)
    if pid and plan["status"] == "awaiting_evidence":
        iq = plan["inquiries"][0]
        s, _ = call(B, "POST", "/v1/sandbox/reply", K, {"inquiry_id": iq["inquiry_id"], "kind": "button", "answer_id": "blocked_long"})
        s, plan = call(B, "GET", f"/v1/plans/{pid}", K)
    if pid:
        s, _ = call(B, "POST", f"/v1/plans/{pid}/decision", K, {"decision": "approve", "by": "verify", "role": "analyst"})
        check("plan approval by an analyst is refused (supervisor only)", s == 403, f"status {s}")
        s, done = call(B, "POST", f"/v1/plans/{pid}/decision", K, {"decision": "approve", "by": "verify-supervisor", "role": "supervisor"})
        check("supervisor approval executes the plan as SIMULATED", s == 200 and done.get("status") == "executed_simulated", str(done.get("status")) if isinstance(done, dict) else str(done))
    print(f"INFO  records created: run {rid}" + (f", plan {pid}" if pid else "") + "  (re-run with --check-run after a restart to test persistence)")

    if a.frontend:
        F = a.frontend
        s, _ = call(F, "GET", "/api/dallal/v1/health")
        check("Vercel proxy reaches the backend", s == 200, f"status {s}")
        s, pm = call(F, "GET", "/api/dallal/v1/meta")
        check("proxy adds the API key server-side (browser never holds it)", s == 200 and isinstance(pm, dict) and pm.get("env") == a.expect_env, f"status {s}")
        s, _ = call(F, "GET", "/api/dallal/admin/anything")
        check("proxy forwards only /v1/*", s == 404, f"status {s}")
        for page in ("/", "/models", "/incidents/INC-2417", "/shipments/DL-20764"):
            s, _ = call(F, "GET", page)
            check(f"frontend page {page} loads", s == 200, f"status {s}")
    bad = [n for n, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} checks passed" + (f"; FAILED: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
