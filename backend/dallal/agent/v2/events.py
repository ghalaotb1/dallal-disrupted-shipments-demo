"""Events that resume a paused run. Idempotency is enforced by the store (provider message id) and by the runtime (pending id)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class InquiryResponse:
    inquiry_id: str
    answer_id: str | None  # one of the inquiry's answer ids; None if the reply could not be interpreted
    elapsed_min: float  # minutes between asking and the reply (operational clock)
    raw: dict[str, Any] = field(default_factory=dict)  # original payload summary (text / location / media ref) for audit
    interpretation: dict[str, Any] = field(default_factory=dict)  # how the reply was mapped (method, confidence)
    provider_msg_id: str | None = None
    needs_review: bool = False


@dataclass
class InquiryTimeout:
    inquiry_id: str
    reason: str = "no_response_before_deadline"
