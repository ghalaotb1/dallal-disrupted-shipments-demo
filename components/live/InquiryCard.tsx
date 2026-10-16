"use client";

import { useState } from "react";
import { AlertTriangle, CheckCheck, Clock, MapPin, Send, ShieldQuestion, TimerOff } from "lucide-react";
import { cn } from "@/lib/cn";
import { analystName } from "@/lib/live/payload";
import { api } from "@/lib/live/client";
import { refreshRunNow } from "@/lib/live/feed";
import { Button } from "@/components/common/Button";
import { SandboxTag } from "@/components/live/LiveTags";
import type { LiveInquiry, LiveMessage } from "@/types/live";

const WHO: Record<string, string> = { recipient: "the recipient", courier: "the courier", dispatcher: "the dispatcher", branch_supervisor: "the branch supervisor" };

/** What a delivery state truthfully means. Sandbox and Cloud statuses are never conflated. */
function stateLabel(m: LiveMessage): { text: string; tone: string } {
  if (m.mode === "sandbox") return { text: m.status === "sandbox_delivered" ? "Delivered (sandbox)" : m.status === "sandbox_read" ? "Read (sandbox)" : "Recorded in sandbox · not sent to a phone", tone: "text-warn-700" };
  if (m.status === "accepted") return { text: "Accepted by WhatsApp · delivery unconfirmed", tone: "text-ink-3" };
  if (m.status === "delivered" || m.status === "sent") return { text: m.status === "sent" ? "Sent" : "Delivered", tone: "text-ok-700" };
  if (m.status === "read") return { text: "Read", tone: "text-ok-700" };
  if (m.status === "failed") return { text: "Failed", tone: "text-crit-700" };
  return { text: m.status, tone: "text-ink-3" };
}

const STATUS: Record<string, { label: string; cls: string }> = {
  awaiting: { label: "Waiting for an answer", cls: "bg-review-50 text-review-700 ring-review-200" },
  answered: { label: "Answered", cls: "bg-ok-50 text-ok-700 ring-ok-200" },
  timed_out: { label: "No answer · timed out", cls: "bg-warn-50 text-warn-700 ring-warn-200" },
  opted_out: { label: "Recipient opted out", cls: "bg-muted text-ink-3 ring-line" },
  send_refused: { label: "Not sent", cls: "bg-crit-50 text-crit-700 ring-crit-200" },
};

