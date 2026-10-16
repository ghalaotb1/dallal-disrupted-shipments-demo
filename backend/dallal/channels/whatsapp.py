"""WhatsApp Business Platform (Cloud API) integration, with an equivalent sandbox.

Grounded in Meta's documentation (verified 2026-10-15):
  * send:   POST https://graph.facebook.com/<version>/<PHONE_NUMBER_ID>/messages  (Bearer token, JSON body; example version v25.0)
  * the send response means ACCEPTED, not delivered; delivery arrives later as `statuses` webhooks (sent/delivered/read/failed)
  * a user message opens a 24-hour customer-service window; outside it only approved TEMPLATE messages may be sent
  * business-initiated conversations therefore start with a template; opt-in is required
  * interactive reply buttons: max 3, title <= 20 chars, id <= 256 chars; inbound tap = messages[].interactive.button_reply{id,title}
  * template quick-reply tap  = messages[].type == "button" with button{payload,text}; context.id = our outbound message id
  * location share           = messages[].type == "location" with location{latitude,longitude[,name,address]}
  * webhook: GET verify (hub.mode=subscribe, hub.verify_token, hub.challenge -> echo challenge), POST signed with
    X-Hub-Signature-256: sha256=HMAC_SHA256(app_secret, raw_body); retries for up to 7 days => duplicates MUST be tolerated
NOT verified from a fetchable page (flagged in code): the exact SEND-time shape of template quick-reply button parameters.
We use the Cloud API convention (component type "button", sub_type "quick_reply", index, parameters [{type:"payload",payload}]) and
keep it in one function (`template_payload`) so it can be corrected against your WABA without touching anything else.

HONESTY RULES enforced here
  * The sandbox NEVER reports a real delivery. Its states are prefixed `sandbox_` and every receipt carries `real_delivery: False`.
  * The Cloud provider reports only what Meta confirms: `accepted` on a 200 response, later states only from webhooks.
  * The Cloud provider refuses recipients that are not E.164 or not on an explicit allow-list, so fixtures (SANDBOX-nnnn ids)
    can never message a real phone.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

E164 = re.compile(r"^\+?[1-9]\d{7,14}$")
DEFAULT_API_VERSION = "v25.0"
SERVICE_WINDOW_S = 24 * 3600
LIMITS = {"buttons": 3, "button_title": 20, "button_id": 256, "body": 1024, "list_rows": 10, "row_title": 24}


class SendRefused(RuntimeError):
    """A policy or provider refusal; carries a Meta-style error code where one applies."""

    def __init__(self, msg: str, code: int | None = None):
        super().__init__(msg)
        self.code = code


# ── message payload builders (exact Cloud API request bodies) ─────────────────────────────────────────────────────────
def text_payload(to: str, body: str) -> dict[str, Any]:
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "text", "text": {"preview_url": False, "body": body}}


def buttons_payload(to: str, body: str, buttons: list[dict[str, str]]) -> dict[str, Any]:
    if len(buttons) > LIMITS["buttons"]:
        raise SendRefused(f"reply buttons are limited to {LIMITS['buttons']}")
    for b in buttons:
        if len(b["title"]) > LIMITS["button_title"] or len(b["id"]) > LIMITS["button_id"]:
            raise SendRefused(f"button '{b['title']}' exceeds WhatsApp limits")
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "interactive",
            "interactive": {"type": "button", "body": {"text": body[: LIMITS["body"]]},
                            "action": {"buttons": [{"type": "reply", "reply": {"id": b["id"], "title": b["title"]}} for b in buttons]}}}


def list_payload(to: str, body: str, rows: list[dict[str, str]], button_label: str = "Choose") -> dict[str, Any]:
    if len(rows) > LIMITS["list_rows"]:
        raise SendRefused("list messages are limited to 10 rows")
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "interactive",
            "interactive": {"type": "list", "body": {"text": body[: LIMITS["body"]]},
                            "action": {"button": button_label[:20], "sections": [{"title": "Options", "rows": [{"id": r["id"], "title": r["title"][: LIMITS["row_title"]]} for r in rows]}]}}}


def location_request_payload(to: str, body: str) -> dict[str, Any]:
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "type": "interactive", "to": to,
            "interactive": {"type": "location_request_message", "body": {"text": body[: LIMITS["body"]]}, "action": {"name": "send_location"}}}


def template_payload(to: str, name: str, language: str, body_params: list[str], quick_replies: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Template message. Quick-reply button parameters follow the Cloud API convention (see module docstring: verify on your WABA)."""
    components: list[dict[str, Any]] = []
    if body_params:
        components.append({"type": "body", "parameters": [{"type": "text", "text": p} for p in body_params]})
    for i, b in enumerate(quick_replies or []):
        components.append({"type": "button", "sub_type": "quick_reply", "index": str(i), "parameters": [{"type": "payload", "payload": b["payload"]}]})
    return {"messaging_product": "whatsapp", "recipient_type": "individual", "to": to, "type": "template",
            "template": {"name": name, "language": {"code": language}, "components": components}}


