"""WhatsAppChannel: turns the agent's PendingInquiry into the right Cloud API request and sends it through a provider."""

from __future__ import annotations

from typing import Any

from dallal.channels import templates as tpl
from dallal.channels import whatsapp as wa

LANG_CODE = {"ar": "ar", "en": "en_US"}


class WhatsAppChannel:
    def __init__(self, provider: Any, on_sent: Any = None):
        self.provider = provider
        self.on_sent = on_sent  # callback(pending, receipt, payload) for persistence

    def build_payload(self, pending: Any, facts: dict[str, Any]) -> dict[str, Any]:
        to = str(pending.recipient_ref)
        answers = [{"id": f"{pending.inquiry_id}|{a['id']}", "title": a["title"]} for a in pending.answers]
        lang = LANG_CODE.get(pending.lang, pending.lang)
        if pending.mode in ("template_buttons", "template_location"):
            name = pending.template or "dallal_generic"
            qr = [{"payload": a["id"], "title": a["title"]} for a in answers] if pending.mode == "template_buttons" else []
            return wa.template_payload(to, name, lang, tpl.params_for(name, facts), qr)
        if pending.mode == "list":
            return wa.list_payload(to, pending.question, answers)
        return wa.text_payload(to, pending.question)

    def send_inquiry(self, pending: Any, facts: dict[str, Any], run_id: str | None = None) -> dict[str, Any]:
        try:
            payload = self.build_payload(pending, facts)
            receipt = self.provider.send(payload)
        except wa.SendRefused as e:
            rd = {"mode": self.provider.mode, "status": "refused", "real_delivery": False, "error": {"message": str(e), "code": e.code}, "wamid": None}
            if self.on_sent:
                self.on_sent(pending, rd, None)
            return rd
        rd = receipt.asdict()
        if self.on_sent:
            self.on_sent(pending, rd, payload)
        return rd
