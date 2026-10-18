#!/usr/bin/env bash
# One command to run the whole local Dallal system: Ollama (Qwen) + Python backend + Next.js frontend.
#   ./scripts/demo.sh            start everything (sandbox WhatsApp, simulated actions, LLM reply suggestions on if Ollama has the model)
#   ./scripts/demo.sh --reset    wipe the demo database first (fresh runs, inquiries, plans, ledger)
#   ./scripts/demo.sh --no-llm   skip Ollama (rules read replies; nothing else changes)
#   ./scripts/demo.sh --stop     stop the services started by this script
# Real WhatsApp stays DISABLED: WHATSAPP_MODE is forced to sandbox. Nothing here can message a real person or execute a real operational action.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$ROOT/backend/.data/logs"; PIDS="$ROOT/backend/.data/demo.pids"; DB="$ROOT/backend/.data/demo.sqlite"
API_PORT="${API_PORT:-8000}"; WEB_PORT="${WEB_PORT:-3000}"; MODEL="${DALLAL_QWEN_MODEL:-qwen3.5:4b}"
USE_LLM=1; RESET=0
for a in "$@"; do case "$a" in --no-llm) USE_LLM=0;; --reset) RESET=1;; --stop) STOP=1;; esac; done

stop_all() { [ -f "$PIDS" ] && while read -r p; do kill "$p" 2>/dev/null || true; done < "$PIDS"; rm -f "$PIDS"; }
if [ "${STOP:-0}" = 1 ]; then stop_all; echo "stopped"; exit 0; fi

mkdir -p "$LOGS"; stop_all
[ -x "$ROOT/backend/.venv/bin/python" ] || { echo "backend venv missing: cd backend && uv venv && uv pip install -e '.[dev,api,report]'"; exit 1; }
[ -d "$ROOT/node_modules" ] || { echo "node modules missing: npm install"; exit 1; }
if [ "$RESET" = 1 ]; then rm -f "$DB" "$DB-wal" "$DB-shm"; echo "demo database reset"; fi

LLM_ENV=""
if [ "$USE_LLM" = 1 ]; then
  if command -v ollama >/dev/null; then
    if ! curl -sf localhost:11434/api/tags >/dev/null; then
      OLLAMA_MAX_LOADED_MODELS=1 OLLAMA_KEEP_ALIVE=10m nohup ollama serve >"$LOGS/ollama.log" 2>&1 & echo $! >> "$PIDS"
      for _ in $(seq 1 20); do curl -sf localhost:11434/api/tags >/dev/null && break; sleep 1; done
    fi
    if curl -sf localhost:11434/api/tags | grep -q "\"$MODEL\""; then
      LLM_ENV="DALLAL_LLM_BACKEND=ollama DALLAL_LLM_INTERPRET_MODEL=$MODEL"
      echo "LLM: $MODEL via Ollama (reply suggestions on; a person confirms every suggestion)"
    else echo "LLM: model $MODEL not found in Ollama (ollama pull $MODEL) - continuing without it"; fi
  else echo "LLM: ollama not installed - continuing without it"; fi
else echo "LLM: disabled (--no-llm)"; fi

cd "$ROOT/backend"
env DALLAL_ENV=dev DALLAL_RESPONSE_PRIOR_STRENGTH=60 WHATSAPP_MODE=sandbox DALLAL_EXECUTION_MODE=simulated DALLAL_DB="$DB" DALLAL_TIME_SCALE="${DALLAL_TIME_SCALE:-30}" \
    DALLAL_CORS_ORIGINS="http://localhost:$WEB_PORT,http://127.0.0.1:$WEB_PORT" $LLM_ENV \
    nohup .venv/bin/python -m uvicorn dallal.api.app:app --port "$API_PORT" >"$LOGS/backend.log" 2>&1 & echo $! >> "$PIDS"
cd "$ROOT"
NEXT_PUBLIC_DALLAL_API_URL="http://localhost:$API_PORT" nohup npm run dev -- --port "$WEB_PORT" >"$LOGS/frontend.log" 2>&1 & echo $! >> "$PIDS"

for _ in $(seq 1 60); do curl -sf "localhost:$API_PORT/v1/health" >/dev/null && break; sleep 1; done
curl -sf "localhost:$API_PORT/v1/health" >/dev/null || { echo "backend did not start: see $LOGS/backend.log"; exit 1; }
for _ in $(seq 1 90); do curl -sf "localhost:$WEB_PORT" >/dev/null && break; sleep 1; done
echo
echo "Dallal is running"
echo "  operator UI : http://localhost:$WEB_PORT          (top bar should read: Live / Sandbox; open a case)"
echo "  model evidence : http://localhost:$WEB_PORT/models"
echo "  backend     : http://localhost:$API_PORT/v1/meta    logs: $LOGS"
echo "  stop        : ./scripts/demo.sh --stop     reset data: ./scripts/demo.sh --reset"
