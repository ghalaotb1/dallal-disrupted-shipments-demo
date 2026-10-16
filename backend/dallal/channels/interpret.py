"""Turn an inbound WhatsApp message into one of an inquiry's ANSWER IDS - or into 'needs review'. Never guesses.

Order of trust:
  1. structured replies (interactive id, template quick-reply payload or button text)       confidence 1.0
  2. a shared location, converted to a distance from the delivery address                    confidence 1.0, distance recorded
  3. free text (Arabic / English): normalised keyword match with negation handling          confidence 0.6-0.9, abstains on conflict
  4. anything else (images, voice notes, unknown text)                                       needs_review - stored as evidence, NOT used
The agent only ever receives an answer id from the inquiry's own closed set (or None). An LLM interpreter may be added as a stage
between 3 and 4 (dallal.llm.interpret); it must return one of the allowed ids with a confidence, and is never trusted above 0.9.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from dallal.agent.v2 import inquiry as iq
from dallal.channels.whatsapp import Inbound
from dallal.tools.signals import haversine_m

LOC_MATCH_M, LOC_FAR_M = 150.0, 300.0
OPT_OUT = {"stop", "unsubscribe", "ايقاف", "الغاء الاشتراك", "توقف", "لا تراسلني"}

# Arabic/English lexicons per inquiry. Matching is on normalised tokens/phrases (see `normalise`).
LEX: dict[str, dict[str, list[str]]] = {
    "ask_recipient_availability": {
        "avail_yes": ["نعم", "ايوه", "ايوا", "اي", "متوفر", "موجود", "موجودين", "اكيد", "yes", "available", "sure", "ok", "okay", "home"],
        "avail_no": ["لا", "غير متوفر", "مو موجود", "مب موجود", "مسافر", "خارج", "ما اقدر", "no", "not available", "unavailable", "away", "out"],
        "reschedule": ["موعد اخر", "وقت اخر", "بكره", "بكرة", "غدا", "لاحقا", "بعدين", "اجل", "another time", "later", "tomorrow", "reschedule"],
    },
    "ask_recipient_receipt": {
        "received": ["استلمت", "استلمتها", "وصلتني", "وصلت", "received", "got it", "yes"],
        "not_received": ["لا", "لم استلم", "ما استلمت", "لم تصلني", "ما وصلتني", "لم استلمها", "not received", "didnt receive", "did not receive", "never", "no"],
        "unsure": ["غير متاكد", "مدري", "ما ادري", "not sure", "unsure", "maybe"],
    },
}
NEGATORS = {"لا", "ما", "مو", "مب", "مش", "غير", "لم", "لن", "not", "no", "never", "dont", "didnt", "isnt"}
POLAR_FLIP = {"ask_recipient_availability": {"avail_yes": "avail_no", "avail_no": "avail_yes"}, "ask_recipient_receipt": {"received": "not_received", "not_received": "received"}}


def normalise(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[ً-ٰٟـ]", "", s)  # diacritics and tatweel
    s = s.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"}))
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s)


def _norm_lex(spec_id: str) -> dict[str, list[str]]:
    return {a: [normalise(k) for k in ks] for a, ks in LEX.get(spec_id, {}).items()}


@dataclass
class Interpretation:
    answer_id: str | None
    confidence: float
    method: str
    needs_review: bool = False
    opt_out: bool = False
    details: dict[str, Any] = field(default_factory=dict)


def _match_text(spec_id: str, text: str) -> Interpretation:
    t = normalise(text)
    spans: list[tuple[int, int, str, str]] = []  # (start, end, answer, key)
    for ans, keys in _norm_lex(spec_id).items():
        for k in keys:
            for m in re.finditer(rf"(?<!\w){re.escape(k)}(?!\w)", t):
                spans.append((m.start(), m.end(), ans, k))
    if not spans:
        return Interpretation(None, 0.0, "text_lexicon", True, details={"reason": "no keyword matched"})
    # a keyword inside a longer matched phrase is part of that phrase ("موجود" inside "مو موجود")
    spans = [s for s in spans if not any(o is not s and o[0] <= s[0] and o[1] >= s[1] and (o[1] - o[0]) > (s[1] - s[0]) for o in spans)]
    eff: set[str] = set()
    flipped = multiword = False
    for start, _end, ans, key in spans:
        before = t[:start].split()[-2:]
        negated = any(w in NEGATORS for w in before) and not any(w in NEGATORS for w in key.split())
        multiword |= len(key.split()) > 1
        if negated:
            alt = POLAR_FLIP.get(spec_id, {}).get(ans)
            if alt is None:
                return Interpretation(None, 0.0, "text_lexicon", True, details={"reason": "negated non-polar answer", "matched": ans})
            eff.add(alt)
            flipped = True
        else:
            eff.add(ans)
    if spec_id == "ask_recipient_availability" and {"avail_no", "reschedule"} <= eff and "avail_yes" not in eff:
        eff = {"reschedule"}  # "I can't today, tomorrow is better" is a reschedule request, the more specific answer
    if len(eff) != 1:
        return Interpretation(None, 0.0, "text_lexicon", True, details={"reason": "conflicting keywords", "candidates": sorted(eff)})
    (ans,) = eff
    return Interpretation(ans, 0.7 if flipped else 0.85 if multiword else 0.75, "text_lexicon_negated" if flipped else "text_lexicon", details={"spans": len(spans)})


def interpret(msg: Inbound, spec: iq.InquirySpec, inquiry_id: str, facts: dict[str, Any]) -> Interpretation:
    """Map one inbound message to an answer id of `spec`, or abstain."""
    valid = {a["id"] for a in spec.answers}
    titles = {a["ar"]: a["id"] for a in spec.answers} | {a["en"]: a["id"] for a in spec.answers}

    if msg.kind == "text" and msg.text and normalise(msg.text) in {normalise(x) for x in OPT_OUT}:
        return Interpretation(None, 1.0, "opt_out", False, True)

    def from_id(raw: str | None, method: str) -> Interpretation | None:
        if not raw:
            return None
        if "|" in raw:  # our payload convention: "<inquiry_id>|<answer_id>"
            iid, aid = raw.split("|", 1)
            if iid != inquiry_id:
                return Interpretation(None, 0.0, method, True, details={"reason": "reply is for a different inquiry", "payload_inquiry": iid})
            raw = aid
        return Interpretation(raw, 1.0, method) if raw in valid else None

    if msg.kind == "interactive":
        got = from_id(msg.choice_id, "interactive_id") or (Interpretation(titles[msg.choice_title], 1.0, "interactive_title") if msg.choice_title in titles else None)
        return got or Interpretation(None, 0.0, "interactive", True, details={"reason": "id/title not in this inquiry's answer set"})
    if msg.kind == "button":
        got = from_id(msg.button_payload, "template_payload") or (Interpretation(titles[msg.button_text], 1.0, "template_button_text") if msg.button_text in titles else None)
        return got or Interpretation(None, 0.0, "template_button", True, details={"reason": "payload/text not in this inquiry's answer set"})
    if msg.kind == "location":
        if spec.id != "ask_recipient_location":
            return Interpretation(None, 0.0, "location", True, details={"reason": "location sent in reply to a different question", "lat": msg.lat, "lng": msg.lng})
        if None in (msg.lat, msg.lng, facts.get("dest_lat"), facts.get("dest_lng")):
            return Interpretation(None, 0.0, "location", True, details={"reason": "no destination coordinates to compare"})
        d = haversine_m(msg.lat, msg.lng, facts["dest_lat"], facts["dest_lng"])
        aid = "loc_match" if d <= LOC_MATCH_M else "loc_far" if d > LOC_FAR_M else "loc_unsure"
        return Interpretation(aid, 1.0, "location_distance", details={"distance_m": round(d, 1)})
    if msg.kind == "text" and msg.text:
        r = _match_text(spec.id, msg.text)
        if r.answer_id is None and spec.id == "ask_recipient_location" and any(w in normalise(msg.text) for w in ("العنوان خطا", "العنوان غلط", "wrong address", "address is wrong")):
            return Interpretation("address_wrong_text", 0.8, "text_lexicon")
        return r
    # images, voice notes, stickers... are stored as evidence for a human; they never become an automatic answer in this phase.
    return Interpretation(None, 0.0, f"media:{msg.kind}", True, details={"media_id": msg.media_id, "note": "stored for human review; no automatic inference"})
