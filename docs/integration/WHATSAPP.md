# WhatsApp in Dallal's reasoning loop

**Status: the full loop works end-to-end against a SANDBOX provider. The official WhatsApp Business Cloud API provider is implemented and unit-tested against recorded payload shapes, but has not been run against Meta's servers** (no business account, phone number or approved templates exist for this project). Nothing in this repository claims a real message was delivered; every sandbox receipt carries `real_delivery: false` and statuses are prefixed `sandbox_`.

## The loop

```
agent reasons ─► databases exhausted? ─► value of asking > cost? ─► pick inquiry + recipient ─► guard ─► send
      ▲                                                                                                  │
      │                                                                                       durable pause (checkpoint)
      └── update belief ◄── interpret reply (closed answer set) ◄── webhook (idempotent) ◄── WhatsApp ◄───┘
                                     │ unreadable / media            timeout ─► "no response" is evidence too
                                     └► human review (never evidence)
```

1. **Why ask** (`dallal/agent/v2/voi.py`): net expected value of information in SAR-equivalents - decision impact, urgency decay, response probability, latency, communication cost, recipient friction and fatigue. Database tools are always exhausted first ("ask only for what you cannot look up").
2. **Whom / what** (`inquiries.yaml`): six inquiries with a *closed* answer set each - recipient availability / location / receipt, courier status, corridor status (dispatcher, shared by every parcel on the corridor), branch backlog. Arabic and English text.
3. **Guard** (`OpsService._guard_send`, `_Guard`): opt-in and opt-out, quiet hours 21:30-08:00 local, at most 2 recipient messages / 24 h, E.164 validation, allowlist for the Cloud provider. A refused send is recorded (`send_refused`) and the agent continues without that evidence.
4. **Send** (`channels/whatsapp.py`): Cloud API (`v25.0`) or Sandbox. Business-initiated messages open with an **approved template**; inside a 24 h customer-service window an interactive message with reply buttons is used. The sandbox enforces the same window (error `131047`).
5. **Pause**: the run is checkpointed as JSON in SQLite (WAL). The process can restart; the run resumes when the answer or the timeout arrives. Late answers re-open a finished run; duplicates and stale events are ignored; webhook idempotency is a `UNIQUE` key in the database, not application memory.
6. **Interpret** (`channels/interpret.py`): button payload `<inquiry_id>|<answer_id>` -> exact; shared location -> distance to the address; free text (Arabic/English) -> keyword match with negation, abstains on conflict; media/voice -> stored for a human, never an automatic answer. An LLM stage may be added between free text and review (`dallal/eval/reply_bench.py` measures it); it can only return one of the inquiry's own answer ids.
7. **Update** (`EnsembleBelief.update`): the answer is a likelihood-weighted observation like any tool. "No response" is also an observation with its own likelihood.
8. **Human oversight**: unreadable replies surface in the UI for an analyst to classify; actions that exceed the autonomy bounds need analyst/supervisor approval; coordinated plans need a supervisor.

## Text, interactive, and later modalities

Implemented: text, interactive buttons (<= 3, titles <= 20 chars, as WhatsApp requires), template quick-reply buttons, location messages. Images, voice notes and documents are *received and stored* (media id kept) but deliberately never converted to an automatic answer; adding them means a transcription / vision stage that returns a closed answer id with a confidence, exactly like the LLM text stage.

## Templates to submit to Meta (UTILITY, languages `ar`, `en_US`)

Definitions live in `dallal/channels/templates.py` (the sandbox renders exactly this text):

| template | parameters | purpose |
|---|---|---|
| `dallal_availability_check` | recipient name, shipment id, merchant, window | will someone be at the address? (buttons: yes / no / another time) |
| `dallal_location_check` | recipient name, shipment id | ask the recipient to share a location pin |
| `dallal_receipt_check` | recipient name, shipment id | delivered-but-disputed check |
| `dallal_branch_check` | branch | is the sorting line backlogged? (internal staff number) |

Staff contacts (courier, dispatcher, branch supervisor) are treated as *standing sessions* in the sandbox (`STANDING` in `service.py`, flagged in `/v1/meta`). In production they need either approved templates or their own 24 h window.

## Setting up the real provider (not done here)

Environment (never committed; `.env.example`-style):

```
WHATSAPP_MODE=cloud
WHATSAPP_ACCESS_TOKEN=...        # system-user token with whatsapp_business_messaging
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_APP_SECRET=...          # verifies X-Hub-Signature-256 on every webhook POST
WHATSAPP_VERIFY_TOKEN=...        # answers Meta's GET handshake (hub.verify_token / hub.challenge)
WHATSAPP_ALLOWLIST=9665XXXXXXXX,...   # only these numbers can ever be messaged (start with your own test numbers)
WHATSAPP_API_VERSION=v25.0
```

Steps: create a Meta app and WhatsApp Business account -> add a phone number (Meta's free test number can message a handful of verified recipients) -> submit the four templates -> in the app's WhatsApp configuration set the webhook callback to `https://<backend>/v1/whatsapp/webhook` with the verify token and subscribe to `messages` -> set `WHATSAPP_MODE=cloud` and redeploy. Webhook POSTs without a valid signature are rejected (`403`). Check Meta's current documentation for template review times, rate/pricing tiers and test-number limits: they change and were not verified here.

## Sandbox for judges

`/v1/sandbox/*` and the "Simulated recipient device" panel in the UI play the recipient: answer buttons, free-text replies (try Arabic dialect), a location pin, "no reply (let it time out)". The same webhook code path processes these replies as real ones, including idempotency and interpretation. Timeouts are real-time scaled by `DALLAL_TIME_SCALE` (e.g. 30 = a 30-minute deadline fires after 1 minute).

## What is measured, what is not

* Reply interpretation (rules vs LLM stage) on a small hand-written Arabic/English set: [`docs/experiments/reply_interpretation.json`](../experiments/reply_interpretation.json). It is **not** real customer traffic.
* Response rates and latencies used by the value-of-information model are **assumptions** (`inquiries.yaml`); with real traffic they should be re-estimated per recipient segment and time of day, and the model already supports per-recipient overrides.