# ── inbound parsing ───────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Inbound:
    wamid: str
    sender: str
    timestamp: int
    kind: str  # text | button | interactive | location | image | audio | other
    context_id: str | None = None
    text: str | None = None
    button_payload: str | None = None
    button_text: str | None = None
    choice_id: str | None = None
    choice_title: str | None = None
    lat: float | None = None
    lng: float | None = None
    media_id: str | None = None
    raw_type: str | None = None


@dataclass
class StatusEvt:
    wamid: str
    status: str  # sent | delivered | read | failed | played
    recipient: str
    timestamp: int
    errors: list[dict[str, Any]] = field(default_factory=list)


def parse_webhook(payload: dict[str, Any]) -> tuple[list[Inbound], list[StatusEvt]]:
    msgs: list[Inbound] = []
    stats: list[StatusEvt] = []
    for entry in payload.get("entry", []):
        for ch in entry.get("changes", []):
            v = ch.get("value", {})
            for m in v.get("messages", []) or []:
                t = m.get("type", "other")
                base = dict(wamid=m.get("id", ""), sender=m.get("from", ""), timestamp=int(m.get("timestamp", 0) or 0), context_id=(m.get("context") or {}).get("id"), raw_type=t)
                if t == "text":
                    msgs.append(Inbound(kind="text", text=(m.get("text") or {}).get("body"), **base))
                elif t == "button":
                    b = m.get("button") or {}
                    msgs.append(Inbound(kind="button", button_payload=b.get("payload"), button_text=b.get("text"), **base))
                elif t == "interactive":
                    i = m.get("interactive") or {}
                    r = i.get("button_reply") or i.get("list_reply") or {}
                    msgs.append(Inbound(kind="interactive", choice_id=r.get("id"), choice_title=r.get("title"), **base))
                elif t == "location":
                    loc = m.get("location") or {}
                    msgs.append(Inbound(kind="location", lat=loc.get("latitude"), lng=loc.get("longitude"), text=loc.get("name") or loc.get("address"), **base))
                elif t in ("image", "audio", "voice", "video", "document", "sticker"):
                    media = m.get(t) or {}
                    msgs.append(Inbound(kind="audio" if t in ("audio", "voice") else "image" if t == "image" else "other", media_id=media.get("id"), text=media.get("caption"), **base))
                else:
                    msgs.append(Inbound(kind="other", **base))
            for s in v.get("statuses", []) or []:
                stats.append(StatusEvt(s.get("id", ""), s.get("status", ""), s.get("recipient_id", ""), int(s.get("timestamp", 0) or 0), s.get("errors") or []))
    return msgs, stats


def verify_signature(raw_body: bytes, header: str | None, app_secret: str) -> bool:
    """Constant-time check of X-Hub-Signature-256 over the RAW request body."""
    if not header or not header.startswith("sha256=") or not app_secret:
        return False
    expect = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expect, header.split("=", 1)[1])


def verify_challenge(params: dict[str, str], verify_token: str) -> str | None:
    if params.get("hub.mode") == "subscribe" and hmac.compare_digest(params.get("hub.verify_token", ""), verify_token) and "hub.challenge" in params:
        return params["hub.challenge"]
    return None


def hash_ref(ref: str) -> str:
    """Stable short hash for logs: phone numbers never appear in traces or the audit feed."""
    return hashlib.sha256(("dallal-salt|" + ref).encode()).hexdigest()[:12]


