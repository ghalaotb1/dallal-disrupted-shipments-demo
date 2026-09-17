"use client";

import { useState } from "react";
import { Building2, Inbox, MapPin, OctagonAlert, Package, RefreshCw, ShieldCheck, Siren, Store, TriangleAlert, UserRoundSearch, Warehouse } from "lucide-react";
import { cn } from "@/lib/cn";
import { fmtKm } from "@/lib/format";
import { fmtTime } from "@/lib/time";
import { places } from "@/data/network";
import { useDemoNow } from "@/hooks/useDemoNow";
import { estimateEta, progressOf, remainingM } from "@/services/logic/movement";
import { useWorld } from "@/store/world";
import { HEALTH } from "@/components/common/status";
import { RiskMeter, StatusBadge } from "@/components/common/Badges";
import type { Incident, Shipment, ShipmentHealth } from "@/types/domain";

const BODY: Record<ShipmentHealth, string> = {
  on_track: "bg-white text-ok-600 ring-line-strong",
  at_risk: "bg-warn-50 text-warn-600 ring-warn-500",
  disrupted: "bg-crit-500 text-white ring-crit-600",
  review: "bg-review-500 text-white ring-review-600",
  recovering: "bg-brand-50 text-brand-600 ring-brand-500",
  recovered: "bg-white text-ok-600 ring-ok-500",
  prevented: "bg-ok-50 text-ok-600 ring-ok-500",
  delivered: "bg-white text-ink-4 ring-line",
};
const BADGE: Partial<Record<ShipmentHealth, { icon: typeof Package; cls: string }>> = {
  at_risk: { icon: TriangleAlert, cls: "bg-warn-500 text-white" },
  disrupted: { icon: OctagonAlert, cls: "bg-white text-crit-600" },
  review: { icon: UserRoundSearch, cls: "bg-white text-review-600" },
  recovering: { icon: RefreshCw, cls: "bg-brand-500 text-white" },
  prevented: { icon: ShieldCheck, cls: "bg-ok-500 text-white" },
};

export function ShipmentMarker({ id, selected, dimmed, onSelect }: { id: string; selected: boolean; dimmed: boolean; onSelect: (id: string) => void }) {
  const s = useWorld((w) => w.shipments[id]);
  const [hover, setHover] = useState(false);
  if (!s) return null;
  const normal = s.health === "on_track";
  const badge = BADGE[s.health];
  const exposed = s.incident?.role === "exposed";
  return (
    <div
      className={cn("relative transition-opacity duration-300", dimmed && !selected ? "opacity-35" : "opacity-100")}
      style={{ zIndex: selected ? 30 : hover ? 40 : normal ? 1 : 10 }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      {s.health === "disrupted" && !dimmed ? <span className="absolute inset-0 m-auto size-7 animate-pulse-ring rounded-full bg-crit-500/40" aria-hidden /> : null}
      <button
        type="button"
        tabIndex={-1}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(id);
        }}
        aria-label={`${s.id}, ${HEALTH[s.health].label}, to ${s.destination.label}`}
        className={cn(
          "relative flex items-center justify-center rounded-[8px] shadow-marker ring-[1.5px] transition-transform duration-200 ease-out hover:scale-110",
          normal ? "size-[calc(23px*var(--mk,1))]" : "size-[calc(28px*var(--mk,1))]",
          BODY[s.health],
          exposed && "outline-2 outline-offset-2 outline-warn-500 outline-dashed",
          selected && "scale-115 ring-[2.5px] ring-brand-600 outline-2 outline-offset-2 outline-brand-600/25",
        )}
      >
        <Package className={normal ? "size-[calc(13px*var(--mk,1))]" : "size-[calc(16px*var(--mk,1))]"} strokeWidth={2.2} aria-hidden />
        {badge ? (
          <span className={cn("absolute -top-1.5 -right-1.5 flex size-[15px] items-center justify-center rounded-full shadow ring-1 ring-black/5", badge.cls)} aria-hidden>
            <badge.icon className="size-2.5" strokeWidth={2.6} />
          </span>
        ) : null}
      </button>
      {selected ? (
        <span className="absolute top-full left-1/2 mt-1.5 -translate-x-1/2 rounded-md bg-ink px-1.5 py-0.5 font-mono text-[10.5px] font-semibold whitespace-nowrap text-white shadow">{s.id}</span>
      ) : null}
      {hover && !selected ? <HoverCard s={s} /> : null}
    </div>
  );
}

