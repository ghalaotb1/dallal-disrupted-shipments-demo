"""Minimal Ollama chat client (local models: no data leaves the machine, no API key, no per-call cost).

Only what Dallal needs: native tool calling, JSON-schema constrained output, deterministic sampling, latency and token accounting.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import requests

DEFAULT_URL = os.environ.get("DALLAL_OLLAMA_URL", "http://localhost:11434")


class LLMError(RuntimeError):
    pass


@dataclass
class ChatResult:
    content: str
    tool_calls: list[dict[str, Any]]
    latency_s: float
    prompt_tokens: int
    output_tokens: int
    raw: dict[str, Any] = field(default_factory=dict)

    def json(self) -> Any:
        return json.loads(self.content)


def available(url: str = DEFAULT_URL, timeout: float = 1.5) -> list[str]:
    try:
        r = requests.get(f"{url}/api/tags", timeout=timeout)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except requests.RequestException:
        return []


def chat(model: str, messages: list[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None, schema: dict[str, Any] | None = None, think: bool = False,
         temperature: float = 0.0, seed: int = 0, num_predict: int = 400, timeout: float = 180.0, url: str = DEFAULT_URL) -> ChatResult:
    body: dict[str, Any] = {"model": model, "messages": messages, "stream": False, "think": think, "keep_alive": "20m",
                            "options": {"temperature": temperature, "seed": seed, "num_predict": num_predict, "num_ctx": 8192}}
    if tools:
        body["tools"] = tools
    if schema:
        body["format"] = schema
    t0 = time.time()
    try:
        r = requests.post(f"{url}/api/chat", json=body, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        raise LLMError(f"ollama request failed: {e}") from e
    d = r.json()
    msg = d.get("message", {})
    calls = [{"name": c["function"]["name"], "arguments": c["function"].get("arguments", {})} for c in msg.get("tool_calls", []) or []]
    return ChatResult(msg.get("content", "") or "", calls, round(time.time() - t0, 3), int(d.get("prompt_eval_count", 0)), int(d.get("eval_count", 0)), d)
