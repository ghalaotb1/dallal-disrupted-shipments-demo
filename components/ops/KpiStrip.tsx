"use client";

import { useMemo } from "react";
import { Activity, BadgeCheck, FolderOpen, OctagonAlert, TriangleAlert, UserRoundSearch, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { useOpsNow } from "@/hooks/useOpsNow";
import { parcelHealth, isDone } from "@/lib/ops/derive";
import { setUi, useOps, useOpsUi, type UiState } from "@/store/ops";

type Key = UiState["kpiFilter"];

export function KpiStrip() {
  const drivers = useOps((s) => s.drivers);
  const parcels = useOps((s) => s.parcels);
  const cases = useOps((s) => s.cases);
  const filter = useOpsUi((s) => s.kpiFilter);
  const now = useOpsNow(1000);
  const k = useMemo(() => {
    let active = 0, atRisk = 0, disrupted = 0, review = 0, resolved = 0;
    for (const p of Object.values(parcels)) {
      const h = parcelHealth(p, drivers[p.driverId], now);
      if (!isDone(h)) active += 1;
      if (h === "at_risk") atRisk += 1;
      else if (h === "disrupted") disrupted += 1;
      else if (h === "review") review += 1;
      else if (h === "prevented" || h === "recovered") resolved += 1;
    }
    const open = cases.filter((c) => ["attempt_failed", "at_risk", "awaiting_manager"].includes(parcels[c.parcelId].state)).length;
    return { active, atRisk, disrupted, review, resolved, open };
  }, [drivers, parcels, cases, now]);
  const items: { key: Key; label: string; value: number; sub: string; icon: LucideIcon; tone: string }[] = [
    { key: "all", label: "Active parcels", value: k.active, sub: `${Object.keys(drivers).length} drivers`, icon: Activity, tone: "text-brand-600" },
    { key: "at_risk", label: "At risk", value: k.atRisk, sub: "may miss window", icon: TriangleAlert, tone: "text-warn-600" },
    { key: "disrupted", label: "Disrupted", value: k.disrupted, sub: "delivery failed", icon: OctagonAlert, tone: "text-crit-600" },
    { key: "review", label: "With manager", value: k.review, sub: "awaiting approval", icon: UserRoundSearch, tone: "text-review-600" },
    { key: "cases", label: "Open cases", value: k.open, sub: "Dallal on it", icon: FolderOpen, tone: "text-ink-3" },
    { key: "resolved", label: "Resolved by Dallal", value: k.resolved, sub: "no manager needed", icon: BadgeCheck, tone: "text-ok-600" },
  ];
  return (
    <div className="grid shrink-0 grid-cols-6 border-b border-line bg-surface" role="group" aria-label="Filter routes by status">
      {items.map((it) => {
        const on = filter === it.key && it.key !== "all";
        const Icon = it.icon;
        return (
          <button
            key={it.key}
            type="button"
            aria-pressed={on}
            onClick={() => setUi({ kpiFilter: on || it.key === "all" ? "all" : it.key })}
            className={cn("relative flex min-w-0 flex-col items-start border-r border-line-soft px-4 py-2 text-left transition-colors last:border-r-0", on ? "bg-brand-25" : "hover:bg-hover")}
          >
            <span className="flex items-center gap-1.5 text-xs font-medium text-ink-3">
              <Icon className={cn("size-3.5", it.tone)} aria-hidden />
              <span className="truncate">{it.label}</span>
            </span>
            <span className="mt-0.5 flex items-baseline gap-2">
              <span className="text-[22px] leading-7 font-semibold tracking-[-0.02em] text-ink tabular">{it.value}</span>
              <span className="truncate text-2xs text-ink-4">{it.sub}</span>
            </span>
            {on ? <span className="absolute inset-x-3 bottom-0 h-[2.5px] rounded-t bg-brand-600" /> : null}
          </button>
        );
      })}
    </div>
  );
}
