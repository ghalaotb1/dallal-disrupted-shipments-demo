import { people } from "@/data/people";
import { corridorBaselines } from "@/data/scenario/seedIncidents";
import { places } from "@/data/network";
import { shipmentPosition } from "@/services/logic/movement";
import { baselineStats } from "@/services/logic/incidentDetector";
import { demoNow, getWorld } from "@/store/world";
import type { LiveCase } from "@/types/live";

/** Snapshot of one shipment from the shared world store, in the shape the backend adapter expects (backend/dallal/api/frontend_case.py). */
export function buildCase(shipmentId: string, trigger: LiveCase["trigger"] = { kind: "analyst_request" }): LiveCase {
  const w = getWorld();
  const s = w.shipments[shipmentId];
  const ctx = w.contexts[shipmentId];
  if (!s || !ctx) throw new Error(`Unknown shipment ${shipmentId}`);
  const now = demoNow();
  const origin = places[s.originId];
  const [vLng, vLat] = shipmentPosition(s, now);
  const base = corridorBaselines[s.corridorId];
  const stats = base ? baselineStats(base) : undefined;
  return {
    now,
    trigger,
    shipment: {
      id: s.id,
      service: s.service,
      payment: s.payment,
      valueSar: s.valueSar,
      merchant: s.merchant,
      recipientName: s.recipient.name,
      destLat: s.destination.coord[1],
      destLng: s.destination.coord[0],
      originId: s.originId,
      originName: origin?.name ?? s.originId,
      originLat: origin?.coord[1] ?? 26.4,
      originLng: origin?.coord[0] ?? 50.1,
      corridorId: s.corridorId,
      courier: s.courier ? { id: s.courier.id, vehicle: s.courier.vehicle } : undefined,
      createdAt: s.createdAt,
      window: s.window,
      exception: s.exception ? { code: s.exception.code, label: s.exception.label, recordedAt: s.exception.recordedAt } : undefined,
      altRoute: !!s.altRouteKey,
    },
    journey: (w.journeys[shipmentId] ?? []).map((e) => ({ at: e.at, title: e.title, detail: e.detail, source: e.source, tone: e.tone, code: e.code })),
    context: ctx,
    vehicle: s.movement.mode === "route" ? { lat: vLat, lng: vLng, stationarySince: s.movement.stationarySince } : undefined,
    corridorBaseline: stats ? { mean: stats.mean, std: Math.max(stats.std, 0.35) } : undefined,
    peers: Object.values(w.shipments)
      .filter((p) => p.id !== s.id && p.corridorId === s.corridorId && !p.closed)
      .map((p) => ({ id: p.id, corridorId: p.corridorId, originId: p.originId, exceptionAt: p.exception?.recordedAt, code: p.exception?.code })),
  };
}

export const analystName = people.analyst.name;
