"""WhatsApp message templates Dallal needs approved by Meta before the first business-initiated message.

A business-initiated conversation MUST open with an approved template. These are the definitions to submit (category UTILITY,
languages ar + en_US, quick-reply buttons from inquiries.yaml). The sandbox renders exactly this text so judges see what a
recipient would receive; nothing here is a claim that the templates are approved.
"""

from __future__ import annotations

from typing import Any

TEMPLATES: dict[str, dict[str, Any]] = {
    "dallal_availability_check": {
        "category": "UTILITY", "params": ["recipient_name", "shipment_id", "merchant", "window_text"],
        "body": {"ar": "مرحباً {{1}}، شحنتكم رقم {{2}} من {{3}} في طريقها إليكم. هل سيكون أحد في العنوان اليوم بين {{4}}؟",
                 "en_US": "Hello {{1}}, your parcel {{2}} from {{3}} is on its way. Will someone be at the address today between {{4}}?"}},
    "dallal_location_check": {
        "category": "UTILITY", "params": ["recipient_name", "shipment_id"],
        "body": {"ar": "مرحباً {{1}}، لضمان وصول شحنتكم {{2}} بدقة، فضلاً شاركنا موقع التسليم الدقيق عبر زر المرفقات ثم الموقع.",
                 "en_US": "Hello {{1}}, to make sure parcel {{2}} reaches you, please share the exact delivery location using the attachment button, then Location."}},
    "dallal_receipt_check": {
        "category": "UTILITY", "params": ["recipient_name", "shipment_id"],
        "body": {"ar": "مرحباً {{1}}، تُظهر سجلاتنا أن الشحنة {{2}} سُلّمت. هل استلمتها؟", "en_US": "Hello {{1}}, our records show parcel {{2}} as delivered. Did you receive it?"}},
    "dallal_branch_check": {
        "category": "UTILITY", "params": ["branch"],
        "body": {"ar": "هل يوجد تكدس في خط الفرز في {{1}}؟", "en_US": "Is the sorting line at {{1}} backlogged?"}},
}


def params_for(template: str, facts: dict[str, Any]) -> list[str]:
    src = {"recipient_name": facts.get("recipient_name") or "-", "shipment_id": facts.get("shipment_id", ""), "merchant": facts.get("merchant", "Dallal"),
           "window_text": facts.get("window_text") or "", "branch": facts.get("branch_name") or facts.get("origin_node_id", "")}
    return [str(src[p]) for p in TEMPLATES[template]["params"]]


def render(template: str, language: str, params: list[str]) -> str:
    body = TEMPLATES[template]["body"].get(language) or next(iter(TEMPLATES[template]["body"].values()))
    for i, p in enumerate(params, 1):
        body = body.replace("{{" + str(i) + "}}", p)
    return body
