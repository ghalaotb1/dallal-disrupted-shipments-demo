import { getRoute, places } from "@/data/network";
import { pointAt } from "@/lib/geo";
import type { DemoTime, LngLat, Movement, Shipment } from "@/types/domain";

/** Distance over which a vehicle slows into a traffic queue or its next stop. */
export const RAMP_M = 700;

/**
 * Closed-form vehicle progress. Constant speed until the ramp before `holdAtM`,
 * then an exponential approach (natural "crawl to a stop"). Because the function
 * composes (advance a then b == advance a+b), the simulation can re-anchor at any
 * tick and the map can extrapolate every frame with identical results.
 */
export function distanceAt(m: Movement, lengthM: number, now: DemoTime): number {
  if (m.mode !== "route") return m.mode === "delivered" ? lengthM : m.distanceM;
  let d = m.distanceM;
  let t = Math.max(0, (now - m.updatedAt) / 1000);
  const v = m.speedMps;
  if (v <= 0 || t === 0) return Math.min(d, lengthM);
  const hold = m.holdAtM;
  if (hold === undefined) return Math.min(lengthM, d + v * t);
  if (d >= hold) return d;
  const rampStart = hold - RAMP_M;
  if (d < rampStart) {
    const toRamp = (rampStart - d) / v;
    if (t <= toRamp) return d + v * t;
    t -= toRamp;
    d = rampStart;
  }
  return hold - (hold - d) * Math.exp((-v * t) / RAMP_M);
}

export function isEffectivelyStopped(m: Movement, lengthM: number, now: DemoTime) {
  if (m.mode !== "route") return true;
  if (m.holdAtM === undefined) return false;
  return m.holdAtM - distanceAt(m, lengthM, now) < 60;
}

export function shipmentPosition(s: Shipment, now: DemoTime): LngLat {
  if (s.movement.mode === "facility" && s.movement.facilityId) return places[s.movement.facilityId].coord;
  const route = getRoute(s.routeKey);
  if (!route) return s.destination.coord;
  if (s.movement.mode === "delivered") return route.coords[route.coords.length - 1];
  return pointAt(route, distanceAt(s.movement, route.lengthM, now));
}

export function progressOf(s: Shipment, now: DemoTime) {
  const route = getRoute(s.routeKey);
  if (!route) return 0;
  if (s.movement.mode === "facility") return 0;
  if (s.movement.mode === "delivered") return 1;
  return distanceAt(s.movement, route.lengthM, now) / route.lengthM;
}

export function remainingM(s: Shipment, now: DemoTime) {
  const route = getRoute(s.routeKey);
  if (!route) return 0;
  if (s.movement.mode === "facility") return route.lengthM;
  return Math.max(0, route.lengthM - distanceAt(s.movement, route.lengthM, now));
}

/** Freeze a movement at `now` (used before changing speed / hold / route). */
export function anchorMovement(s: Shipment, now: DemoTime): Movement {
  const route = getRoute(s.routeKey);
  const d = route ? distanceAt(s.movement, route.lengthM, now) : s.movement.distanceM;
  return { ...s.movement, distanceM: d, updatedAt: now };
}

/** Realistic ETA (in demo time) used for display, independent of animation speed. */
export function estimateEta(s: Shipment, now: DemoTime): DemoTime | null {
  if (s.closed || s.movement.mode === "delivered") return null;
  const remaining = remainingM(s, now);
  const cruise = 8.5; // m/s urban average incl. traffic lights
  const stopMin = (s.movement.stopsAhead ?? Math.round(remaining / 2500)) * 4;
  if (s.movement.mode === "facility") {
    const departure = Math.max(now, s.window.start - 45 * 60_000);
    return departure + (remaining / cruise) * 1000 + stopMin * 60_000;
  }
  const route = getRoute(s.routeKey);
  const held = route && s.movement.holdAtM !== undefined && isEffectivelyStopped(s.movement, route.lengthM, now);
  const delay = held ? 35 * 60_000 : 0;
  return now + (remaining / cruise) * 1000 + stopMin * 60_000 + delay;
}
