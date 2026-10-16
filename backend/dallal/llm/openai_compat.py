"""OpenAI-compatible chat client (tool calling). Works with Ollama's /v1 endpoint, vLLM, and hosted providers that serve Qwen behind the
OpenAI protocol (the base URL, key and model name come from the environment; nothing provider-specific is hard-coded).

Environment: DALLAL_LLM_BASE_URL (e.g. http://localhost:11434/v1), DALLAL_LLM_API_KEY (secret, never logged), DALLAL_LLM_REASONING (default "none":
sent as `reasoning_effort`; set empty to omit), DALLAL_LLM_EXTRA_JSON (extra request fields, e.g. '{"enable_thinking": false}' for providers with a different thinking switch).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import requests

from dallal.llm.ollama import ChatResult, LLMError


def chat(model: str, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None, temperature: float = 0.0, seed: int = 0, num_predict: int = 400,
         timeout: float = 60.0, url: str | None = None, **_ignored: Any) -> ChatResult:
    base = (url or os.environ.get("DALLAL_LLM_BASE_URL", "")).rstrip("/")
    if not base:
        raise LLMError("DALLAL_LLM_BASE_URL is not set")
    key = os.environ.get("DALLAL_LLM_API_KEY", "")
    body: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature, "seed": seed, "max_tokens": num_predict, "stream": False}
    if tools:
        body["tools"] = tools
    reasoning = os.environ.get("DALLAL_LLM_REASONING", "none")  # Qwen3.5 thinks by default and can burn the whole token budget; "" omits the field
    if reasoning:
        body["reasoning_effort"] = reasoning
    extra = os.environ.get("DALLAL_LLM_EXTRA_JSON")
    if extra:
        try:
            body.update(json.loads(extra))
        except ValueError as e:
            raise LLMError("DALLAL_LLM_EXTRA_JSON is not valid JSON") from e
    t0 = time.time()
    try:
        r = requests.post(f"{base}/chat/completions", json=body, headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        raise LLMError(f"openai-compatible request failed: {type(e).__name__}") from e  # never echo the URL/headers: they may carry secrets
    d = r.json()
    msg = (d.get("choices") or [{}])[0].get("message", {})
    calls = []
    for c in msg.get("tool_calls") or []:
        fn = c.get("function", {})
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        calls.append({"name": fn.get("name", ""), "arguments": args})
    u = d.get("usage") or {}
    return ChatResult(msg.get("content") or "", calls, round(time.time() - t0, 3), int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)), d)
