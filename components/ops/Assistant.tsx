"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, Briefcase, Truck, Package } from "lucide-react";
import { ask, SUGGESTIONS } from "@/lib/ops/assistant";
import { openCase } from "@/lib/ops/agent";
import { getOps, getUi, setUi, useOpsUi } from "@/store/ops";
import type { AssistantMessage } from "@/types/ops";

let seq = 0;

function follow(t: NonNullable<AssistantMessage["links"]>[number]["target"]) {
  setUi({ tab: "cases" });
  if (t.kind === "case") openCase(t.id);
  else if (t.kind === "parcel") {
    const p = getOps().parcels[t.id];
    const c = getOps().cases.find((x) => x.parcelId === t.id);
    if (c) openCase(c.scenario);
    else setUi({ openCaseId: null, selectedParcelId: t.id, selectedDriverId: p?.driverId ?? null, expandedDriverIds: p ? [p.driverId] : [] });
  } else setUi({ openCaseId: null, selectedParcelId: null, selectedDriverId: t.id, expandedDriverIds: [t.id] });
}

const ICON = { case: Briefcase, parcel: Package, driver: Truck } as const;

/** Ask about the operation in plain words. Answers are computed from the live drivers, parcels, runs and plans. */
export function Assistant() {
  const messages = useOpsUi((s) => s.assistant);
  const [draft, setDraft] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  const send = (text: string) => {
    const t = text.trim();
    if (!t) return;
    setDraft("");
    const a = ask(t, getOps());
    setUi({ assistant: [...getUi().assistant, { id: `u${++seq}`, role: "user", text: t }, { id: `a${++seq}`, role: "assistant", ...a }] });
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="scrollbar-thin min-h-0 flex-1 space-y-3 overflow-y-auto py-1">
        {!messages.length ? (
          <div className="space-y-2">
            <p className="text-13 font-medium text-ink">Ask about your operation</p>
            <div className="flex flex-col gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button key={s} type="button" onClick={() => send(s)} className="rounded-lg border border-line bg-surface px-3 py-2 text-left text-13 text-ink-2 transition-colors hover:border-brand-200 hover:bg-brand-25 hover:text-ink">
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : null}
        {messages.map((m) =>
          m.role === "user" ? (
            <div key={m.id} className="ml-auto max-w-[85%] rounded-xl rounded-tr-sm bg-brand-600 px-3 py-2 text-13 text-white">
              {m.text}
            </div>
          ) : (
            <div key={m.id} className="max-w-[95%] space-y-2 rounded-xl rounded-tl-sm bg-subtle px-3 py-2.5 text-13 leading-5 text-ink ring-1 ring-line-soft">
              <p className="whitespace-pre-line">{m.text}</p>
              {m.links?.length ? (
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
          {SUGGESTIONS.slice(0, 3).map((s) => (
            <button key={s} type="button" onClick={() => send(s)} className="rounded-full bg-muted px-2.5 py-1 text-xs text-ink-3 hover:bg-hover hover:text-ink">
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
        <input id="assistant-input" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Ask about a parcel, driver or route…" className="h-8 min-w-0 flex-1 bg-transparent text-13 text-ink outline-none placeholder:text-ink-4" />
        <button type="submit" disabled={!draft.trim()} className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:bg-muted disabled:text-ink-4" aria-label="Send">
          <ArrowUp className="size-4" />
        </button>
      </form>
    </div>
  );
}
