"""Hand-written labelled replies (Arabic MSA, Saudi dialect, English, code-mixed) for evaluating free-text reply interpretation.

Authored by the Dallal team for this benchmark - NOT real customer traffic and small (see counts). `None` = the correct behaviour is to
abstain (unrelated, a question back, contradictory or too vague to commit to). Used to compare the rule interpreter with an LLM stage.
"""

from __future__ import annotations

REPLIES: list[tuple[str, str, str | None]] = [
    # ── ask_recipient_availability ──
    *[("ask_recipient_availability", t, "avail_yes") for t in ["نعم متوفر", "ايوه موجود", "أكيد بكون في البيت", "تمام، موجود", "yes I'll be home", "ok available", "موجودين، تفضل", "ايوا بكون موجود", "حياك الله، موجود"]],
    *[("ask_recipient_availability", t, "avail_no") for t in ["لا مو موجود", "مسافر لين الاسبوع الجاي", "ما اقدر اليوم", "not home today", "I'm out of town", "غير متواجد", "للاسف ما راح اكون موجود", "No"]],
    *[("ask_recipient_availability", t, "reschedule") for t in ["بكرة أفضل", "ممكن بعد العصر بكرة؟", "can you come tomorrow instead", "خلها يوم الخميس", "وقت ثاني لو سمحت", "later this week please", "اجلها للاسبوع القادم", "ليس اليوم، غدا افضل"]],
    *[("ask_recipient_availability", t, None) for t in ["مين انت؟", "who is this", "شكرا", "متى بالضبط؟", "اتصل علي", "نعم ولا", "😊", "حاضر"]],
    # ── ask_recipient_receipt ──
    *[("ask_recipient_receipt", t, "received") for t in ["نعم استلمتها", "وصلتني الشحنة شكرا", "استلمتها امس", "received, thanks", "yes got it", "تم الاستلام والحمدلله"]],
    *[("ask_recipient_receipt", t, "not_received") for t in ["لا ما استلمت", "ما وصلني شي", "لم تصل", "never got it", "I didn't receive anything", "No"]],
    *[("ask_recipient_receipt", t, "unsure") for t in ["مدري", "ما أدري يمكن زوجتي استلمتها", "not sure, will check", "خلني اسأل اهل البيت"]],
    *[("ask_recipient_receipt", t, None) for t in ["منو؟", "كم السعر", "شكرا", "?"]],
    # ── ask_courier_status ──
    *[("ask_courier_status", t, "on_route_normal") for t in ["في الطريق، كله طبيعي", "on my way, no issues", "ماشي الامور تمام وبوصل بعد ١٥ دقيقة"]],
    *[("ask_courier_status", t, "at_address_no_answer") for t in ["انا عند العنوان وماحد يرد", "at the address, nobody is answering the door", "واقف عند الباب ولا احد يفتح"]],
    *[("ask_courier_status", t, "cannot_find_address") for t in ["ما لقيت العنوان", "can't find the building", "العنوان مو واضح وانا ضايع"]],
    *[("ask_courier_status", t, "road_blocked") for t in ["الطريق مسكر", "stuck, there is an accident on the road", "في حادث والطريق واقف"]],
    *[("ask_courier_status", t, "never_reached") for t in ["ما وصلت للموقع بعد", "haven't reached the stop yet", "لسا ما وصلت"]],
    *[("ask_courier_status", t, "delivered_handed") for t in ["سلمتها للعميل", "already delivered", "تم التسليم"]],
    *[("ask_courier_status", t, "parcel_missing") for t in ["الشحنة مو معي", "I don't have this parcel on the van", "ما لقيتها في السيارة"]],
    *[("ask_courier_status", t, None) for t in ["ممكن اتصل بك؟", "ok", "الشحنة ايش؟", "wait"]],
    # ── ask_corridor_status ──
    *[("ask_corridor_status", t, "clear") for t in ["سالك", "كل شي تمام", "the road is clear", "مفتوح وما فيه زحمة"]],
    *[("ask_corridor_status", t, "slow_short") for t in ["بطيء شوي، ربع ساعة", "slow but moving, 15 minutes", "زحمة بسيطة وبتفتح قريب", "just slow, 20 min"]],
    *[("ask_corridor_status", t, "blocked_long") for t in ["مغلق تماما يمكن ساعتين", "closed after an accident, hours", "الطريق مسكر لين الليل", "blocked for at least an hour"]],
    *[("ask_corridor_status", t, "dont_know") for t in ["ما اعلم", "no idea", "ما عندي معلومة", "ماني متأكد من الطريق"]],
    *[("ask_corridor_status", t, None) for t in ["اتصل بالمشرف", "who is asking"]],
]
