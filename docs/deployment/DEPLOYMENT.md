# Deploying Dallal: Vercel frontend + hosted backend

**Status:** the packaging is done and the backend was run from a clean copy of exactly the file set the image contains (health, models, experiments, meta all answered). **It has not been deployed**: no hosting account or credentials exist in this environment, and Docker is not installed on the build machine, so the image itself was not built here. Until a backend URL is set, the Vercel frontend keeps working on its in-browser prototype logic and says so ("Simulated" pill in the top bar).

## Topology

```
Browser ──► Vercel (Next.js, static + /api/dallal proxy) ──► Backend container (FastAPI + SQLite on a volume)
                                                                   ▲
                                         Meta WhatsApp webhook ────┘  (only when the real provider is enabled)
```

Two ways to connect the frontend. Pick one.

**A. Same-origin proxy (recommended; keeps keys server-side, no CORS)** - set on Vercel (Project -> Settings -> Environment Variables):

| variable | value |
|---|---|
| `DALLAL_BACKEND_URL` | `https://<backend-host>` (server-only) |
| `DALLAL_API_KEY` | the same secret the backend uses (server-only) |
| `NEXT_PUBLIC_DALLAL_API_URL` | `/api/dallal` |

The route handler `app/api/dallal/[...path]/route.ts` forwards only `/v1/*` to that one origin and adds the key.

**B. Direct** - `NEXT_PUBLIC_DALLAL_API_URL=https://<backend-host>` and set `DALLAL_CORS_ORIGINS` on the backend to the Vercel origin(s). Do not set an API key in this mode (a `NEXT_PUBLIC_` value is visible to every visitor); run the backend in sandbox WhatsApp mode only.

Judges can also point any copy of the frontend at their own backend with `?backend=https://host` (remembered in localStorage; `?backend=off` clears it).

## Backend

Container (from the repo root):

```bash
docker build -f backend/Dockerfile -t dallal-backend .
docker run -p 8000:8000 -v dallal-data:/data -e DALLAL_API_KEY=changeme -e DALLAL_CORS_ORIGINS=https://<vercel-host> dallal-backend
```

`render.yaml` is a Render blueprint (Docker, 1 GB disk at `/data`, health check `/v1/health`). The same image runs on Fly.io, Railway or any container host; what matters is **a persistent volume for the SQLite file** (`DALLAL_DB`) - runs, inquiries, plans and the outcome ledger live there. On an ephemeral free instance state resets on restart: acceptable for a demo, say so.

| variable | meaning | default |
|---|---|---|
| `DALLAL_DB` | SQLite path | `/data/dallal.sqlite` in the image |
| `DALLAL_API_KEY` | required `x-api-key` on every `/v1` call except the Meta webhook | unset = open (sandbox demos only) |
| `DALLAL_CORS_ORIGINS` | comma-separated allowed origins | localhost + `*.vercel.app` |
| `DALLAL_TIME_SCALE` | demo clock: inquiry deadlines run N x faster | 1 |
| `WHATSAPP_MODE` | `sandbox` (default) or `cloud` | sandbox |
| `WHATSAPP_*` | see `docs/integration/WHATSAPP.md` | - |
| `DALLAL_OLLAMA_URL` | local LLM endpoint for the optional LLM planner / reply interpreter | `http://localhost:11434` |

The image contains code, the three committed calibrated model artifacts (~1 MB, SHA-256 checked on load) and the experiment reports. It contains **no datasets and no secrets**. The LLM stage is off in the hosted default: Qwen needs a GPU/Apple-silicon-class machine (see the LLM section of the final report); the deterministic EVOI planner and rule interpreter are the hosted path.

## Verifying a deployment

```bash
curl https://<backend>/v1/health            # {"ok":true,...}
curl https://<backend>/v1/meta              # whatsapp_mode, real_delivery_possible:false in sandbox
curl https://<backend>/v1/models            # three trained models
```

Then open the Vercel site: the top-bar pill should read **Live backend** (with **WA SANDBOX**), `/models` should list the models, shipment `DL-20764` should show a LIVE agent run that asks the courier, and an incident page should offer **Plan with the backend**.

## Security notes

* Sandbox mode cannot send a message to a phone, by construction. Cloud mode is additionally gated by an allowlist of E.164 numbers, opt-in, quiet hours and a per-recipient rate limit.
* Webhook POSTs are rejected unless the `X-Hub-Signature-256` HMAC verifies against `WHATSAPP_APP_SECRET`.
* Execution endpoints enforce roles from the decision type (auto / analyst / supervisor); the UI cannot talk the backend into a higher autonomy level.
* Model artifacts are joblib pickles of the project's own models; `registry.load` refuses a file whose hash differs from its card. Never load artifacts from an untrusted source.
