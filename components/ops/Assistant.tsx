"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, Briefcase, Loader2, Package, Truck } from "lucide-react";
import { cn } from "@/lib/cn";
import { SUGGESTIONS } from "@/lib/ops/assistant";
import { openCase } from "@/lib/ops/agent";
import { prepareAssistant, sendQuestion } from "@/lib/ops/assistantChat";
import { getOps, setUi, useOpsUi } from "@/store/ops";
import type { AssistantMessage } from "@/types/ops";

type Target = { kind: "case"; id: "A" | "B" | "C" } | { kind: "parcel"; id: string } | { kind: "driver"; id: string };

function follow(t: Target) {
  setUi({ tab: "cases" });
  if (t.kind === "case") openCase(t.id);
  else if (t.kind === "parcel") {
    const p = getOps().parcels[t.id];
    const c = getOps().cases.find((x) => x.parcelId === t.id);
    if (c) openCase(c.scenario);
    else setUi({ openCaseId: null, selectedParcelId: t.id, selectedDriverId: p?.driverId ?? null, expandedDriverIds: p ? [p.driverId] : [] });
  } else setUi({ openCaseId: null, selectedParcelId: null, selectedDriverId: t.id, expandedDriverIds: [t.id] });
}

function sourceTarget(s: NonNullable<AssistantMessage["sources"]>[number]): Target | null {
  const w = getOps();
  if (s.type === "parcel") return { kind: "parcel", id: s.id };
  if (s.type === "driver") return { kind: "driver", id: s.id };
  if (s.type === "run") {
    const c = w.cases.find((x) => x.runId === s.id);
    return c ? { kind: "case", id: c.scenario } : null;
  }
  if (s.type === "plan") {
    const c = w.cases.find((x) => x.planId === s.id);
    return c ? { kind: "case", id: c.scenario } : null;
  }
  return null;
}

const ICON = { case: Briefcase, parcel: Package, driver: Truck } as const;

/** Render **bold** as bold; the model often uses it. Everything else stays plain text. */
function Rich({ text }: { text: string }) {
  return (
    <>
      {text.split(/(\*\*[^*]+\*\*)/g).map((part, i) => (part.startsWith("**") && part.endsWith("**") ? <b key={i}>{part.slice(2, -2)}</b> : <span key={i}>{part}</span>))}
    </>
  );
}

function ModelStatus() {
  const m = useOpsUi((s) => s.assistantModel);
  const dot = m.state === "ready" ? "bg-ok-500" : m.state === "loading" ? "bg-warn-500 animate-pulse" : m.state === "unavailable" ? "bg-ink-4" : "bg-ink-5";
  const label = m.state === "ready" ? `Qwen · local${m.model ? ` · ${m.model}` : ""}` : m.state === "loading" ? "Loading the local model…" : m.state === "unavailable" ? "Qwen unavailable · basic answers" : "Local model";
  return (
    <p className="flex items-center gap-1.5 pb-2 text-[11px] text-ink-4" title={m.reason}>
      <span className={cn("size-1.5 rounded-full", dot)} aria-hidden /> {label}
      <span className="ml-auto">Answers use live data</span>
    </p>
  );
}

