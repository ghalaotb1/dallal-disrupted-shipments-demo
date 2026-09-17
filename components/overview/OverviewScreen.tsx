"use client";

import { useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useActiveShipments } from "@/hooks/useWorldData";
import { useUi } from "@/store/ui";
import { LazyNetworkMap } from "@/components/map/LazyMap";
import { KpiStrip } from "@/components/overview/KpiStrip";
import { IncidentBanner } from "@/components/overview/IncidentBanner";
import { PriorityQueue } from "@/components/overview/PriorityQueue";
import { MapSelectionCards } from "@/components/overview/MapCards";
import { SimTag } from "@/components/common/Badges";

export function OverviewScreen() {
  const router = useRouter();
  const filter = useUi((s) => s.statusFilter);
  const selectedId = useUi((s) => s.selectedShipmentId);
  const selectedFacilityId = useUi((s) => s.selectedFacilityId);
  const focus = useUi((s) => s.mapFocus);
  const set = useUi((s) => s.set);
  const active = useActiveShipments();

  const highlightIds = useMemo(() => {
    if (filter === "all") return null;
    if (filter === "incidents") return active.filter((s) => s.incident).map((s) => s.id);
    if (filter === "review") return active.filter((s) => s.health === "review" || s.agent.state === "awaiting_supervisor").map((s) => s.id);
    return active.filter((s) => s.health === filter).map((s) => s.id);
  }, [filter, active]);

  const onSelectShipment = useCallback((id: string | null) => set({ selectedShipmentId: id, selectedFacilityId: null }), [set]);
  const onSelectFacility = useCallback((id: string | null) => set({ selectedFacilityId: id, selectedShipmentId: null }), [set]);
  const moving = active.filter((s) => s.movement.mode === "route" && s.movement.holdAtM === undefined).length;

  return (
    <div className="flex h-[calc(100dvh-56px)] min-h-[640px] flex-col gap-3 p-3 lg:p-4">
      <KpiStrip />
      <IncidentBanner />
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(300px,368px)_1fr] gap-3">
        <PriorityQueue />
        <section className="relative min-h-0 overflow-hidden rounded-xl border border-line shadow-card" aria-label="Live network map">
          <LazyNetworkMap
            variant="overview"
            className="size-full"
            selectedId={selectedId}
            onSelectShipment={onSelectShipment}
            selectedFacilityId={selectedFacilityId}
            onSelectFacility={onSelectFacility}
            onSelectIncident={(id) => router.push(`/incidents/${id}`)}
            highlightIds={highlightIds}
            focus={focus}
            controlsOffset={!!selectedId || !!selectedFacilityId}
          >
            <div className="pointer-events-none absolute top-3 left-3 z-10 flex items-center gap-2 rounded-lg border border-line bg-surface/95 px-2.5 py-1.5 text-xs shadow-card backdrop-blur-sm">
              <span className="relative flex size-2" aria-hidden>
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-ok-500 opacity-50" />
                <span className="relative inline-flex size-2 rounded-full bg-ok-500" />
              </span>
              <span className="font-medium text-ink">Live network</span>
              <span className="text-ink-3">· {moving} parcels moving</span>
              <SimTag className="pointer-events-auto" />
            </div>
            <MapSelectionCards />
          </LazyNetworkMap>
        </section>
      </div>
    </div>
  );
}
