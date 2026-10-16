"""Dallal backend HTTP API (FastAPI).

Run:  uvicorn dallal.api.app:app --host 0.0.0.0 --port 8000        (see backend/README.md and docs/deploy for hosting)

Environment
  DALLAL_DB                     SQLite path (default backend/.data/ops.sqlite; ':memory:' for tests)
  DALLAL_CORS_ORIGINS           comma-separated allowed origins (default: localhost + any *.vercel.app)
  DALLAL_API_KEY                if set, mutating endpoints require header X-API-Key
  DALLAL_TIME_SCALE             operational minutes per real minute for inquiry timeouts (demo: 30)
  WHATSAPP_MODE                 'sandbox' (default) or 'cloud'
  WHATSAPP_ACCESS_TOKEN / WHATSAPP_PHONE_NUMBER_ID / WHATSAPP_APP_SECRET / WHATSAPP_VERIFY_TOKEN / WHATSAPP_ALLOWLIST   (cloud mode)
No secret is ever read from a file in the repository.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from dallal.agent.frontend import to_frontend
from dallal.agent.trace import AgentRun
from dallal.api.frontend_case import bundle_from_frontend
from dallal.api.security import RateLimiter, Settings
from dallal.channels import whatsapp as wa
from dallal.data.augment.scenarios import SCENARIOS
from dallal.service import OpsService
from dallal.store import Store


def build_service(settings: Settings | None = None) -> OpsService:
    from dallal.config import PATHS

    settings = settings or Settings.from_env()
    settings.enforce()  # fail closed: unsafe combinations never start
    db = os.environ.get("DALLAL_DB", str(PATHS.data / "ops.sqlite"))
    provider = wa.CloudApiProvider() if settings.whatsapp_mode == "cloud" else wa.SandboxProvider()
    return OpsService(Store(db), provider, time_scale=float(os.environ.get("DALLAL_TIME_SCALE", "1")), settings=settings)


class CaseRequest(BaseModel):
    case: dict[str, Any]
    lang: str = "ar"


class ExecuteRequest(BaseModel):
    approved_by: str | None = None
    role: str | None = None
    action: str | None = None


class OutcomeRequest(BaseModel):
    kind: str
    source: str
    note: str = ""


class ReviewRequest(BaseModel):
    answer_id: str | None = None
    reviewer: str


class SendDecision(BaseModel):
    approver: str
    role: str


class ScoreRequest(BaseModel):
    features: dict[str, float]


class PlanRequest(BaseModel):
    snapshot: dict[str, Any]
    lang: str = "ar"


class PlanDecision(BaseModel):
    decision: str
    by: str
    role: str
    note: str = ""


class SandboxReply(BaseModel):
    inquiry_id: str
    kind: str
    answer_id: str | None = None
    text: str | None = None
    lat: float | None = None
    lng: float | None = None


class SandboxAdvance(BaseModel):
    wamid: str
    status: str


def create_app(service: OpsService | None = None, start_ticker: bool = True, settings: Settings | None = None) -> FastAPI:
    settings = settings or (service.settings if service is not None else Settings.from_env())
    settings.enforce()
    svc = service or build_service(settings)
    api_key = settings.api_key
    stop = threading.Event()
    limiter = RateLimiter(settings.rate_per_min)
    backup_state: dict[str, Any] = {"last": None, "error": None}

    def do_backup() -> str | None:
        if not settings.backup_dir:
            return None
        from pathlib import Path

        dest = Path(settings.backup_dir) / f"dallal-{time.strftime('%Y%m%d-%H%M%S')}.sqlite"
        try:
            svc.store.backup(dest)
            for old in sorted(Path(settings.backup_dir).glob("dallal-*.sqlite"))[:-settings.backups_keep]:
                old.unlink(missing_ok=True)
            backup_state.update(last=str(dest), error=None, at=time.time())
            return str(dest)
        except Exception as e:  # noqa: BLE001 - a failed backup must be visible, never fatal
            backup_state["error"] = f"{type(e).__name__}"
            return None

    def ticker() -> None:
        last_backup = time.time()
        while not stop.wait(2.0):
            try:
                svc.tick()
                if settings.backup_dir and time.time() - last_backup >= settings.backup_every_h * 3600:
                    last_backup = time.time()
                    do_backup()
            except Exception:  # noqa: BLE001 - the loop must survive a bad row
                pass

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        t = threading.Thread(target=ticker, daemon=True)
        if start_ticker:
            t.start()
        yield
        stop.set()

    public = {"/v1/health", "/v1/whatsapp/webhook"}  # webhook authenticity is the Meta signature / verify token, not the API key

    def guard(request: Request, x_api_key: str | None = Header(default=None)) -> None:
        if request.url.path in public or not api_key:
            return
        if not x_api_key or not hmac.compare_digest(x_api_key.encode(), api_key.encode()):
            raise HTTPException(401, "missing or invalid X-API-Key")

    app = FastAPI(title="Dallal backend", version="0.3.0", lifespan=lifespan, dependencies=[Depends(guard)],
                  docs_url=None if settings.locked_down else "/docs", redoc_url=None, openapi_url=None if settings.locked_down else "/openapi.json")
    origins = settings.cors_origins
    app.add_middleware(CORSMiddleware, allow_origins=origins or ([] if settings.locked_down else ["http://localhost:3000", "http://127.0.0.1:3000"]),
                       allow_origin_regex=None if (origins or settings.locked_down) else r"https://.*\.vercel\.app", allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-API-Key"])

    @app.middleware("http")
    async def limits(request: Request, call_next):  # noqa: ANN001
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > settings.max_body_bytes:
            return JSONResponse({"detail": "request body too large"}, status_code=413)
        if request.url.path != "/v1/health" and request.method != "OPTIONS":
            fwd = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            if not limiter.allow(fwd or (request.client.host if request.client else "?")):
                return JSONResponse({"detail": "rate limit exceeded"}, status_code=429, headers={"Retry-After": "30"})
        return await call_next(request)

    def ui(run: dict[str, Any], started_at_ms: int = 0) -> dict[str, Any]:
        r = AgentRun(**{k: v for k, v in run.items() if k in AgentRun.__dataclass_fields__})
        live = {"whatsapp_mode": svc.provider.mode, "inquiries": run.get("inquiries_live", [])}
        return to_frontend(r, started_at_ms, live)

    # ── meta ──
    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        try:
            svc.store.q("SELECT 1")
            db_ok = True
        except Exception:  # noqa: BLE001
            db_ok = False
        return {"ok": db_ok, "ts": time.time(), "env": settings.env}

    @app.get("/v1/meta")
    def meta() -> dict[str, Any]:
        return {**svc.meta(), **capabilities()}

    def capabilities() -> dict[str, Any]:
        from dallal import llm
        from dallal.ml import registry

        return {"env": settings.env, "execution": {"mode": settings.execution_mode, "note": "operational actions are recorded and simulated; no real executor is configured"},
                "whatsapp": {"mode": svc.provider.mode, "send_requires_supervisor_approval": svc.provider.mode == "cloud" and settings.require_send_approval, "real_send_enabled": settings.allow_real_send and svc.provider.mode == "cloud"},
                "llm": llm.capabilities(), "response_learning": {"enabled": True, "prior_strength": 8.0, "learned": {k: {"p_response": round(v["p"], 3), "median_latency_min": round(v["latency_median"], 1)} for k, v in svc.response_stats().overrides().items()}},
                "ml": {"models": registry.available(), "agent_scoring": "calibrated models score a case only when a point-in-time adapter supplies a complete in-domain feature row; otherwise the labelled heuristic is used"},
                "persistence": {"db": "sqlite (WAL)", "backups": bool(settings.backup_dir), "last_backup": backup_state.get("last"), "backup_error": backup_state.get("error")},
                "auth": {"api_key_required": bool(api_key), "roles": "asserted by the client; a single shared key does not identify individual users (add SSO before production)"}}

    @app.post("/v1/admin/backup")
    def admin_backup() -> dict[str, Any]:
        dest = do_backup()
        if dest is None:
            raise HTTPException(409, backup_state.get("error") or "DALLAL_BACKUP_DIR is not configured")
        return {"backup": dest}

    # ── runs ──
    @app.post("/v1/frontend/runs", dependencies=[Depends(guard)])
    def frontend_run(req: CaseRequest) -> dict[str, Any]:
        try:
            bundle = bundle_from_frontend(req.case)
        except (KeyError, ValueError) as e:
            raise HTTPException(422, f"invalid case snapshot: {e}") from e
        run = svc.investigate(bundle, req.lang)
        return {"run": run, "ui": ui(run, int(req.case["now"]))}

    @app.post("/v1/scenarios/{name}/run", dependencies=[Depends(guard)])
    def scenario_run(name: str, seed: int = 7, lang: str = "ar") -> dict[str, Any]:
        if name not in SCENARIOS:
            raise HTTPException(404, f"unknown scenario; choose from {sorted(SCENARIOS)}")
        run = svc.investigate(SCENARIOS[name](seed), lang)
        return {"run": run, "ui": ui(run)}

    @app.get("/v1/scenarios")
    def scenarios() -> list[str]:
        return sorted(SCENARIOS)

    @app.get("/v1/runs")
    def runs(subject_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        return [{"run_id": r["run_id"], "subject_id": r["subject_id"], "status": r["status"], "origin": r["origin"], "updated_at": r["updated_at"],
                 "decision": r["run"].get("decision", {}).get("type"), "headline": r["run"].get("decision", {}).get("headline")} for r in svc.store.list_runs(subject_id, limit)]

    @app.get("/v1/runs/{run_id}")
    def get_run(run_id: str, started_at_ms: int = 0) -> dict[str, Any]:
        try:
            run = svc.view_run(run_id)
        except KeyError:
            raise HTTPException(404, "unknown run") from None
        return {"run": run, "ui": ui(run, started_at_ms)}

    @app.post("/v1/runs/{run_id}/execute", dependencies=[Depends(guard)])
    def execute(run_id: str, req: ExecuteRequest) -> dict[str, Any]:
        try:
            return svc.execute(run_id, req.approved_by, req.role, req.action)
        except KeyError:
            raise HTTPException(404, "unknown run") from None
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

    @app.post("/v1/actions/{action_id}/outcome", dependencies=[Depends(guard)])
    def outcome(action_id: str, req: OutcomeRequest) -> dict[str, Any]:
        try:
            return svc.record_outcome(action_id, req.kind, req.source, req.note)
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    # ── inquiries ──
    @app.get("/v1/inquiries")
    def inquiries(run_id: str | None = None, subject_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        return [svc._inquiry_view(i) for i in svc.store.inquiries_for(run_id=run_id, subject_id=subject_id, status=status)]

    @app.post("/v1/inquiries/{inquiry_id}/expire", dependencies=[Depends(guard)])
    def expire(inquiry_id: str) -> dict[str, Any]:
        try:
            run = svc.expire(inquiry_id)
        except KeyError:
            raise HTTPException(404, "unknown or already-closed inquiry") from None
        return {"plan": run} if "plan_id" in run else {"run": run, "ui": ui(run)}

    @app.post("/v1/inquiries/{inquiry_id}/review", dependencies=[Depends(guard)])
    def review(inquiry_id: str, req: ReviewRequest) -> dict[str, Any]:
        try:
            run = svc.resolve_review(inquiry_id, req.answer_id, req.reviewer)
        except KeyError:
            raise HTTPException(404, "unknown or already-closed inquiry") from None
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return {"plan": run} if "plan_id" in run else {"run": run, "ui": ui(run)}

    @app.post("/v1/inquiries/{inquiry_id}/send/approve")
    def send_approve(inquiry_id: str, req: SendDecision) -> dict[str, Any]:
        try:
            run = svc.approve_send(inquiry_id, req.approver, req.role)
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        except KeyError:
            raise HTTPException(404, "unknown or already-closed inquiry") from None
        except ValueError as e:
            raise HTTPException(409, str(e)) from e
        return {"plan": run} if "plan_id" in run else {"run": run, "ui": ui(run)}

    @app.post("/v1/inquiries/{inquiry_id}/send/decline")
    def send_decline(inquiry_id: str, req: SendDecision) -> dict[str, Any]:
        try:
            run = svc.decline_send(inquiry_id, req.approver, req.role)
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        except KeyError:
            raise HTTPException(404, "unknown, closed or not-held inquiry") from None
        return {"plan": run} if "plan_id" in run else {"run": run, "ui": ui(run)}

    # ── trained risk models (real public data; see docs/ml/models.json) ──
    def _models() -> dict[str, Any]:
        from dallal.ml import registry

        out = {}
        for mid in registry.available():
            try:
                out[mid] = registry.load(mid)
            except Exception:  # noqa: BLE001 - corrupt artifact is simply not served
                continue
        return out

    @app.get("/v1/models")
    def list_models() -> list[dict[str, Any]]:
        res = []
        for mid, m in _models().items():
            c = m.card
            res.append({"model_id": mid, "task_id": c.task_id, "target": c.target, "source": c.source, "licence": c.licence, "algorithm": c.algorithm, "calibration": c.calibration,
                        "features": [f.name for f in c.features], "split": c.split, "test": {k: c.metrics["test"][k] for k in ("n", "prevalence", "roc_auc", "pr_auc", "lift@top10%", "brier", "brier_prevalence_baseline", "ece")},
                        "test_auc_95ci": c.metrics["test_auc_95ci"], "trained_at": c.trained_at, "sha256": c.sha256[:16], "origin": "real-public-data"})
        return res

    @app.get("/v1/models/{model_id}")
    def get_model(model_id: str) -> dict[str, Any]:
        m = _models().get(model_id)
        if m is None:
            raise HTTPException(404, "unknown model")
        return m.card.to_json()

    @app.post("/v1/models/{model_id}/score")
    def score_model(model_id: str, req: ScoreRequest) -> dict[str, Any]:
        from dallal.ml.registry import ContractError

        m = _models().get(model_id)
        if m is None:
            raise HTTPException(404, "unknown model")
        try:
            pred = m.predict(req.features)
        except ContractError as e:
            raise HTTPException(422, str(e)) from e
        c = m.card
        base = {"model_id": model_id, "target": c.target, "source": c.source, "base_rate_source": round(c.base_rate_valid, 5), "origin": "real-public-data"}
        if pred is None:
            return {**base, "abstained": True, "reason": "input outside the range this model was trained on", "features_outside_range": m.out_of_domain_features(req.features)}
        return {**base, "abstained": False, "probability": round(pred.probability, 5), "band": pred.band, "lift_over_base_rate": round(pred.probability / c.base_rate_valid, 2),
                "note": "Calibrated probability of this model's target in the SOURCE population - not an SPL probability."}

    @app.get("/v1/models/{model_id}/replay")
    def replay_model(model_id: str, n: int = 12, seed: int = 0) -> dict[str, Any]:
        """Real held-out rows with the model's prediction and the outcome that actually happened (needs the source data on this host)."""
        import numpy as np
        import pandas as pd

        from dallal.config import PATHS

        m = _models().get(model_id)
        f = PATHS.data / "replay" / f"{model_id}.parquet"
        if m is None:
            raise HTTPException(404, "unknown model")
        if not f.exists():
            raise HTTPException(404, "replay sample not available on this host (source data is not redistributed); run dallal.ml.train locally")
        df = pd.read_parquet(f)
        rows = df.iloc[np.random.default_rng(seed).choice(len(df), size=min(n, len(df)), replace=False)]
        out = []
        for _, r in rows.iterrows():
            feats = {k: float(r[k]) for k in m.feature_names}
            pred = m.predict(feats)
            out.append({"features": feats, "probability": None if pred is None else round(pred.probability, 5), "band": None if pred is None else pred.band, "abstained": pred is None, "outcome": int(r["_label"])})
        base = float(df["_label"].mean())
        return {"model_id": model_id, "source": m.card.source, "origin": "real-public-data", "sample": "random held-out test rows (chronologically after training)", "sample_base_rate": round(base, 4), "rows": out}

    # ── real-data replay (demo A): a real held-out LaDe task goes through the agent; the outcome is revealed afterwards ──
    @app.get("/v1/replay/lade/status")
    def replay_status() -> dict[str, Any]:
        from dallal.data.replay import HUB

        return {"available": HUB.available(), "reason": None if HUB.available() else "the LaDe canonical tables are not on this host (they are not redistributed); build them locally with dallal-data"}

    @app.post("/v1/replay/lade")
    def replay_run(seed: int = 0, minutes_after: float = 10.0) -> dict[str, Any]:
        from dallal.agent.v2.runtime import AgentRuntimeV2
        from dallal.data.replay import HUB

        if not HUB.available():
            raise HTTPException(404, "replay data not available on this host")
        cid, bundle, meta = HUB.new_case(seed, minutes_after)
        res = AgentRuntimeV2(mode="no_inquiry", providers=svc.providers, book=svc.book).start(bundle, run_id=f"run-{cid}")
        call = next((c for c in res.state.calls if c.tool == "predict_risk"), None)
        risk = ((getattr(call, "data", None) or {}).get("risk") or {}) if call else {}
        steps = [{"tool": s["tool"], "summary": s["summary"], "facts": s["facts"], "outcome": s["outcome"], "why": s["why"], "top": ((s.get("belief_after") or {}).get("top") or [])[:2]} for s in res.run.steps]
        d = res.run.decision
        return {**meta, "label": "REAL-DATA REPLAY", "steps": steps, "risk": {"source": risk.get("source"), "band": risk.get("band"), "probability": risk.get("probability"), "meta": risk.get("meta"), "level": risk.get("level")},
                "decision": {k: d.get(k) for k in ("type", "headline", "rationale", "watch", "risk_flag", "top_cause", "posterior")}}

    @app.get("/v1/replay/lade/{case_id}/outcome")
    def replay_outcome(case_id: str) -> dict[str, Any]:
        from dallal.data.replay import HUB

        if case_id not in HUB.cases:
            raise HTTPException(404, "unknown replay case")
        return HUB.outcome(case_id)

    @app.get("/v1/experiments/{name}")
    def experiment(name: str) -> dict[str, Any]:
        """Committed experiment reports (docs/ml, docs/experiments). Whitelisted by name; each report states whether it is real-data or synthetic."""
        import json as _json
        import re

        from dallal.config import PATHS

        if not re.fullmatch(r"[a-z0-9_]+", name):
            raise HTTPException(404, "unknown experiment")
        for d in (PATHS.docs / "ml", PATHS.docs / "experiments"):
            f = d / f"{name}.json"
            if f.exists():
                return _json.loads(f.read_text())
        raise HTTPException(404, "unknown experiment")

    # ── coordinated recovery plans ──
    @app.post("/v1/frontend/incidents/plan", dependencies=[Depends(guard)])
    def make_plan(req: PlanRequest) -> dict[str, Any]:
        try:
            return svc.plans.create(req.snapshot, req.lang)
        except (KeyError, ValueError) as e:
            raise HTTPException(422, f"invalid incident snapshot: {e}") from e

    @app.get("/v1/plans")
    def list_plans() -> list[dict[str, Any]]:
        return [{"plan_id": r["plan_id"], "status": r["status"], "scope": r["scope"], "created_at": r["created_at"]} for r in svc.store.list_plans()]

    @app.get("/v1/plans/{plan_id}")
    def get_plan(plan_id: str) -> dict[str, Any]:
        try:
            return svc.plans.view(plan_id)
        except KeyError:
            raise HTTPException(404, "unknown plan") from None

    @app.post("/v1/plans/{plan_id}/decision", dependencies=[Depends(guard)])
    def decide_plan(plan_id: str, req: PlanDecision) -> dict[str, Any]:
        try:
            return svc.plans.decide(plan_id, req.decision, req.by, req.role, req.note)
        except KeyError:
            raise HTTPException(404, "unknown plan") from None
        except PermissionError as e:
            raise HTTPException(403, str(e)) from e
        except ValueError as e:
            raise HTTPException(409, str(e)) from e

    # ── audit feed ──
    @app.get("/v1/events")
    def events(after: int = 0, limit: int = 200, subject_id: str | None = None) -> list[dict[str, Any]]:
        return svc.store.timeline(after, limit, subject_id)

    @app.get("/v1/events/last")
    def events_last() -> dict[str, int]:
        """Cursor for a new subscriber: start from 'now' instead of replaying every past event."""
        rows = svc.store.q("SELECT MAX(id) AS m FROM timeline")
        return {"id": int(rows[0]["m"] or 0)}

    @app.get("/v1/events/stream")
    async def stream(request: Request, after: int = 0):
        async def gen():
            last = after
            beat = time.time()
            while not await request.is_disconnected():
                for e in svc.store.timeline(last, 100):
                    last = e["id"]
                    yield f"id: {e['id']}\nevent: {e['kind']}\ndata: {json.dumps(e)}\n\n"
                if time.time() - beat > 15:
                    beat = time.time()
                    yield ": keep-alive\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ── WhatsApp webhook (Meta) ──
    @app.get("/v1/whatsapp/webhook")
    def wh_verify(request: Request) -> PlainTextResponse:
        challenge = wa.verify_challenge(dict(request.query_params), settings.verify_token)
        if challenge is None:
            raise HTTPException(403, "verification failed")
        return PlainTextResponse(challenge)

    @app.post("/v1/whatsapp/webhook")
    async def wh_receive(request: Request) -> dict[str, Any]:
        raw = await request.body()
        secret = settings.app_secret
        if svc.provider.mode == "sandbox" and not secret:
            raise HTTPException(404, "webhook is disabled in sandbox mode")  # unsigned inbound events would let anyone forge replies
        if svc.provider.mode == "cloud" or secret:
            if not wa.verify_signature(raw, request.headers.get("X-Hub-Signature-256"), secret):
                raise HTTPException(403, "invalid signature")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise HTTPException(400, "invalid JSON") from None
        # Acknowledge fast with 200; processing here is quick (single DB transaction chain) - a queue is the production upgrade.
        return svc.handle_webhook(payload, "whatsapp")

    # ── sandbox recipient device ──
    @app.get("/v1/sandbox/conversations")
    def sb_conversations() -> list[dict[str, Any]]:
        return svc.sandbox_conversations()

    @app.post("/v1/sandbox/reply", dependencies=[Depends(guard)])
    def sb_reply(req: SandboxReply) -> dict[str, Any]:
        try:
            return svc.sandbox_reply(req.inquiry_id, req.kind, answer_id=req.answer_id, text=req.text, lat=req.lat, lng=req.lng)
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from e
        except (KeyError, ValueError, StopIteration) as e:
            raise HTTPException(422, f"bad sandbox reply: {e}") from e

    @app.post("/v1/sandbox/advance", dependencies=[Depends(guard)])
    def sb_advance(req: SandboxAdvance) -> dict[str, Any]:
        return svc.sandbox_advance(req.wamid, req.status)

    @app.get("/v1/ledger")
    def ledger(limit: int = 200) -> list[dict[str, Any]]:
        return svc.store.ledger(limit)

    return app


app = create_app() if os.environ.get("DALLAL_AUTOSTART", "1") == "1" and __name__ != "__main__" else None  # noqa: E305