/** Ask about the operation in Arabic or English. A local Qwen model answers from the live operation and the agent's own records; it never decides anything. */
export function Assistant() {
  const messages = useOpsUi((s) => s.assistant);
  const [draft, setDraft] = useState("");
  const end = useRef<HTMLDivElement>(null);
  const busy = messages.some((m) => m.role === "assistant" && (m.status === "thinking" || m.status === "streaming"));
  useEffect(() => {
    void prepareAssistant();
  }, []);
  const lastText = messages[messages.length - 1]?.text.length ?? 0;
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, lastText]);

  const send = (text: string) => {
    if (!text.trim() || busy) return;
    setDraft("");
    void sendQuestion(text);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <ModelStatus />
      <div className="scrollbar-thin min-h-0 flex-1 space-y-3 overflow-y-auto py-1">
        {!messages.length ? (
          <div className="space-y-2">
            <p className="text-13 font-medium text-ink">Ask about your operation · اسأل عن عملياتك</p>
            <div className="flex flex-col gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" dir="auto" onClick={() => send(s)} className="rounded-lg border border-line bg-surface px-3 py-2 text-start text-13 text-ink-2 transition-colors hover:border-brand-200 hover:bg-brand-25 hover:text-ink">
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        {messages.map((m) =>
          m.role === "user" ? (
            <div key={m.id} dir="auto" className="ms-auto max-w-[85%] rounded-xl bg-brand-600 px-3 py-2 text-13 text-white">
              {m.text}
            </div>
          ) : (
            <div key={m.id} className="max-w-[96%] space-y-2 rounded-xl bg-subtle px-3 py-2.5 text-13 leading-5 text-ink ring-1 ring-line-soft">
              {m.status === "thinking" ? (
                <p className="flex items-center gap-2 text-xs text-ink-3">
                  <Loader2 className="size-3.5 animate-spin" aria-hidden /> {m.phase ?? "Thinking…"}
                </p>
              ) : null}
              {m.phase && m.status !== "thinking" ? <p className="text-xs text-ink-3">{m.phase}</p> : null}
              {m.text ? (
                <p dir="auto" className="whitespace-pre-line">
                  <Rich text={m.text} />
                  {m.status === "streaming" ? <span className="ms-0.5 inline-block h-3.5 w-[2px] animate-pulse bg-ink-3 align-middle" aria-hidden /> : null}
                </p>
              ) : null}
              {m.status === "done" ? (
                <p className="text-[10.5px] text-ink-4">
                  {m.mode === "qwen" && m.meta ? `Qwen (${m.meta.model}) · local · ${m.meta.latencyS.toFixed(1)} s` : "Basic answer (no language model)"}
                  {m.note ? ` · ${m.note}` : ""}
                </p>
              ) : null}
              {m.status === "done" && m.mode === "qwen" && m.sources?.length ? (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-[10.5px] text-ink-4">Based on</span>
                  {m.sources.map((s) => {
                    const t = sourceTarget(s);
                    return t ? (
                      <button key={`${s.type}:${s.id}`} type="button" onClick={() => follow(t)} className="rounded-md bg-surface px-1.5 py-0.5 text-[11px] font-medium text-brand-700 ring-1 ring-brand-200 hover:bg-brand-50">
                        {s.label}
                      </button>
                    ) : (
                      <span key={`${s.type}:${s.id}`} className="rounded-md bg-surface px-1.5 py-0.5 text-[11px] text-ink-3 ring-1 ring-line">
                        {s.label}
                      </span>
                    );
                  })}
                </div>
              ) : null}
              {m.status === "done" && m.mode === "basic" && m.links?.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {m.links.map((l, i) => {
                    const Icon = ICON[l.target.kind];
                    return (
                      <button key={i} type="button" onClick={() => follow(l.target)} className="flex items-center gap-1.5 rounded-lg bg-surface px-2 py-1 text-xs font-medium text-brand-700 ring-1 ring-brand-200 hover:bg-brand-50">
                        <Icon className="size-3.5" aria-hidden /> {l.label}
                        {l.sub ? <span className="font-normal text-ink-4">· {l.sub}</span> : null}
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
          ),
        )}
        <div ref={end} aria-hidden />
      </div>
      {messages.length ? (
        <div className="flex flex-wrap gap-1 pb-2">
          {SUGGESTIONS.filter((_, i) => i === 0 || i === 3).map((s) => (
            <button key={s} type="button" dir="auto" disabled={busy} onClick={() => send(s)} className="rounded-full bg-muted px-2.5 py-1 text-xs text-ink-3 hover:bg-hover hover:text-ink disabled:opacity-50">
              {s}
            </button>
          ))}
        </div>
      ) : null}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
        className="flex items-center gap-2 rounded-xl border border-line bg-surface px-3 py-1.5 focus-within:border-brand-300 focus-within:ring-2 focus-within:ring-brand-100"
      >
        <label htmlFor="assistant-input" className="sr-only">
          Ask Dallal
        </label>
        <input id="assistant-input" dir="auto" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask in Arabic or English…" className="h-8 min-w-0 flex-1 bg-transparent text-13 text-ink outline-none placeholder:text-ink-4" />
        <button type="submit" disabled={!draft.trim() || busy} className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:bg-muted disabled:text-ink-4" aria-label="Send">
          <ArrowUp className="size-4" />
        </button>
      </form>
    </div>
  );
}
