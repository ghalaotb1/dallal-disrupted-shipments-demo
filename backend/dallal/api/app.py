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
import json
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from dallal.agent.frontend import to_frontend
from dallal.agent.trace import AgentRun
from dallal.api.frontend_case import bundle_from_frontend
from dallal.channels import whatsapp as wa
from dallal.data.augment.scenarios import SCENARIOS
from dallal.service import OpsService
from dallal.store import Store


def build_service() -> OpsService:
    from dallal.config import PATHS

    db = os.environ.get("DALLAL_DB", str(PATHS.data / "ops.sqlite"))
    provider = wa.CloudApiProvider() if os.environ.get("WHATSAPP_MODE", "sandbox") == "cloud" else wa.SandboxProvider()
    return OpsService(Store(db), provider, time_scale=float(os.environ.get("DALLAL_TIME_SCALE", "1")))


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


def create_app(service: OpsService | None = None, start_ticker: bool = True) -> FastAPI:
    svc = service or build_service()
    api_key = os.environ.get("DALLAL_API_KEY")
    stop = threading.Event()

    def ticker() -> None:
        while not stop.wait(2.0):
            try:
                svc.tick()
            except Exception:  # noqa: BLE001 - the loop must survive a bad row
                pass

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        t = threading.Thread(target=ticker, daemon=True)
        if start_ticker:
            t.start()
        yield
        stop.set()

    app = FastAPI(title="Dallal backend", version="0.2.0", lifespan=lifespan)
    origins = [o.strip() for o in os.environ.get("DALLAL_CORS_ORIGINS", "").split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins or ["http://localhost:3000", "http://127.0.0.1:3000"], allow_origin_regex=None if origins else r"https://.*\.vercel\.app",
                       allow_methods=["*"], allow_headers=["*"])

    def guard(x_api_key: str | None = Header(default=None)) -> None:
        if api_key and x_api_key != api_key:
            raise HTTPException(401, "missing or invalid X-API-Key")

    def ui(run: dict[str, Any], started_at_ms: int = 0) -> dict[str, Any]:
        r = AgentRun(**{k: v for k, v in run.items() if k in AgentRun.__dataclass_fields__})
        live = {"whatsapp_mode": svc.provider.mode, "inquiries": run.get("inquiries_live", [])}
        return to_frontend(r, started_at_ms, live)

    # ── meta ──
    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "ts": time.time()}

    @app.get("/v1/meta")
    def meta() -> dict[str, Any]:
        return svc.meta()

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
        challenge = wa.verify_challenge(dict(request.query_params), os.environ.get("WHATSAPP_VERIFY_TOKEN", ""))
        if challenge is None:
            raise HTTPException(403, "verification failed")
        return PlainTextResponse(challenge)

    @app.post("/v1/whatsapp/webhook")
    async def wh_receive(request: Request) -> dict[str, Any]:
        raw = await request.body()
        secret = os.environ.get("WHATSAPP_APP_SECRET", "")
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
