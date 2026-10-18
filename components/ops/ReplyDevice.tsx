"use client";

import { useState } from "react";
import { CheckCheck, Send, Smartphone, TimerOff } from "lucide-react";
import { cn } from "@/lib/cn";
import { letItTimeOut, reviewReply, sendReply } from "@/lib/ops/agent";
import { WHO } from "@/lib/ops/narrative";
import { useOpsUi } from "@/store/ops";
import { Button } from "@/components/common/Button";
import type { LiveInquiry, LiveMessage } from "@/types/live";

function delivery(m: LiveMessage): string {
  if (m.status === "held_for_approval") return "Held - not sent until a manager approves";
  if (m.mode === "sandbox") return "Sandbox · not sent to a phone";
  return m.status;
}

/**
 * The WhatsApp question Dallal sent (SANDBOX: nothing reaches a phone) and a simulated device to answer it as the person asked.
 * Free text goes through the real reply interpreter; an unclear reply is held for a person, with an optional local-model suggestion.
 */
export function ReplyDevice({ inquiry, run, plan, suggested, who: whoName, auto }: { inquiry: LiveInquiry; run?: string; plan?: string; suggested?: string; who?: string; auto?: "typing" | "sent" | "failed" }) {
  const busy = useOpsUi((s) => s.busy === "reply");
  const [text, setText] = useState("");
  const out = inquiry.messages.find((m) => m.direction === "out");
  const incoming = inquiry.messages.filter((m) => m.direction === "in");
  const awaiting = inquiry.status === "awaiting";
  const review = awaiting && incoming.some((m) => m.interpretation?.needs_review);
  const suggestion = [...incoming].reverse().find((m) => m.interpretation?.details?.llm_suggestion)?.interpretation?.details?.llm_suggestion;
  const suggestedAns = suggestion ? inquiry.answers.find((a) => a.id === suggestion.answer_id) : undefined;
  const who = whoName ?? WHO[inquiry.target] ?? inquiry.target;

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-subtle">
      <div className="flex items-center gap-2 border-b border-line-soft bg-surface px-3 py-2">
        <Smartphone className="size-3.5 text-ink-4" aria-hidden />
        <span className="text-xs font-semibold text-ink">WhatsApp to {who}</span>
        <span className="rounded bg-warn-50 px-1.5 py-px text-[10px] font-semibold text-warn-700 uppercase ring-1 ring-warn-200">Sandbox</span>
        <span className={cn("ml-auto rounded-full px-2 py-px text-[11px] font-medium ring-1", awaiting ? "bg-review-50 text-review-700 ring-review-200" : inquiry.status === "answered" ? "bg-ok-50 text-ok-700 ring-ok-200" : "bg-warn-50 text-warn-700 ring-warn-200")}>
          {awaiting ? "Waiting for a reply" : inquiry.status === "answered" ? "Answered" : inquiry.status === "timed_out" ? "No reply" : inquiry.status}
        </span>
      </div>
      <div className="space-y-2 px-3 py-3">
        {out ? (
          <div className="max-w-[92%] rounded-xl rounded-tl-sm bg-surface px-3 py-2 text-13 leading-5 shadow-card ring-1 ring-line">
            <p dir="auto" className="whitespace-pre-wrap text-ink">{out.text}</p>
            {inquiry.question_en ? <p className="mt-1 text-xs text-ink-3">{inquiry.question_en}</p> : null}
            <p className="mt-1 flex items-center gap-1 text-[10.5px] text-warn-700">
              <CheckCheck className="size-3" aria-hidden /> {delivery(out)}
            </p>
          </div>
        ) : null}
        {incoming.map((m, i) => (
          <div key={i} className="ml-auto max-w-[88%] rounded-xl rounded-tr-sm bg-ok-50 px-3 py-2 text-13 text-ink ring-1 ring-ok-200">
            <p dir="auto">{inquiry.answers.find((a) => a.id === m.interpretation?.answer_id)?.title ?? m.text ?? "(reply)"}</p>
            {m.interpretation ? (
              <p className="mt-0.5 text-[10.5px] text-ink-3">
                read as <b>{inquiry.answers.find((a) => a.id === m.interpretation?.answer_id)?.title_en ?? m.interpretation.answer_id ?? "unclear"}</b>
                {auto ? " · simulated reply (sandbox)" : ""}
              </p>
            ) : null}
          </div>
        ))}

        {review ? (
          <div className="rounded-lg border border-warn-200 bg-warn-50 px-3 py-2">
            <p className="text-xs font-medium text-warn-700">Unclear reply. A person decides.</p>
            {suggestion && suggestedAns ? (
              <div className="mt-2 rounded-md bg-surface px-2.5 py-2 text-xs text-ink-2 ring-1 ring-line">
                Local model ({suggestion.model}) suggests <b>{suggestedAns.title_en ?? suggestedAns.title}</b>. You confirm.
                <Button className="mt-1.5 ml-2" size="xs" variant="primary" disabled={busy} onClick={() => reviewReply(inquiry.inquiry_id, run, plan, suggestion.answer_id)}>
                  Accept suggestion
                </Button>
              </div>
            ) : null}
            <div className="mt-2 flex flex-wrap gap-1">
              {inquiry.answers.map((a) => (
                <Button key={a.id} size="xs" variant="secondary" disabled={busy} onClick={() => reviewReply(inquiry.inquiry_id, run, plan, a.id)}>
                  {a.title_en ?? a.title}
                </Button>
              ))}
            </div>
          </div>
        ) : null}

        {awaiting && !review && (auto === "typing" || auto === "sent") ? (
          <div className="flex items-center gap-2 rounded-lg border border-dashed border-line-strong bg-surface px-3 py-2.5 text-xs text-ink-3">
            <span className="flex gap-0.5" aria-hidden>
              {[0, 1, 2].map((i) => (
                <span key={i} className="size-1.5 animate-pulse rounded-full bg-ink-4" style={{ animationDelay: `${i * 200}ms` }} />
              ))}
            </span>
            <span>
              {who} is replying · <b className="font-medium text-ink-2">sandbox simulation</b>, not WhatsApp
            </span>
          </div>
        ) : null}

        {awaiting && !review && auto !== "typing" && auto !== "sent" ? (
          <div className="rounded-lg border border-dashed border-line-strong bg-surface px-3 py-2.5">
            <p className="text-[10.5px] font-semibold tracking-[0.06em] text-ink-4 uppercase">Reply as {who}</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {inquiry.answers.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  disabled={busy}
                  onClick={() => sendReply(inquiry.inquiry_id, { run, plan }, { kind: "button", answer_id: a.id })}
                  className={cn("rounded-lg border px-2.5 py-1.5 text-left text-xs transition-colors disabled:opacity-50", a.id === suggested ? "border-brand-300 bg-brand-50 text-brand-800 ring-2 ring-brand-100 hover:bg-brand-100" : "border-line bg-surface text-ink-2 hover:bg-hover")}
                >
                  <span dir="auto" className="block font-medium">{a.title}</span>
                  {a.title_en ? <span className="block text-[10.5px] text-ink-3">{a.title_en}</span> : null}
                </button>
              ))}
            </div>
            <form
              className="mt-2 flex gap-1.5"
              onSubmit={(e) => {
                e.preventDefault();
                if (!text.trim()) return;
                void sendReply(inquiry.inquiry_id, { run, plan }, { kind: "text", text }).then(() => setText(""));
              }}
            >
              <input dir="auto" value={text} onChange={(e) => setText(e.target.value)} placeholder="Or type a reply (Arabic / English)" aria-label="Free-text reply" className="h-8 min-w-0 flex-1 rounded-lg border border-line bg-subtle px-2.5 text-xs outline-none focus:border-brand-400" />
              <Button size="sm" variant="secondary" type="submit" disabled={busy || !text.trim()}>
                <Send /> Send
              </Button>
              <Button size="sm" variant="ghost" type="button" disabled={busy} onClick={() => letItTimeOut(inquiry.inquiry_id, run, plan)} title="Let the question expire with no reply">
                <TimerOff /> No reply
              </Button>
            </form>
          </div>
        ) : null}
      </div>
    </div>
  );
}
