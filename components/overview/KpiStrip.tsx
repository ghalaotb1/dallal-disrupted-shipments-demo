"use client";

import { AnimatePresence, motion } from "motion/react";
import { Activity, OctagonAlert, Siren, TriangleAlert, UserRoundSearch, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { useKpis } from "@/hooks/useWorldData";
import { useUi, type StatusFilter } from "@/store/ui";
import { SimTag } from "@/components/common/Badges";

export function KpiStrip() {
  const k = useKpis();
  const filter = useUi((s) => s.statusFilter);
  const set = useUi((s) => s.set);
  const items: { key: StatusFilter; label: string; value: number; sub: string; icon: LucideIcon; tone: string }[] = [
    { key: "all", label: "Active shipments", value: k.active, sub: `${k.moving} moving now`, icon: Activity, tone: "text-brand-600" },
    { key: "at_risk", label: "At risk", value: k.atRisk, sub: "predicted before failure", icon: TriangleAlert, tone: "text-warn-600" },
    { key: "disrupted", label: "Disrupted", value: k.disrupted, sub: "failed or stalled", icon: OctagonAlert, tone: "text-crit-600" },
    { key: "review", label: "Human review", value: k.review, sub: "awaiting a person", icon: UserRoundSearch, tone: "text-review-600" },
    { key: "incidents", label: "Open incidents", value: k.incidents, sub: k.criticalIncident ? k.criticalIncident.id : "shared causes", icon: Siren, tone: "text-crit-600" },
  ];
  return (
    <div className="flex items-stretch overflow-hidden rounded-xl border border-line bg-surface shadow-card">
      <div className="hidden min-w-[208px] flex-col justify-center border-r border-line-soft px-4 py-2.5 xl:flex">
        <h1 className="text-[17px] font-semibold tracking-[-0.01em] text-ink">Operations overview</h1>
        <p className="mt-0.5 flex items-center gap-1.5 text-xs text-ink-3">
          Dammam · Al Khobar · Dhahran <SimTag />
        </p>
      </div>
      <div className="grid flex-1 grid-cols-5" role="group" aria-label="Filter queue and map by status">
        {items.map((it) => {
          const active = filter === it.key;
          const Icon = it.icon;
          const alert = it.key === "incidents" && !!k.criticalIncident;
          return (
            <button
              key={it.key}
              onClick={() => set({ statusFilter: active && it.key !== "all" ? "all" : it.key, selectedShipmentId: null })}
              aria-pressed={active}
              className={cn(
                "group relative flex min-w-0 flex-col items-start justify-center border-r border-line-soft px-4 py-2.5 text-left transition-colors last:border-r-0",
                active ? "bg-brand-25" : "hover:bg-hover",
              )}
            >
              <span className="flex items-center gap-1.5 text-xs font-medium text-ink-3">
                <Icon className={cn("size-3.5", it.tone)} aria-hidden />
                <span className="truncate">{it.label}</span>
              </span>
              <span className="mt-0.5 flex items-baseline gap-2">
                <AnimatePresence mode="popLayout" initial={false}>
                  <motion.span
                    key={it.value}
                    initial={{ y: -10, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    exit={{ y: 10, opacity: 0 }}
                    transition={{ type: "spring", stiffness: 500, damping: 32 }}
                    className={cn("text-[22px] leading-7 font-semibold tracking-[-0.02em] tabular", alert ? "text-crit-600" : "text-ink")}
                  >
                    {it.value}
                  </motion.span>
                </AnimatePresence>
                <span className="truncate text-2xs text-ink-4">{it.sub}</span>
              </span>
              {active ? <motion.span layoutId="kpi-active" className="absolute inset-x-3 bottom-0 h-[2.5px] rounded-t bg-brand-600" /> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}
