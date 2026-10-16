"""LLM access for Dallal: one `chat` entry point over the configured backend.

Backends (env `DALLAL_LLM_BACKEND`): `ollama` (native API, local), `openai` (any OpenAI-compatible endpoint, incl. hosted Qwen), `none` (default when nothing is
configured: every LLM-assisted feature is off and the deterministic paths run). `capabilities()` reports what is actually usable in THIS process.
"""

from __future__ import annotations

import os
import time
from typing import Any

from dallal.llm import ollama, openai_compat
from dallal.llm.ollama import ChatResult, LLMError

__all__ = ["ChatResult", "LLMError", "backend", "capabilities", "chat"]

_CACHE: dict[str, Any] = {"t": 0.0, "v": None}


def backend() -> str:
    b = os.environ.get("DALLAL_LLM_BACKEND", "").lower()
    if b in ("ollama", "openai", "none"):
        return b
    if os.environ.get("DALLAL_LLM_BASE_URL"):
        return "openai"
    return "ollama" if os.environ.get("DALLAL_OLLAMA_URL") else "none"


def chat(model: str, messages: list[dict[str, Any]], **kw: Any) -> ChatResult:
    b = backend()
    if b == "ollama":
        return ollama.chat(model, messages, **kw)
    if b == "openai":
        return openai_compat.chat(model, messages, **kw)
    raise LLMError("no LLM backend configured (DALLAL_LLM_BACKEND=none)")


def capabilities(max_age_s: float = 30.0) -> dict[str, Any]:
    """What an operator can rely on right now. Cached briefly; probing never raises."""
    now = time.time()
    if _CACHE["v"] is not None and now - _CACHE["t"] < max_age_s:
        return _CACHE["v"]
    b = backend()
    out: dict[str, Any] = {"backend": b, "available": False, "interpreter_model": os.environ.get("DALLAL_LLM_INTERPRET_MODEL", ""), "planner": "deterministic EVOI (LLM planner is optional and off)"}
    if b == "ollama":
        models = ollama.available()
        out.update(available=bool(models), models=models, endpoint="local Ollama")
    elif b == "openai":
        out.update(available=True, endpoint="OpenAI-compatible endpoint (configured; not probed)", note="reachability is only known when a call is made")
    else:
        out["note"] = "no LLM backend configured: reply suggestions are off; rules interpret replies"
    out["interpreter_active"] = bool(out["interpreter_model"]) and out["available"]
    _CACHE.update(t=now, v=out)
    return out
