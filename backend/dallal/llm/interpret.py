"""LLM reply-interpretation stage: SUGGESTS one of an inquiry's own answer ids for a free-text reply the rules could not read.

Design rules:
  * native tool calling with an enum-constrained argument (Qwen3.5 under Ollama ignores `format` JSON schemas; it follows tool calls);
  * the answer must be in the closed set - anything else is discarded;
  * the stated confidence is the model's own and is NOT calibrated (a contradictory "yes and no" came back at 0.95 in our benchmark), so a
    suggestion never becomes evidence by itself: it is shown to a human reviewer, who accepts or overrides it in one click.
"""

from __future__ import annotations

from dataclasses import dataclass

from dallal.agent.v2 import inquiry as iq
from dallal.llm import ollama

SYSTEM = ("You read a short WhatsApp reply (Arabic, Saudi dialect, English or mixed) from a person who was asked one question by a postal operator. "
          "Map the reply to exactly one of the allowed answer ids, or to \"none\" if the reply does not clearly answer the question, answers something else, "
          "asks a question back, or is contradictory. Do not guess. Give your confidence between 0 and 1.")


@dataclass
class Suggestion:
    answer_id: str | None
    confidence: float
    latency_s: float
    model: str


def suggest(model: str, spec: iq.InquirySpec, text: str, facts: dict | None = None) -> Suggestion:
    ids = [a["id"] for a in spec.answers]
    tool = {"type": "function", "function": {"name": "report_answer", "description": "Report which allowed answer the reply gives, or none.",
                                             "parameters": {"type": "object", "properties": {"answer_id": {"type": "string", "enum": [*ids, "none"]}, "confidence": {"type": "number", "description": "0 to 1"}},
                                                            "required": ["answer_id", "confidence"]}}}
    q = iq.render_question(spec, facts or {"window_text": "14:00-18:00", "corridor_id": "DK-04", "branch_name": "Dammam", "shipment_id": "DL-1"}, "en")
    opts = "; ".join(f"{a['id']} = {a['en']}" for a in spec.answers)
    user = f"Question asked: {q}\nAllowed answers: {opts}\nReply: {text}\nCall report_answer."
    try:
        r = ollama.chat(model, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], tools=[tool], num_predict=120, timeout=60.0)
    except ollama.LLMError:
        return Suggestion(None, 0.0, 0.0, model)
    if not r.tool_calls or r.tool_calls[0]["name"] != "report_answer":
        return Suggestion(None, 0.0, r.latency_s, model)
    try:
        args = r.tool_calls[0]["arguments"]
        a = str(args["answer_id"])
        c = float(args["confidence"])
    except (KeyError, ValueError, TypeError):
        return Suggestion(None, 0.0, r.latency_s, model)
    if a not in ids:  # "none" or outside the closed set
        return Suggestion(None, c if a == "none" else 0.0, r.latency_s, model)
    return Suggestion(a, max(0.0, min(1.0, c)), r.latency_s, model)
