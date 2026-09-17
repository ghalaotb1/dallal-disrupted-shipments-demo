"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowUp, Database, RotateCcw, Sparkles, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { SUGGESTED_PROMPTS } from "@/services/demo/assistantService";
import { useUi } from "@/store/ui";
import { askAssistant } from "@/components/assistant/askAssistant";
import { BlockView } from "@/components/assistant/blocks";
import { SimTag } from "@/components/common/Badges";
import type { AssistantMessage } from "@/types/assistant";

const GROUPS = [
  { title: "Situation", prompts: ["What happened today?", "Which shipments need attention right now?", "Are there any active operational incidents?"] },
  { title: "Shipments", prompts: ["Where is DL-20481?", "Why is DL-20334 delayed?", "What did the Agent do for DL-20910?", "Show me high-risk shipments in Dammam."] },
  { title: "Decisions & patterns", prompts: ["Which shipments are waiting for supervisor approval?", "Which route has the most issues today?", "Show recipient-unavailable cases."] },
];

export function AssistantDrawer() {
  const open = useUi((s) => s.assistantOpen);
  const messages = useUi((s) => s.assistantMessages);
  const pending = useUi((s) => s.assistantPending);
  const set = useUi((s) => s.set);
  const reduce = useReducedMotion();
  const [draft, setDraft] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (open) setTimeout(() => input.current?.focus(), 250);
  }, [open]);
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: reduce ? "auto" : "smooth" });
  }, [messages.length, pending, reduce]);

  const send = (text: string) => {
    if (!text.trim()) return;
    setDraft("");
    void askAssistant(text);
  };

  return (
    <AnimatePresence>
      {open ? (
        <motion.aside
          key="assistant"
          role="complementary"
          aria-label="Dallal Assistant"
          initial={reduce ? { opacity: 0 } : { x: 32, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={reduce ? { opacity: 0 } : { x: 32, opacity: 0 }}
          transition={{ type: "spring", stiffness: 420, damping: 40 }}
          className="fixed top-0 right-0 bottom-0 z-[75] flex w-[460px] max-w-[100vw] flex-col border-l border-line bg-canvas shadow-pop"
          onKeyDown={(e) => {
            if (e.key === "Escape") set({ assistantOpen: false });
          }}
        >
          <header className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-line bg-surface px-4">
            <div className="flex items-center gap-2.5">
              <span className="flex size-8 items-center justify-center rounded-lg bg-gradient-to-br from-brand-500 to-brand-700 text-white shadow-[0_1px_2px_rgb(15_30_54/0.25)]">
                <Sparkles className="size-4" aria-hidden />
              </span>
              <div className="leading-tight">
                <div className="text-sm font-semibold text-ink">Dallal Assistant</div>
                <div className="flex items-center gap-1 text-2xs text-ink-3">
                  <Database className="size-3" aria-hidden /> Answers computed from live operations data
                </div>
              </div>
            </div>
            <div className="flex items-center gap-1">
              {messages.length ? (
                <button onClick={() => set({ assistantMessages: [] })} className="rounded-md p-1.5 text-ink-4 hover:bg-hover hover:text-ink-2" aria-label="New conversation" title="New conversation">
                  <RotateCcw className="size-4" />
                </button>
              ) : null}
              <button onClick={() => set({ assistantOpen: false })} className="rounded-md p-1.5 text-ink-4 hover:bg-hover hover:text-ink-2" aria-label="Close assistant">
                <X className="size-4" />
              </button>
            </div>
          </header>

          <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-4 py-4 scrollbar-thin" aria-live="polite">
            {!messages.length ? <Welcome onPick={send} /> : null}
            <div className="space-y-5">
              {messages.map((m) => (
                <Message key={m.id} m={m} onFollowUp={send} />
              ))}
              {pending ? <Thinking /> : null}
            </div>
          </div>

          <footer className="shrink-0 border-t border-line bg-surface px-3 pt-2.5 pb-3">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                send(draft);
              }}
              className="flex items-end gap-2 rounded-xl border border-line bg-surface px-3 py-2 focus-within:border-brand-300 focus-within:ring-2 focus-within:ring-brand-100"
            >
              <label htmlFor="assistant-input" className="sr-only">
                Ask Dallal
              </label>
              <textarea
                id="assistant-input"
                ref={input}
                rows={1}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send(draft);
                  }
                }}
                placeholder="Ask about a shipment, an incident or today’s operations…"
                className="max-h-28 min-h-6 flex-1 resize-none bg-transparent py-1 text-13 text-ink outline-none placeholder:text-ink-4"
              />
              <button type="submit" disabled={!draft.trim() || pending} className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-white transition-colors hover:bg-brand-700 disabled:bg-muted disabled:text-ink-4" aria-label="Send">
                <ArrowUp className="size-4" />
              </button>
            </form>
            <p className="mt-1.5 flex items-center justify-between px-1 text-2xs text-ink-4">
              <span>Prototype intent engine · same response format an LLM with tools would return</span>
              <SimTag />
            </p>
          </footer>
        </motion.aside>
      ) : null}
    </AnimatePresence>
  );
}

