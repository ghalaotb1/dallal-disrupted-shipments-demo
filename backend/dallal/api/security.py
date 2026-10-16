"""Deployment safety: environment modes, fail-closed configuration checks, request limits.

Modes (DALLAL_ENV): `dev` (default, permissive for local work) | `staging` | `production`. In staging/production the process REFUSES TO START unless:
  * DALLAL_API_KEY is set (>= 24 chars) - every /v1 route except /v1/health and the Meta webhook (which has its own signature check) requires it;
  * execution is simulated (the only executor that exists; DALLAL_EXECUTION_MODE=real is rejected);
  * WhatsApp cloud mode, if requested, additionally has DALLAL_ALLOW_REAL_SEND=true, a non-empty WHATSAPP_ALLOWLIST, WHATSAPP_APP_SECRET and
    WHATSAPP_VERIFY_TOKEN. Even then every outbound message is HELD until a supervisor approves it (DALLAL_REQUIRE_SEND_APPROVAL, default true).
In every mode, cloud WhatsApp without DALLAL_ALLOW_REAL_SEND=true is refused: real messages never happen by accident.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class Settings:
    env: str = "dev"
    api_key: str = ""
    whatsapp_mode: str = "sandbox"
    allow_real_send: bool = False
    require_send_approval: bool = True
    execution_mode: str = "simulated"
    allowlist: str = ""
    app_secret: str = ""
    verify_token: str = ""
    cors_origins: list[str] = field(default_factory=list)
    max_body_bytes: int = 512_000
    rate_per_min: int = 240
    backup_dir: str = ""
    backup_every_h: float = 24.0
    backups_keep: int = 7

    @classmethod
    def from_env(cls, e: dict[str, str] | None = None) -> Settings:
        e = dict(os.environ) if e is None else e
        flag = lambda k, d: e.get(k, d).strip().lower() in ("1", "true", "yes", "on")  # noqa: E731
        return cls(env=e.get("DALLAL_ENV", "dev").strip().lower(), api_key=e.get("DALLAL_API_KEY", ""), whatsapp_mode=e.get("WHATSAPP_MODE", "sandbox").strip().lower(),
                   allow_real_send=flag("DALLAL_ALLOW_REAL_SEND", "false"), require_send_approval=flag("DALLAL_REQUIRE_SEND_APPROVAL", "true"),
                   execution_mode=e.get("DALLAL_EXECUTION_MODE", "simulated").strip().lower(), allowlist=e.get("WHATSAPP_ALLOWLIST", ""), app_secret=e.get("WHATSAPP_APP_SECRET", ""),
                   verify_token=e.get("WHATSAPP_VERIFY_TOKEN", ""), cors_origins=[o.strip() for o in e.get("DALLAL_CORS_ORIGINS", "").split(",") if o.strip()],
                   max_body_bytes=int(e.get("DALLAL_MAX_BODY_BYTES", "512000")), rate_per_min=int(e.get("DALLAL_RATE_PER_MIN", "240")), backup_dir=e.get("DALLAL_BACKUP_DIR", ""),
                   backup_every_h=float(e.get("DALLAL_BACKUP_EVERY_H", "24")), backups_keep=int(e.get("DALLAL_BACKUPS_KEEP", "7")))

    @property
    def locked_down(self) -> bool:
        return self.env in ("staging", "production")

    def problems(self) -> list[str]:
        p: list[str] = []
        if self.env not in ("dev", "staging", "production"):
            p.append(f"DALLAL_ENV must be dev|staging|production, got {self.env!r}")
        if self.execution_mode != "simulated":
            p.append("DALLAL_EXECUTION_MODE must be 'simulated': no real operational executor exists, and none can be switched on by configuration alone")
        if self.whatsapp_mode not in ("sandbox", "cloud"):
            p.append("WHATSAPP_MODE must be sandbox|cloud")
        if self.whatsapp_mode == "cloud":
            if not self.allow_real_send:
                p.append("WHATSAPP_MODE=cloud requires DALLAL_ALLOW_REAL_SEND=true (explicit opt-in to real messages)")
            if not [x for x in self.allowlist.split(",") if x.strip()]:
                p.append("WHATSAPP_MODE=cloud requires a non-empty WHATSAPP_ALLOWLIST (E.164 numbers that may ever be messaged)")
            if not (self.app_secret and self.verify_token):
                p.append("WHATSAPP_MODE=cloud requires WHATSAPP_APP_SECRET and WHATSAPP_VERIFY_TOKEN (webhook authenticity)")
        if self.locked_down and len(self.api_key) < 24:
            p.append(f"DALLAL_ENV={self.env} requires DALLAL_API_KEY of at least 24 characters")
        return p

    def enforce(self) -> None:
        probs = self.problems()
        if probs:
            raise RuntimeError("unsafe configuration, refusing to start:\n - " + "\n - ".join(probs))


class RateLimiter:
    """Sliding one-minute window per key. In-memory: one process, which is what a single SQLite writer implies."""

    def __init__(self, per_min: int):
        self.per_min = per_min
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > 60.0:
                q.popleft()
            if len(q) >= self.per_min:
                return False
            q.append(now)
            if len(self.hits) > 5000:  # bound memory under a key-spraying client
                self.hits.clear()
            return True
