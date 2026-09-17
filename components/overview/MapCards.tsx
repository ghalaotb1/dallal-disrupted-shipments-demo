"use client";

import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Siren, X } from "lucide-react";
import { places } from "@/data/network";
import { fmtKm, fmtSar } from "@/lib/format";
import { fmtTime, fmtWindow } from "@/lib/time";
import { useDemoNow } from "@/hooks/useDemoNow";
import { estimateEta, progressOf, remainingM } from "@/services/logic/movement";
import { useUi } from "@/store/ui";
import { useWorld } from "@/store/world";
import { AgentBadge, PriorityBadge, RiskMeter, StatusBadge } from "@/components/common/Badges";
import { HEALTH } from "@/components/common/status";
import { RouteProgress } from "@/components/shipments/RouteProgress";

export function MapSelectionCards() {
  const selectedId = useUi((s) => s.selectedShipmentId);
  const facilityId = useUi((s) => s.selectedFacilityId);
  return (
    <div className="pointer-events-none absolute top-3 right-3 z-20 w-[320px]">
      <AnimatePresence mode="wait">
        {selectedId ? (
          <motion.div key={`s-${selectedId}`} initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.2 }} className="pointer-events-auto">
            <ShipmentCard id={selectedId} />
          </motion.div>
        ) : facilityId ? (
          <motion.div key={`f-${facilityId}`} initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.2 }} className="pointer-events-auto">
            <FacilityCard id={facilityId} />
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

function ShipmentCard({ id }: { id: string }) {
  const s = useWorld((w) => w.shipments[id]);
  const set = useUi((x) => x.set);
  const now = useDemoNow(1000);
  if (!s) return null;
  const eta = estimateEta(s, now);
  const pay = s.payment.type === "COD" ? `COD ${fmtSar(s.payment.amountSar)}` : "Prepaid";
  return (
    <div className="rounded-xl border border-line bg-surface shadow-pop">
      <div className="flex items-start justify-between gap-2 px-4 pt-3.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-15 font-semibold">{s.id}</span>
            <PriorityBadge priority={s.priority} />
          </div>
          <div className="mt-0.5 truncate text-xs text-ink-3">
            {s.merchant} · {s.service} · {pay}
          </div>
        </div>
        <button onClick={() => set({ selectedShipmentId: null })} className="-mt-1 -mr-1.5 rounded-md p-1 text-ink-4 hover:bg-hover hover:text-ink-2" aria-label="Close shipment card">
          <X className="size-4" />
        </button>
      </div>
      <div className="px-4 pt-2">
        <StatusBadge health={s.health} />
        {s.headline ? <p className={`mt-2 text-13 leading-5 font-medium ${HEALTH[s.health].text}`}>{s.headline}</p> : null}
      </div>
      <div className="mx-4 mt-3 rounded-lg bg-subtle p-3">
        <div className="flex items-center justify-between gap-3 text-xs text-ink-3">
          <span className="shrink-0">{places[s.originId].short}</span>
          <span className="truncate text-right font-medium text-ink-2">{s.destination.label}</span>
        </div>
        <RouteProgress s={s} now={now} className="mt-2" />
        <div className="mt-2 flex items-center justify-between text-xs">
          <span className="text-ink-3 tabular">
            {s.movement.mode === "facility" ? "Not departed" : `${Math.round(progressOf(s, now) * 100)}% · ${fmtKm(remainingM(s, now))} left`}
          </span>
          <span className="text-ink-3">
            ETA <span className={`font-semibold tabular ${eta && eta > s.slaDeadline ? "text-crit-600" : "text-ink"}`}>{eta ? fmtTime(eta) : "—"}</span>
          </span>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2 px-4 pt-3 text-xs">
        <div>
          <dt className="text-ink-4">Window</dt>
          <dd className="font-medium text-ink-2 tabular">{fmtWindow(s.window)}</dd>
        </div>
        <div>
          <dt className="text-ink-4">Risk</dt>
          <dd>
            <RiskMeter risk={s.risk} />
          </dd>
        </div>
        <div className="col-span-2">
          <dt className="text-ink-4">Agent</dt>
          <dd className="mt-0.5 flex items-center justify-between gap-2">
            <AgentBadge state={s.agent.state} />
          </dd>
          {s.agent.headline && s.agent.state !== "monitoring" ? <dd className="mt-0.5 line-clamp-2 text-ink-3">{s.agent.headline}</dd> : null}
        </div>
      </dl>
      <div className="flex gap-2 p-4 pt-3">
        <Link href={`/shipments/${s.id}`} className="inline-flex h-9 flex-1 items-center justify-center gap-1.5 rounded-lg bg-brand-600 text-13 font-medium text-white hover:bg-brand-700">
          Open Shipment Intelligence <ArrowRight className="size-4" />
        </Link>
      </div>
      {s.incident ? (
        <Link href={`/incidents/${s.incident.id}`} className="flex items-center gap-2 border-t border-line-soft px-4 py-2.5 text-xs text-crit-700 hover:bg-crit-50">
          <Siren className="size-3.5" /> Part of {s.incident.id} ({s.incident.role}) <ArrowRight className="ml-auto size-3.5" />
        </Link>
      ) : null}
    </div>
  );
}

function FacilityCard({ id }: { id: string }) {
  const place = places[id];
  const set = useUi((x) => x.set);
  const held = useWorld((w) => Object.values(w.shipments).filter((s) => !s.closed && s.movement.mode === "facility" && s.movement.facilityId === id));
  const incident = useWorld((w) => Object.values(w.incidents).find((i) => i.sharedFactor.placeId === id && i.status !== "resolved"));
  return (
    <div className="rounded-xl border border-line bg-surface shadow-pop">
      <div className="flex items-start justify-between px-4 pt-3.5">
        <div>
          <div className="text-15 font-semibold">{place.name}</div>
          <div className="text-xs text-ink-3">
            {place.district}, {place.city} · <span className="capitalize">{place.kind}</span> <span className="text-ink-4">(demo node)</span>
          </div>
        </div>
        <button onClick={() => set({ selectedFacilityId: null })} className="-mt-1 -mr-1.5 rounded-md p-1 text-ink-4 hover:bg-hover" aria-label="Close facility card">
          <X className="size-4" />
        </button>
      </div>
      {incident ? (
        <Link href={`/incidents/${incident.id}`} className="mx-4 mt-3 flex items-center gap-2 rounded-lg bg-warn-50 px-3 py-2 text-xs font-medium text-warn-700 hover:bg-warn-100">
          <Siren className="size-3.5" /> {incident.id} · {incident.title} · {incident.status}
        </Link>
      ) : null}
      <div className="px-4 pt-3 pb-1 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">{held.length ? `${held.length} shipments here` : "No shipments held"}</div>
      <ul className="max-h-60 overflow-auto px-2 pb-3 scrollbar-thin">
        {held.map((s) => (
          <li key={s.id}>
            <Link href={`/shipments/${s.id}`} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-hover">
              <span className="font-mono text-xs font-semibold">{s.id}</span>
              <StatusBadge health={s.health} size="xs" />
              <span className="ml-auto truncate text-2xs text-ink-3">{s.destination.district}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
