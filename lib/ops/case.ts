import { places } from "@/data/network";
import { COURIER_ID } from "@/data/ops/world";
import { remainingMin, vanPosition } from "@/lib/ops/derive";
import type { PlanSnapshot, LiveCase } from "@/types/live";
import type { OpsWorld } from "@/types/ops";

/**
 * Snapshot of the simulated world in the shape the backend adapter expects (backend/dallal/api/frontend_case.py).
 * The browser owns the SIMULATED physical world; the backend reasons over what this snapshot says and nothing else.
 */
export function buildCase(w: OpsWorld, parcelId: string, now: number, trigger: LiveCase["trigger"]): LiveCase {
  const p = w.parcels[parcelId];
  const d = w.drivers[p.driverId];
  const ctx = w.contexts[parcelId];
  const origin = places[p.originId];
  const [lng, lat] = vanPosition(d, now);
  return {
    now,
    trigger,
    shipment: {
      id: p.id,
      service: p.service,
      payment: p.payment,
      valueSar: p.valueSar,
      merchant: p.merchant,
      recipientName: p.recipient.name,
      destLat: p.dest[1],
      destLng: p.dest[0],
      originId: p.originId,
      originName: origin?.name ?? p.originId,
      originLat: origin?.coord[1] ?? 26.4,
      originLng: origin?.coord[0] ?? 50.1,
      corridorId: d.corridorId,
      courier: { id: COURIER_ID[d.id] ?? d.id, vehicle: d.vehicle },
      createdAt: w.journeys[parcelId][0]?.at ?? now,
      window: p.window,
      exception: p.exception,
      altRoute: false,
    },
    journey: w.journeys[parcelId].map((e) => ({ at: e.at, title: e.title, detail: e.detail, source: e.source, tone: e.tone, code: e.code })),
    context: ctx,
    vehicle: { lat, lng },
    corridorBaseline: { mean: 0.4, std: 0.6 },
    peers: Object.values(w.parcels)
      .filter((q) => q.id !== p.id && w.drivers[q.driverId].corridorId === d.corridorId)
      .map((q) => ({ id: q.id, corridorId: w.drivers[q.driverId].corridorId, originId: q.originId, exceptionAt: q.exception?.recordedAt, code: q.exception?.code })),
  };
}

/**
 * Incident -> coordinated-recovery problem: every parcel already delayed or exposed, grouped by the van that carries it.
 * RESOURCES (spare couriers, pickup capacity, whether an alternative road is usable) and the prior on blockage duration are
 * ASSUMPTIONS of this demonstration: the simulated operation has no dispatch-capacity feed. The screens label them SIM.
 */
export function buildPlanSnapshot(w: OpsWorld, now: number, incidentId: string): PlanSnapshot {
  const a = w.active;
  if (!a) throw new Error("no active scenario");
  const ids = [...a.affectedDriverIds.flatMap((d) => Object.values(w.parcels).filter((p) => p.driverId === d && p.exception && p.state === "at_risk").map((p) => p.id)), ...a.exposedParcelIds];
  const parcels = ids.map((id) => {
    const p = w.parcels[id];
    const d = w.drivers[p.driverId];
    return {
      id,
      van: d.vehicle,
      value: p.valueSar,
      slackMin: Math.max(5, (p.window.end - now) / 60_000),
      remainingMin: remainingMin(p, d, now),
      service: p.service,
      exposed: a.exposedParcelIds.includes(id),
      pickupOk: p.service !== "Same-day",
      reachable: w.contexts[id]?.recipient.responsiveness !== "low",
    };
  });
  const pickups = Object.values(places)
    .filter((q) => q.kind === "pickup" || q.kind === "locker")
    .slice(0, 2)
    .map((q, i) => ({ id: q.id, travelMin: 20 + 6 * i, capacity: 3, online: true }));
  return {
    incidentId,
    scope: "corridor",
    scopeId: "DK-04",
    now,
    belief: { pLong: 0.3 },
    dispatcherContactable: true,
    parcels,
    resources: { spares: [{ id: "S1", etaMin: 20, capacity: 3 }, { id: "S2", etaMin: 28, capacity: 2 }], pickups, alt: { available: false, extraMin: 55 } },
  };
}