# ── providers ─────────────────────────────────────────────────────────────────────────────────────────────────────────
@dataclass
class Receipt:
    mode: str  # sandbox | cloud
    wamid: str | None
    status: str  # sandbox_accepted | accepted | refused
    real_delivery: bool
    request: dict[str, Any]
    note: str = ""
    error: dict[str, Any] | None = None

    def asdict(self) -> dict[str, Any]:
        d = {"mode": self.mode, "wamid": self.wamid, "status": self.status, "real_delivery": self.real_delivery, "note": self.note, "error": self.error,
             "kind": self.request.get("type"), "template": (self.request.get("template") or {}).get("name"), "to_hash": hash_ref(str(self.request.get("to", "")))}
        return d


class SandboxProvider:
    """Records what a real send WOULD do and enforces the same window/template rules; never touches the network or a phone."""

    mode = "sandbox"

    def __init__(self) -> None:
        self.outbox: list[dict[str, Any]] = []
        self.window_open_until: dict[str, float] = {}
        self.standing_sessions: set[str] = set()  # contacts with a standing operational session (couriers, dispatch) - an assumption, flagged

    def open_window(self, to: str, now: float | None = None) -> None:
        self.window_open_until[to] = (now or time.time()) + SERVICE_WINDOW_S

    def window_open(self, to: str, now: float | None = None) -> bool:
        return to in self.standing_sessions or self.window_open_until.get(to, 0) > (now or time.time())

    def send(self, payload: dict[str, Any], now: float | None = None) -> Receipt:
        to, kind = payload["to"], payload["type"]
        if kind != "template" and not self.window_open(to, now):
            # Meta rejects free-form/interactive messages outside the 24h window (re-engagement error 131047).
            err = {"code": 131047, "title": "Re-engagement message", "message": "More than 24 hours have passed since the recipient last replied"}
            r = Receipt("sandbox", None, "refused", False, payload, "non-template message outside the 24-hour window", err)
            self.outbox.append({"payload": payload, "receipt": r.asdict(), "ts": now or time.time()})
            raise SendRefused(err["message"], 131047)
        wamid = "wamid.SANDBOX" + uuid.uuid4().hex[:24].upper()
        r = Receipt("sandbox", wamid, "sandbox_accepted", False, payload, "SANDBOX: recorded only - no message left this process")
        self.outbox.append({"payload": payload, "receipt": r.asdict(), "ts": now or time.time(), "wamid": wamid})
        return r


class CloudApiProvider:
    """Real WhatsApp Cloud API sender. Needs WHATSAPP_ACCESS_TOKEN + WHATSAPP_PHONE_NUMBER_ID; refuses non-allow-listed recipients."""

    mode = "cloud"

    def __init__(self, token: str | None = None, phone_number_id: str | None = None, version: str | None = None, allowlist: set[str] | None = None, session: Any = None):
        self.token = token or os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
        self.phone_number_id = phone_number_id or os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        self.version = version or os.environ.get("WHATSAPP_API_VERSION", DEFAULT_API_VERSION)
        raw = os.environ.get("WHATSAPP_ALLOWLIST", "")
        self.allowlist = allowlist if allowlist is not None else {x.strip().lstrip("+") for x in raw.split(",") if x.strip()}
        if not (self.token and self.phone_number_id):
            raise RuntimeError("WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID are required for the Cloud API provider")
        if session is None:
            import requests

            session = requests.Session()
        self.session = session

    def send(self, payload: dict[str, Any], now: float | None = None) -> Receipt:
        to = str(payload["to"])
        if not E164.match(to):
            raise SendRefused(f"recipient is not an E.164 number: refusing to send ({hash_ref(to)})")
        if to.lstrip("+") not in self.allowlist:
            raise SendRefused(f"recipient {hash_ref(to)} is not on WHATSAPP_ALLOWLIST: refusing to send")
        url = f"https://graph.facebook.com/{self.version}/{self.phone_number_id}/messages"
        resp = self.session.post(url, headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}, data=json.dumps(payload), timeout=15)
        body = resp.json() if resp.content else {}
        if resp.status_code != 200:
            err = (body or {}).get("error", {"message": f"HTTP {resp.status_code}"})
            return Receipt("cloud", None, "refused", False, payload, "Meta rejected the request", err)
        wamid = (body.get("messages") or [{}])[0].get("id")
        # 200 = ACCEPTED. Delivery is unknown until a `statuses` webhook says so.
        return Receipt("cloud", wamid, "accepted", False, payload, "accepted by the Cloud API; delivery unconfirmed until a status webhook arrives")
