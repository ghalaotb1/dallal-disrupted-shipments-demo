import { routes, places } from "@/data/network";
import { pointAt } from "@/lib/geo";
import type { DemoTime, LngLat, ShipmentHealth } from "@/types/domain";
import type { Driver, OpsWorld, Parcel } from "@/types/ops";

const CRUISE_MPS = 8.5;

export function routeLength(d: Driver): number {
  return routes[d.routeKey]?.lengthM ?? 0;
}

/** Metres along the route at `now` (demo clock). */
export function vanDistance(d: Driver, now: DemoTime): number {
  const len = routeLength(d);
  const raw = d.nav.distanceM + (d.nav.speedMps * Math.max(0, now - d.nav.updatedAt)) / 1000;
  return Math.min(len, d.nav.holdAtM !== undefined ? Math.min(raw, d.nav.holdAtM) : raw);
}

export function vanPosition(d: Driver, now: DemoTime): LngLat {
  const r = routes[d.routeKey];
  return r ? pointAt(r, vanDistance(d, now)) : [50.1, 26.4];
}

/** A van that is held (traffic/blockage) and has reached its hold point. */
export function isHeld(d: Driver, now: DemoTime): boolean {
  return d.nav.holdAtM !== undefined && vanDistance(d, now) >= d.nav.holdAtM - 1;
}

/** Done = physically delivered on the way, or recovered/prevented after an action. */
export function isDelivered(p: Parcel, d: Driver, now: DemoTime): boolean {
  return p.state === "scheduled" && vanDistance(d, now) >= p.stopAtM + 25;
}

export function parcelHealth(p: Parcel, d: Driver, now: DemoTime): ShipmentHealth {
  switch (p.state) {
    case "attempt_failed":
      return "disrupted";
    case "at_risk":
      return "at_risk";
    case "awaiting_manager":
      return "review";
    case "recovering":
    case "reassigned":
      return "recovering";
    case "prevented":
      return "prevented";
    case "recovered":
      return "recovered";
    default:
      return isDelivered(p, d, now) ? "delivered" : "on_track";
  }
}

export const isDone = (h: ShipmentHealth) => h === "delivered" || h === "prevented" || h === "recovered";
export const needsAttention = (h: ShipmentHealth) => h === "disrupted" || h === "at_risk" || h === "review";

export interface DriverSummary {
  driver: Driver;
  parcels: Parcel[];
  total: number;
  done: number;
  disrupted: number;
  atRisk: number;
  review: number;
  recovering: number;
  moved: number;
  /** Worst status among this driver's parcels, for the card accent. */
  worst: ShipmentHealth;
  held: boolean;
  nextStop?: Parcel;
  nextEta?: DemoTime;
}

const RANK: Record<ShipmentHealth, number> = { disrupted: 6, review: 5, at_risk: 4, recovering: 3, on_track: 2, recovered: 1, prevented: 1, delivered: 0 };

export function summarize(w: Pick<OpsWorld, "drivers" | "parcels">, now: DemoTime): DriverSummary[] {
  return Object.values(w.drivers).map((driver) => {
    const parcels = Object.values(w.parcels).filter((p) => p.driverId === driver.id).sort((a, b) => a.seq - b.seq);
    let done = 0, disrupted = 0, atRisk = 0, review = 0, recovering = 0, moved = 0;
    let worst: ShipmentHealth = "delivered";
    let nextStop: Parcel | undefined;
    for (const p of parcels) {
      const h = parcelHealth(p, driver, now);
      if (p.state === "reassigned") moved += 1;
      if (isDone(h)) done += 1;
      else if (h === "disrupted") disrupted += 1;
      else if (h === "at_risk") atRisk += 1;
      else if (h === "review") review += 1;
      else if (h === "recovering") recovering += 1;
      if (RANK[h] > RANK[worst]) worst = h;
      if (!nextStop && !isDone(h) && p.state !== "reassigned" && p.stopAtM > vanDistance(driver, now) - 25) nextStop = p;
    }
    const held = isHeld(driver, now);
    const nextEta = nextStop && !held && driver.nav.speedMps > 0.8 ? now + ((nextStop.stopAtM - vanDistance(driver, now)) / driver.nav.speedMps) * 1000 : undefined;
    return { driver, parcels, total: parcels.length, done, disrupted, atRisk, review, recovering, moved, worst, held, nextStop, nextEta };
  });
}

export function driverOf(w: Pick<OpsWorld, "drivers">, p: Parcel): Driver {
  return w.drivers[p.driverId];
}

export function remainingMin(p: Parcel, d: Driver, now: DemoTime): number {
  return Math.max(5, Math.round(((p.stopAtM - vanDistance(d, now)) / CRUISE_MPS / 60) * 10) / 10);
}

export function originName(id: string) {
  return places[id]?.name ?? id;
}
