"use client";

import { useMemo } from "react";
import { ChevronDown, Truck } from "lucide-react";
import { cn } from "@/lib/cn";
import { fmtTime } from "@/lib/time";
import { useOpsNow } from "@/hooks/useOpsNow";
import { isDone, parcelHealth, summarize, type DriverSummary } from "@/lib/ops/derive";
import { getUi, setUi, useOps, useOpsUi } from "@/store/ops";
import { HEALTH } from "@/components/common/status";
import { Dot, HealthChip } from "@/components/ops/Chips";
import type { ShipmentHealth } from "@/types/domain";
import type { Parcel } from "@/types/ops";

const SEGMENT: Record<ShipmentHealth, string> = {
  delivered: "bg-ink-5",
  on_track: "bg-line-strong",
  at_risk: "bg-warn-500",
  disrupted: "bg-crit-500",
  review: "bg-review-500",
  recovering: "bg-brand-500",
  recovered: "bg-ok-500",
  prevented: "bg-ok-500",
};
const RANK: Record<ShipmentHealth, number> = { disrupted: 6, review: 5, at_risk: 4, recovering: 3, on_track: 2, recovered: 1, prevented: 1, delivered: 0 };

export function RoutesPanel() {
  const drivers = useOps((s) => s.drivers);
  const parcels = useOps((s) => s.parcels);
  const now = useOpsNow(700);
  const selectedDriver = useOpsUi((s) => s.selectedDriverId);
  const expanded = useOpsUi((s) => s.expandedDriverIds);
  const rows = useMemo(() => {
    const order = Object.keys(drivers);
    return summarize({ drivers, parcels }, now).sort((a, b) => RANK[b.worst] - RANK[a.worst] || order.indexOf(a.driver.id) - order.indexOf(b.driver.id));
  }, [drivers, parcels, now]);
  const attention = rows.reduce((n, r) => n + r.disrupted + r.atRisk + r.review, 0);
  const total = rows.reduce((n, r) => n + r.total, 0);

  return (
    <section aria-label="Drivers and routes" className="flex min-h-0 flex-col border-r border-line bg-surface">
      <header className="flex items-center gap-2 border-b border-line px-4 py-3">
        <Truck className="size-4 text-ink-3" aria-hidden />
        <h2 className="text-sm font-semibold text-ink">Drivers &amp; routes</h2>
        <span className="ml-auto text-xs text-ink-3">
          {rows.length} drivers · {total} parcels
          {attention ? <b className="ml-1 text-warn-700">· {attention} need attention</b> : null}
        </span>
      </header>
      <ul className="scrollbar-thin min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {rows.map((r) => (
          <DriverCard key={r.driver.id} r={r} now={now} selected={selectedDriver === r.driver.id} open={expanded.includes(r.driver.id)} />
        ))}
      </ul>
    </section>
  );
}

function DriverCard({ r, now, selected, open }: { r: DriverSummary; now: number; selected: boolean; open: boolean }) {
  const d = r.driver;
  const accent = HEALTH[r.worst === "delivered" ? "on_track" : r.worst];
  const issues = r.disrupted + r.atRisk + r.review;
  const toggle = () => {
    const ex = getUi().expandedDriverIds;
    setUi({ selectedDriverId: d.id, expandedDriverIds: ex.includes(d.id) && selected ? ex.filter((x) => x !== d.id) : ex.includes(d.id) ? ex : [...ex, d.id] });
  };
  return (
    <li className={cn("overflow-hidden rounded-xl border bg-surface shadow-card transition-colors", selected ? "border-brand-300 ring-2 ring-brand-100" : "border-line")}>
      <button type="button" onClick={toggle} aria-expanded={open} className="relative block w-full px-3.5 py-3 text-left">
        <span className={cn("absolute inset-y-0 left-0 w-1", r.worst === "on_track" || r.worst === "delivered" ? "bg-line" : accent.dot)} aria-hidden />
        <div className="flex items-center gap-2.5">
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-ink text-xs font-semibold text-white">{d.name[0]}</span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="text-13 font-semibold text-ink">{d.name}</span>
              <span className="font-mono text-2xs text-ink-4">{d.vehicle}</span>
            </div>
            <div className="truncate text-xs text-ink-3">{d.note ?? (r.held ? "Held up" : `${r.done} of ${r.total} done`)}</div>
          </div>
          {issues > 0 ? <HealthChip health={r.worst === "review" ? "review" : r.worst === "disrupted" ? "disrupted" : "at_risk"} label={`${issues} ${r.worst === "review" ? "for manager" : r.worst === "disrupted" ? "failed" : "at risk"}`} /> : r.recovering > 0 ? <HealthChip health="recovering" label={`${r.recovering} recovering`} /> : null}
          <ChevronDown className={cn("size-4 shrink-0 text-ink-4 transition-transform", open && "rotate-180")} aria-hidden />
        </div>
        <div className="mt-2.5 flex items-center gap-0.5" role="img" aria-label={`${r.done} of ${r.total} parcels done`}>
          {r.parcels.map((p) => (
            <span key={p.id} className={cn("h-1.5 flex-1 rounded-full", SEGMENT[parcelHealth(p, d, now)])} />
          ))}
        </div>
        <div className="mt-1.5 flex items-center justify-between text-xs text-ink-3">
          <span>
            <b className="font-semibold text-ink tabular">{r.done}</b> of {r.total} done
          </span>
          {r.nextStop ? (
            <span className="truncate">
              Next: {r.nextStop.address.district}
              {r.nextEta ? <> · {fmtTime(r.nextEta)}</> : r.held ? <> · delayed</> : null}
            </span>
          ) : r.moved > 0 ? (
            <span className="text-brand-700">{r.moved} moved to spare / pickup</span>
          ) : (
            <span>Route complete</span>
          )}
        </div>
      </button>
      {open ? (
        <ul className="border-t border-line-soft bg-subtle px-2 py-1.5">
          {r.parcels.map((p) => (
            <ParcelRow key={p.id} p={p} now={now} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function ParcelRow({ p, now }: { p: Parcel; now: number }) {
  const driver = useOps((s) => s.drivers[p.driverId]);
  const selected = useOpsUi((s) => s.selectedParcelId === p.id);
  const h = parcelHealth(p, driver, now);
  const done = isDone(h);
  return (
    <li>
      <button
        type="button"
        onClick={() => setUi({ selectedParcelId: p.id, selectedDriverId: p.driverId })}
        className={cn("flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left transition-colors hover:bg-hover", selected && "bg-brand-50 ring-1 ring-brand-200")}
      >
        <span className="flex w-4 justify-center font-mono text-2xs text-ink-4 tabular">{p.seq}</span>
        <Dot health={h} />
        <span className="min-w-0 flex-1">
          <span className={cn("block truncate text-xs", done ? "text-ink-4" : "font-medium text-ink")}>
            {p.address.district} <span className="font-normal text-ink-4">· {p.id}</span>
          </span>
          {p.recovery && p.recovery.kind !== "wait" ? <span className="block truncate text-2xs text-brand-700">→ {p.recovery.label}</span> : null}
        </span>
        {h !== "on_track" && h !== "delivered" ? <span className={cn("shrink-0 text-2xs font-medium", HEALTH[h].text)}>{HEALTH[h].label}</span> : <span className="shrink-0 text-2xs text-ink-4">{h === "delivered" ? "Delivered" : ""}</span>}
      </button>
    </li>
  );
}