function HoverCard({ s }: { s: Shipment }) {
  const now = useDemoNow(2000);
  const eta = estimateEta(s, now);
  const progress = progressOf(s, now);
  return (
    <div className="pointer-events-none absolute bottom-full left-1/2 mb-2.5 w-60 -translate-x-1/2 rounded-xl border border-line bg-surface p-3 text-left shadow-pop">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-13 font-semibold text-ink">{s.id}</span>
        <StatusBadge health={s.health} size="xs" />
      </div>
      <div className="mt-1 truncate text-xs text-ink-3">
        {places[s.originId].short} → {s.destination.label}
      </div>
      {s.headline ? <div className="mt-1.5 line-clamp-2 text-xs text-ink-2">{s.headline}</div> : null}
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full" style={{ width: `${Math.round(progress * 100)}%`, background: HEALTH[s.health].map }} />
      </div>
      <div className="mt-2 flex items-center justify-between text-xs">
        <span className="text-ink-3">
          ETA <span className="font-medium text-ink tabular">{eta ? fmtTime(eta) : "—"}</span>
          <span className="text-ink-4"> · {fmtKm(remainingM(s, now))} left</span>
        </span>
        <RiskMeter risk={s.risk} showLabel={false} />
      </div>
    </div>
  );
}

const FACILITY_ICON = { hub: Warehouse, branch: Building2, pickup: Store, locker: Inbox };

export function FacilityMarker({ placeId, held, incident, selected, onSelect, showLabel }: { placeId: string; held: Shipment[]; incident?: Incident; selected: boolean; onSelect: (id: string) => void; showLabel: boolean }) {
  const place = places[placeId];
  const Icon = FACILITY_ICON[place.kind];
  const major = place.kind === "hub" || place.kind === "branch";
  const worst = held.find((s) => s.health === "review") ?? held.find((s) => s.health === "disrupted") ?? held.find((s) => s.health === "at_risk") ?? held[0];
  return (
    <div className="relative flex flex-col items-center" style={{ zIndex: selected ? 25 : 5 }}>
      {incident && incident.status !== "resolved" ? <span className="absolute top-[-6px] size-[42px] rounded-[13px] ring-2 ring-warn-500/70 ring-offset-2 ring-offset-transparent" aria-hidden /> : null}
      <button
        type="button"
        tabIndex={-1}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(placeId);
        }}
        aria-label={`${place.name}${held.length ? `, ${held.length} shipments held` : ""}`}
        className={cn(
          "relative flex items-center justify-center shadow-marker transition-transform hover:scale-105",
          major ? "size-[30px] rounded-[9px] bg-ink text-white" : "size-6 rounded-[7px] bg-white text-ink-2 ring-1 ring-line-strong",
          selected && "ring-[2.5px] ring-brand-600",
        )}
      >
        <Icon className={major ? "size-4" : "size-3.5"} aria-hidden />
        {held.length ? (
          <span className={cn("absolute -top-2 -right-2 flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1 text-[10.5px] font-bold tabular ring-2 ring-white", worst ? HEALTH[worst.health].dot : "bg-ink-4", worst?.health === "at_risk" ? "text-ink" : "text-white")}>
            {held.length}
          </span>
        ) : null}
      </button>
      {showLabel || selected ? (
        <span className="mt-1 rounded bg-white/85 px-1 text-[10.5px] font-semibold whitespace-nowrap text-ink-2 shadow-[0_0_0_1px_rgb(15_30_54/0.06)]">{place.short}</span>
      ) : null}
    </div>
  );
}

export function IncidentMarker({ incident, onSelect }: { incident: Incident; onSelect?: () => void }) {
  const critical = incident.severity === "critical" || incident.severity === "high";
  return (
    <button
      type="button"
      tabIndex={-1}
      onClick={(e) => {
        e.stopPropagation();
        onSelect?.();
      }}
      className="relative flex flex-col items-center"
      aria-label={`${incident.id} ${incident.title}`}
      style={{ zIndex: 20 }}
    >
      {incident.status === "active" ? <span className="absolute top-0 size-8 animate-pulse-ring rounded-full bg-crit-500/45" aria-hidden /> : null}
      <span className={cn("relative flex size-8 items-center justify-center rounded-full text-white shadow-marker ring-[3px] ring-white", critical ? "bg-crit-600" : "bg-warn-500")}>
        <Siren className="size-4" aria-hidden />
      </span>
      <span className="mt-1 rounded-md bg-crit-700 px-1.5 py-0.5 text-[10.5px] font-semibold whitespace-nowrap text-white shadow">
        {incident.id} · {incident.status === "mitigating" ? "Mitigating" : "Lane closure"}
      </span>
    </button>
  );
}

export function DestinationPin({ s }: { s: Shipment }) {
  const now = useDemoNow(5000);
  const eta = estimateEta(s, now);
  return (
    <div className="pointer-events-none flex flex-col items-center">
      <span className="rounded-lg border border-line bg-surface px-2 py-1 text-left shadow-float">
        <span className="block text-[10.5px] font-medium text-ink-3">Drop-off{eta ? ` · ETA ${fmtTime(eta)}` : ""}</span>
        <span className="block text-xs font-semibold whitespace-nowrap text-ink">{s.destination.label}</span>
      </span>
      <MapPin className="mt-0.5 size-6 fill-ink text-white" strokeWidth={1.8} aria-hidden />
    </div>
  );
}