export function InquiryCard({ inquiry, onChanged }: { inquiry: LiveInquiry; onChanged?: () => Promise<unknown> | void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const sandbox = inquiry.delivery_mode === "sandbox";
  const awaiting = inquiry.status === "awaiting";
  const needsReview = awaiting && inquiry.messages.some((m) => m.direction === "in" && m.interpretation?.needs_review);
  const suggestion = [...inquiry.messages].reverse().find((m) => m.direction === "in" && m.interpretation?.details?.llm_suggestion)?.interpretation?.details?.llm_suggestion;
  const suggested = suggestion ? inquiry.answers.find((a) => a.id === suggestion.answer_id) : undefined;
  const st = STATUS[inquiry.status] ?? { label: inquiry.status, cls: "bg-muted text-ink-3 ring-line" };
  const who = WHO[inquiry.target] ?? inquiry.target;

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      await (onChanged ? onChanged() : refreshRunNow(inquiry.run_id));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-2 overflow-hidden rounded-lg border border-line bg-subtle">
      <div className="flex flex-wrap items-center gap-1.5 border-b border-line-soft bg-surface px-2.5 py-1.5">
        <span className="text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">WhatsApp · to {who}</span>
        {sandbox ? <SandboxTag /> : null}
        <span className={cn("ml-auto rounded-full px-1.5 py-px text-[10.5px] font-medium ring-1", st.cls)}>{st.label}</span>
      </div>

      <div className="space-y-2 px-2.5 py-2.5">
        {inquiry.messages.map((m, i) => {
          const out = m.direction === "out";
          const lab = out ? stateLabel(m) : null;
          return (
            <div key={`${m.wamid ?? i}`} className={cn("flex", out ? "justify-start" : "justify-end")}>
              <div className={cn("max-w-[92%] rounded-lg px-2.5 py-1.5 text-13 leading-5 shadow-[0_1px_1px_rgb(15_30_54/0.06)]", out ? "bg-surface ring-1 ring-line" : "bg-ok-50 ring-1 ring-ok-200")}>
                <p dir="auto" className="whitespace-pre-wrap text-ink">
                  {m.text ?? (m.kind === "location" ? "📍 Shared a location" : m.kind === "image" ? "🖼 Sent an image" : `(${m.kind})`)}
                </p>
                {out && inquiry.question_en ? <p className="mt-0.5 text-xs text-ink-3">EN: {inquiry.question_en}</p> : null}
                {out && m.buttons.length ? (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {m.buttons.map((b) => (
                      <span key={b.id} dir="auto" className="rounded-md bg-brand-25 px-1.5 py-0.5 text-xs text-brand-700 ring-1 ring-brand-200">
                        {b.title}
                      </span>
                    ))}
                  </div>
                ) : null}
                {lab ? (
                  <p className={cn("mt-1 flex items-center gap-1 text-[10.5px]", lab.tone)}>
                    <CheckCheck className="size-3" aria-hidden /> {lab.text}
                  </p>
                ) : m.interpretation ? (
                  <p className="mt-1 text-[10.5px] text-ink-3">
                    read as <span className="font-mono">{m.interpretation.answer_id ?? "—"}</span> · {m.interpretation.method} · confidence {(m.interpretation.confidence ?? 0).toFixed(2)}
                  </p>
                ) : null}
              </div>
            </div>
          );
        })}

        <p className="flex items-start gap-1.5 text-xs leading-4 text-ink-3">
          <ShieldQuestion className="mt-px size-3.5 shrink-0" aria-hidden />
          <span>
            Why the agent asked {who}: databases could not settle the cause, and the answer is expected to change the best action
            {inquiry.net_voi != null ? ` (net value of information ${inquiry.net_voi >= 0 ? "+" : ""}${inquiry.net_voi.toFixed(2)} SAR-equivalent` : ""}
            {inquiry.p_response != null ? `, ${Math.round(inquiry.p_response * 100)}% chance of a reply)` : inquiry.net_voi != null ? ")" : ""}.
          </span>
        </p>

        {needsReview ? (
          <div className="rounded-md border border-warn-200 bg-warn-50 px-2 py-1.5">
            <p className="flex items-center gap-1 text-xs font-medium text-warn-700">
              <AlertTriangle className="size-3.5" aria-hidden /> The reply could not be read safely - a person decides how to use it
            </p>
            {suggestion && suggested ? (
              <div className="mt-1.5 rounded-md bg-surface px-2 py-1.5 text-xs text-ink-2 ring-1 ring-line">
                <p>
                  Language model ({suggestion.model}) suggests <b dir="auto">{suggested.title_en ?? suggested.title}</b> - its own confidence {suggestion.confidence.toFixed(2)} is not calibrated, so a person confirms.
                </p>
                <Button className="mt-1" size="xs" variant="primary" disabled={busy} onClick={() => act(() => api.review(inquiry.inquiry_id, { answer_id: suggestion.answer_id, reviewer: analystName }))}>
                  Accept suggestion
                </Button>
              </div>
            ) : null}
            <div className="mt-1.5 flex flex-wrap gap-1">
              {inquiry.answers.map((a) => (
                <Button key={a.id} size="xs" variant="secondary" disabled={busy} onClick={() => act(() => api.review(inquiry.inquiry_id, { answer_id: a.id, reviewer: analystName }))}>
                  <span dir="auto">{a.title_en ?? a.title}</span>
                </Button>
              ))}
              <Button size="xs" variant="ghost" disabled={busy} onClick={() => act(() => api.review(inquiry.inquiry_id, { answer_id: null, reviewer: analystName }))}>
                Unusable
              </Button>
            </div>
          </div>
        ) : null}

        {awaiting && sandbox && !needsReview ? (
          <div className="rounded-md border border-dashed border-line-strong bg-surface px-2 py-2">
            <p className="text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">Simulated recipient device · reply as {who}</p>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {inquiry.answers.map((a) => (
                <Button key={a.id} size="xs" variant="soft" disabled={busy} onClick={() => act(() => api.sandboxReply({ inquiry_id: inquiry.inquiry_id, kind: "button", answer_id: a.id }))} title={a.title_en}>
                  <span dir="auto">{a.title}</span>
                  {a.title_en ? <span className="font-normal text-ink-3">· {a.title_en}</span> : null}
                </Button>
              ))}
            </div>
            <form
              className="mt-1.5 flex gap-1"
              onSubmit={(e) => {
                e.preventDefault();
                if (!text.trim()) return;
                void act(() => api.sandboxReply({ inquiry_id: inquiry.inquiry_id, kind: "text", text }).then(() => setText("")));
              }}
            >
              <input dir="auto" value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a free-text reply (Arabic or English)…" className="h-7 min-w-0 flex-1 rounded-md border border-line bg-subtle px-2 text-xs outline-none focus:border-brand-400" aria-label="Free-text reply" />
              <Button size="xs" variant="secondary" type="submit" disabled={busy || !text.trim()}>
                <Send /> Send
              </Button>
            </form>
            <div className="mt-1.5 flex flex-wrap gap-1">
              {inquiry.spec === "ask_recipient_location" ? (
                <Button size="xs" variant="secondary" disabled={busy} onClick={() => act(() => api.sandboxReply({ inquiry_id: inquiry.inquiry_id, kind: "location", lat: 26.43, lng: 50.1 }))}>
                  <MapPin /> Share a far-away pin
                </Button>
              ) : null}
              <Button size="xs" variant="ghost" disabled={busy} onClick={() => act(() => api.expire(inquiry.inquiry_id))}>
                <TimerOff /> No reply (let it time out)
              </Button>
            </div>
          </div>
        ) : awaiting && !sandbox ? (
          <p className="flex items-center gap-1 text-xs text-ink-3">
            <Clock className="size-3.5" aria-hidden /> Waiting for {who} to reply on WhatsApp.
          </p>
        ) : null}
        {err ? <p className="text-xs text-crit-700">{err}</p> : null}
      </div>
    </div>
  );
}
