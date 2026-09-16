"use client";

import Link from "next/link";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { BadgeCheck, OctagonAlert, Info, TriangleAlert, UserRoundCheck, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { dismissToast, useUi, type Toast } from "@/store/ui";

const ICON = { info: Info, ok: BadgeCheck, warn: TriangleAlert, crit: OctagonAlert, review: UserRoundCheck };
const ACCENT = { info: "text-brand-600 bg-brand-50", ok: "text-ok-600 bg-ok-50", warn: "text-warn-600 bg-warn-50", crit: "text-crit-600 bg-crit-50", review: "text-review-600 bg-review-50" };
const BAR = { info: "bg-brand-500", ok: "bg-ok-500", warn: "bg-warn-500", crit: "bg-crit-500", review: "bg-review-500" };

export function Toaster() {
  const toasts = useUi((s) => s.toasts);
  const assistantOpen = useUi((s) => s.assistantOpen);
  const reduce = useReducedMotion();
  return (
    <>
      <div className="sr-only" role="status" aria-live="polite">
        {toasts.map((t) => `${t.title}. ${t.body ?? ""}`).join(" ")}
      </div>
      <div className={cn("pointer-events-none fixed bottom-4 z-[60] flex w-[360px] flex-col gap-2 transition-[right] duration-300", assistantOpen ? "right-[476px]" : "right-4")}>
        <AnimatePresence initial={false}>
          {toasts.map((t) => (
            <motion.div
              key={t.id}
              layout={!reduce}
              initial={reduce ? { opacity: 0 } : { opacity: 0, y: 16, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={reduce ? { opacity: 0 } : { opacity: 0, x: 24, transition: { duration: 0.18 } }}
              transition={{ type: "spring", stiffness: 420, damping: 34 }}
              className="pointer-events-auto"
            >
              <ToastCard t={t} />
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </>
  );
}

function ToastCard({ t }: { t: Toast }) {
  const Icon = ICON[t.tone];
  return (
    <div className="relative flex gap-3 overflow-hidden rounded-xl border border-line bg-surface py-3 pr-9 pl-3.5 shadow-pop">
      <span className={cn("absolute inset-y-0 left-0 w-[3px]", BAR[t.tone])} aria-hidden />
      <span className={cn("mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full", ACCENT[t.tone])}>
        <Icon className="size-4" aria-hidden />
      </span>
      <div className="min-w-0">
        <div className="text-13 font-semibold text-ink">{t.title}</div>
        {t.body ? <div className="mt-0.5 text-xs text-ink-3">{t.body}</div> : null}
        {t.href ? (
          <Link href={t.href} onClick={() => dismissToast(t.id)} className="mt-1.5 inline-block text-xs font-semibold text-brand-700 hover:underline">
            {t.actionLabel ?? "Open"} →
          </Link>
        ) : null}
      </div>
      <button onClick={() => dismissToast(t.id)} className="absolute top-2 right-2 rounded-md p-1 text-ink-4 hover:bg-hover hover:text-ink-2" aria-label="Dismiss">
        <X className="size-3.5" />
      </button>
    </div>
  );
}
