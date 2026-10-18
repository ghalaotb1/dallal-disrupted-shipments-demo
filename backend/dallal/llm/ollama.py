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


def chat_stream(model: str, messages: list[dict[str, Any]], *, temperature: float = 0.1, seed: int = 0, num_predict: int = 420, timeout: float = 120.0, url: str = DEFAULT_URL):
    """Yield content chunks as the model produces them (first yield may take a while when the model has to be loaded). Raises LLMError."""
    body = {"model": model, "messages": messages, "stream": True, "think": False, "keep_alive": "20m", "options": {"temperature": temperature, "seed": seed, "num_predict": num_predict, "num_ctx": 8192}}
    try:
        with requests.post(f"{url}/api/chat", json=body, timeout=timeout, stream=True) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                d = json.loads(line)
                if d.get("error"):
                    raise LLMError(str(d["error"]))
                chunk = (d.get("message") or {}).get("content") or ""
                if chunk:
                    yield chunk
                if d.get("done"):
                    return
    except requests.RequestException as e:
        raise LLMError(f"ollama request failed: {e}") from e


def warm(model: str, url: str = DEFAULT_URL, timeout: float = 120.0) -> float:
    """Load the model into memory (empty prompt) and keep it for 20 minutes. Returns seconds taken."""
    t0 = time.time()
    try:
        requests.post(f"{url}/api/generate", json={"model": model, "prompt": "", "stream": False, "keep_alive": "20m"}, timeout=timeout).raise_for_status()
    except requests.RequestException as e:
        raise LLMError(f"ollama warm-up failed: {e}") from e
    return round(time.time() - t0, 2)
