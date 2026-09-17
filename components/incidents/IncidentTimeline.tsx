"use client";

import { History } from "lucide-react";
import { cn } from "@/lib/cn";
import { fmtTime } from "@/lib/time";
import type { Incident } from "@/types/domain";

const DOT = { neutral: "bg-ink-4", info: "bg-brand-500", ok: "bg-ok-500", warn: "bg-warn-500", crit: "bg-crit-500", review: "bg-review-500", agent: "bg-brand-600" };

export function IncidentTimeline({ incident }: { incident: Incident }) {
  const events = [...incident.timeline].sort((a, b) => b.at - a.at);
  return (
    <section className="rounded-xl border border-line bg-surface shadow-card" aria-labelledby="inc-timeline-title">
      <header className="px-5 pt-4 pb-2">
        <div className="flex items-center gap-2 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">
          <History className="size-3.5" aria-hidden /> Incident timeline
        </div>
        <h2 id="inc-timeline-title" className="sr-only">
          Incident timeline
        </h2>
      </header>
      <ol className="px-5 pb-4">
        {events.map((e, i) => (
          <li key={e.id} className="relative flex gap-3 pb-3 last:pb-0">
            {i < events.length - 1 ? <span className="absolute top-4 bottom-0 left-[47px] w-px bg-line" aria-hidden /> : null}
            <span className="w-9 shrink-0 pt-px text-right text-xs text-ink-3 tabular">{fmtTime(e.at)}</span>
            <span className={cn("relative z-[1] mt-1.5 size-2.5 shrink-0 rounded-full ring-4 ring-surface", DOT[e.tone])} aria-hidden />
            <div className="min-w-0">
              <div className="text-13 font-medium text-ink">{e.title}</div>
              <div className="text-xs text-ink-3">
                {e.detail ? `${e.detail} · ` : ""}
                {e.actor}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
