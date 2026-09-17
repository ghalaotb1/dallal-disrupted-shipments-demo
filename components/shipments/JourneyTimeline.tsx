"use client";

import { useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Bot, Building2, History, MapPin, MessageCircle, Radar, ScanLine, Settings2, ShieldCheck, Truck, UserRound, UserRoundCheck, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { fmtDate, fmtTime, sameDay } from "@/lib/time";
import type { EventSource, EventTone, JourneyEvent } from "@/types/domain";

const SOURCE: Record<EventSource, { icon: LucideIcon; label: string }> = {
  scan: { icon: ScanLine, label: "Scan" },
  gps: { icon: MapPin, label: "Courier GPS" },
  courier: { icon: Truck, label: "Courier" },
  recipient: { icon: MessageCircle, label: "Recipient" },
  system: { icon: Settings2, label: "System" },
  agent: { icon: Bot, label: "Dallal Agent" },
  analyst: { icon: UserRound, label: "Analyst" },
  supervisor: { icon: UserRoundCheck, label: "Supervisor" },
  model: { icon: Radar, label: "Risk monitor" },
};

const TONE: Record<EventTone, string> = {
  neutral: "bg-surface text-ink-3 ring-line-strong",
  info: "bg-brand-50 text-brand-600 ring-brand-200",
  ok: "bg-ok-50 text-ok-600 ring-ok-200",
  warn: "bg-warn-50 text-warn-600 ring-warn-200",
  crit: "bg-crit-50 text-crit-600 ring-crit-200",
  review: "bg-review-50 text-review-600 ring-review-200",
  agent: "bg-brand-600 text-white ring-brand-600",
};
const TITLE_TONE: Partial<Record<EventTone, string>> = { crit: "text-crit-700", warn: "text-warn-700", ok: "text-ok-700", review: "text-review-700" };

export function JourneyTimeline({ events, now }: { events: JourneyEvent[]; now: number }) {
  const reduce = useReducedMotion();
  const [showAll, setShowAll] = useState(false);
  const ordered = useMemo(() => [...events].sort((a, b) => b.at - a.at), [events]);
  const visible = useMemo(() => {
    const list = showAll ? ordered : ordered.slice(0, 9);
    return list.map((e, i) => {
      const day = sameDay(e.at, now) ? "Today" : fmtDate(e.at);
      const prev = list[i - 1];
      const prevDay = prev ? (sameDay(prev.at, now) ? "Today" : fmtDate(prev.at)) : "";
      return { e, day, showDay: day !== prevDay };
    });
  }, [ordered, showAll, now]);

  return (
    <section className="rounded-xl border border-line bg-surface shadow-card" aria-labelledby="journey-title">
      <header className="flex items-center justify-between px-5 pt-4 pb-2">
        <div>
          <div className="flex items-center gap-2 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">
            <History className="size-3.5" aria-hidden /> Journey
          </div>
          <h2 id="journey-title" className="mt-1 text-15 font-semibold text-ink">
            {events.length} events · newest first
          </h2>
        </div>
        <div className="hidden items-center gap-3 text-2xs text-ink-4 md:flex">
          <span className="flex items-center gap-1">
            <ShieldCheck className="size-3" /> Scans, GPS, contact logs, agent & human actions
          </span>
        </div>
      </header>
      <ol className="px-5 pb-4">
        <AnimatePresence initial={false}>
          {visible.map(({ e, day, showDay }, i) => {
            const src = SOURCE[e.source];
            const Icon = src.icon;
            return (
              <motion.li key={e.id} layout={reduce ? false : "position"} initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} transition={{ duration: 0.3 }}>
                {showDay ? <div className="mt-1 mb-1.5 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">{day}</div> : null}
                <div className="relative flex gap-3 pb-3">
                  {i < visible.length - 1 ? <span className="absolute top-7 bottom-0 left-[51px] w-px bg-line" aria-hidden /> : null}
                  <span className="w-9 shrink-0 pt-1 text-right text-xs text-ink-3 tabular">{fmtTime(e.at)}</span>
                  <span className={cn("relative z-[1] flex size-7 shrink-0 items-center justify-center rounded-full ring-1", TONE[e.tone])} title={src.label}>
                    <Icon className="size-3.5" aria-hidden />
                  </span>
                  <div className="min-w-0 flex-1 pt-0.5">
                    <div className={cn("text-13 leading-5 font-medium text-ink", TITLE_TONE[e.tone])}>
                      {e.title}
                      {e.code ? <span className="ml-1.5 rounded bg-muted px-1 font-mono text-2xs text-ink-2">{e.code}</span> : null}
                    </div>
                    <div className="text-xs text-ink-3">
                      {e.detail}
                      {e.detail && (e.location || src) ? <span className="text-ink-5"> · </span> : null}
                      <span className="text-ink-4">
                        {src.label}
                        {e.location ? ` · ${e.location}` : ""}
                      </span>
                    </div>
                  </div>
                </div>
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ol>
      {ordered.length > 9 ? (
        <button onClick={() => setShowAll((v) => !v)} className="w-full border-t border-line-soft py-2.5 text-xs font-medium text-brand-700 hover:bg-hover">
          {showAll ? "Show fewer" : `Show all ${ordered.length} events`}
        </button>
      ) : null}
    </section>
  );
}

export const BuildingIcon = Building2;
