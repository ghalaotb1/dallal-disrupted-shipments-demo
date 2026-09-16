"use client";

import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import { compareByPriority } from "@/services/logic/priority";
import { useWorld } from "@/store/world";
import type { Shipment } from "@/types/domain";

export const useShipment = (id: string | null | undefined) => useWorld((w) => (id ? w.shipments[id] : undefined));
export const useIncident = (id: string | null | undefined) => useWorld((w) => (id ? w.incidents[id] : undefined));
export const useJourney = (id: string) => useWorld((w) => w.journeys[id]);
export const useContext = (id: string) => useWorld((w) => w.contexts[id]);

export function useActiveShipments(): Shipment[] {
  const map = useWorld((w) => w.shipments);
  return useMemo(() => Object.values(map).filter((s) => !s.closed).sort(compareByPriority), [map]);
}

export function useAllShipments(): Shipment[] {
  const map = useWorld((w) => w.shipments);
  return useMemo(() => Object.values(map), [map]);
}

export function useIncidents() {
  const map = useWorld((w) => w.incidents);
  return useMemo(() => Object.values(map).sort((a, b) => Number(a.status === "resolved") - Number(b.status === "resolved") || b.detectedAt - a.detectedAt), [map]);
}

export function useLatestRun(shipmentId: string, mode?: "investigation" | "execution") {
  return useWorld(
    useShallow((w) => {
      const runs = Object.values(w.agentRuns)
        .filter((r) => r.shipmentId === shipmentId && (!mode || r.mode === mode))
        .sort((a, b) => b.startedAt - a.startedAt);
      return runs[0];
    }),
  );
}

export function useKpis() {
  const shipments = useWorld((w) => w.shipments);
  const incidents = useWorld((w) => w.incidents);
  return useMemo(() => {
    const active = Object.values(shipments).filter((s) => !s.closed);
    return {
      active: active.length,
      moving: active.filter((s) => s.movement.mode === "route" && s.movement.holdAtM === undefined).length,
      atRisk: active.filter((s) => s.health === "at_risk").length,
      disrupted: active.filter((s) => s.health === "disrupted").length,
      review: active.filter((s) => s.health === "review" || s.agent.state === "awaiting_supervisor").length,
      incidents: Object.values(incidents).filter((i) => i.status !== "resolved").length,
      criticalIncident: Object.values(incidents).find((i) => i.status === "active" && (i.severity === "high" || i.severity === "critical")),
    };
  }, [shipments, incidents]);
}
