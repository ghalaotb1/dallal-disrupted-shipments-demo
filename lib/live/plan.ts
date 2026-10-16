import { places } from "@/data/network";
import { remainingM } from "@/services/logic/movement";
import { demoNow, getWorld } from "@/store/world";
import type { PlanSnapshot } from "@/types/live";

/** Typical urban cruise speed used by the demo movement model (m/s) - same constant the frontend ETA uses. */
const CRUISE_MPS = 8.5;

/**
 * Incident -> coordinated-recovery problem. Parcels, values, promises and van sharing come from the shared world store.
 * RESOURCES (spare couriers, pickup capacity, the alternative corridor's extra time) and the prior on blockage duration are
 * ASSUMPTIONS of this demo (the frontend has no dispatch capacity data); the UI labels them SIM.
 */
export function buildPlanSnapshot(incidentId: string): PlanSnapshot {
  const w = getWorld();
  const inc = w.incidents[incidentId];
  if (!inc) throw new Error(`Unknown incident ${incidentId}`);
  const now = demoNow();
  const ids = [...inc.affected, ...inc.exposed];
  const parcels = ids
    .map((id) => w.shipments[id])
    .filter(Boolean)
    .map((s) => ({
      id: s.id,
      van: s.courier?.vehicle ?? s.id,
      value: s.valueSar,
      slackMin: Math.max(5, (s.window.end - now) / 60_000),
      remainingMin: Math.max(5, remainingM(s, now) / CRUISE_MPS / 60),
      service: s.service,
      exposed: inc.exposed.includes(s.id),
      pickupOk: s.service !== "Same-day",
      reachable: w.contexts[s.id]?.recipient.responsiveness !== "low",
    }));
  const pickups = Object.values(places)
    .filter((p) => p.kind === "pickup" || p.kind === "locker")
    .slice(0, 2)
    .map((p, i) => ({ id: p.id, travelMin: 20 + 6 * i, capacity: 3, online: true }));
  return {
    incidentId,
    scope: inc.sharedFactor.corridorId ? "corridor" : "facility",
    scopeId: inc.sharedFactor.corridorId ?? inc.sharedFactor.placeId ?? incidentId,
    now,
    belief: { pLong: 0.3 },
    dispatcherContactable: true,
    parcels,
    resources: { spares: [{ id: "S1", etaMin: 20, capacity: 3 }, { id: "S2", etaMin: 28, capacity: 2 }], pickups, alt: { available: true, extraMin: 55 } },
  };
}