function Welcome({ onPick }: { onPick: (p: string) => void }) {
  return (
    <div className="pb-4">
      <div className="rounded-xl border border-line bg-surface p-4">
        <div className="text-15 font-semibold text-ink">Ask Dallal about today&apos;s operations</div>
        <p className="mt-1 text-13 text-ink-3">Answers are built from the same live shipments, incidents and agent runs you see on screen — with charts, cards and map actions, not just text.</p>
      </div>
      <div className="mt-4 space-y-4">
        {GROUPS.map((g) => (
          <div key={g.title}>
            <div className="mb-1.5 px-1 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">{g.title}</div>
            <div className="flex flex-col gap-1.5">
              {g.prompts.map((p) => (
                <button key={p} onClick={() => onPick(p)} className="group flex items-center justify-between gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-left text-13 text-ink-2 transition-colors hover:border-brand-200 hover:bg-brand-25 hover:text-ink">
                  {p}
                  <ArrowUp className="size-3.5 rotate-45 text-ink-5 transition-colors group-hover:text-brand-600" aria-hidden />
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      <p className="sr-only">{SUGGESTED_PROMPTS.length} suggested prompts</p>
    </div>
  );
}

function Message({ m, onFollowUp }: { m: AssistantMessage; onFollowUp: (p: string) => void }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-brand-600 px-3.5 py-2 text-13 text-white">{m.text}</div>
      </div>
    );
  }
  const r = m.response;
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }} className="flex gap-2.5">
      <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-brand-50 text-brand-600">
        <Sparkles className="size-3.5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1 space-y-2.5">
        <p className="text-13 leading-5 text-ink-2">
          <RichText text={m.text} />
        </p>
        {r?.sources.length ? (
          <div className="flex flex-wrap items-center gap-1 text-2xs text-ink-4">
            <Database className="size-3" aria-hidden /> Queried
            {r.sources.map((s) => (
              <span key={s} className="rounded bg-muted px-1 font-mono text-ink-3">
                {s}
              </span>
            ))}
          </div>
        ) : null}
        {r?.blocks.map((b, i) => (
          <motion.div key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 * (i + 1) }}>
            <BlockView block={b} />
          </motion.div>
        ))}
        {r?.followUps.length ? (
          <div className="flex flex-wrap gap-1.5 pt-0.5">
            {r.followUps.map((f) => (
              <button key={f} onClick={() => onFollowUp(f)} className="rounded-full border border-line bg-surface px-2.5 py-1 text-xs text-ink-2 hover:border-brand-200 hover:bg-brand-25 hover:text-ink">
                {f}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </motion.div>
  );
}

/** Minimal, safe inline formatting: **bold** and *emphasis* (no HTML injection). */
function RichText({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g).filter(Boolean);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("**") ? (
          <strong key={i} className="font-semibold text-ink">
            {p.slice(2, -2)}
          </strong>
        ) : p.startsWith("*") ? (
          <em key={i} className="text-ink">
            {p.slice(1, -1)}
          </em>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  );
}

function Thinking() {
  return (
    <div className="flex gap-2.5" role="status">
      <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-brand-50 text-brand-600">
        <Sparkles className="size-3.5 animate-pulse" aria-hidden />
      </span>
      <div className="space-y-2">
        <p className="text-shimmer text-13">Querying live operations data…</p>
        <div className="flex gap-1.5">
          {["shipments", "incidents", "agent runs"].map((s, i) => (
            <span key={s} className={cn("rounded bg-muted px-1.5 py-0.5 font-mono text-2xs text-ink-3")} style={{ animation: `pulse 1.4s ${i * 0.2}s infinite` }}>
              {s}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
