import { routes } from "@/data/network";
import { pointAt } from "@/lib/geo";
import { fmtTime } from "@/lib/time";
import type { JourneyEvent } from "@/types/domain";
import type { OpsWorld, ScenarioId } from "@/types/ops";

const MIN = 60_000;

export interface ScenarioMeta {
  id: ScenarioId;
  /** Use case the situation illustrates, in product words. */
  useCase: string;
  tone: "ok" | "info" | "review";
}

/** Presentation labels only. What actually happens in each case comes from the real agent and policy, never from this table. */
export const SCENARIOS: ScenarioMeta[] = [
  { id: "A", useCase: "Resolved automatically", tone: "ok" },
  { id: "B", useCase: "Asks, then resolves", tone: "info" },
  { id: "C", useCase: "Escalates to manager", tone: "review" },
];

const ev = (parcelId: string, at: number, title: string, detail: string | undefined, code: string): JourneyEvent => ({ id: `${parcelId}-ex-${at}`, shipmentId: parcelId, at, title, detail, source: "courier", tone: "crit", code });

function log(w: OpsWorld, at: number, text: string, tone: "info" | "ok" | "warn" | "review" = "info", parcelId?: string) {
  w.events.unshift({ id: `E-${w.events.length + 1}-${at}`, at, text, tone, parcelId });
}

function stageA(w: OpsWorld, now: number) {
  const hero = w.parcels["DL-20417"];
  const van = w.drivers[hero.driverId];
  van.nav = { distanceM: 4820, speedMps: 9, updatedAt: now };
  const t = now - 8 * MIN;
  hero.state = "attempt_failed";
  hero.headline = "Delivery attempt failed · address not found";
  hero.exception = { code: "ADR", label: "Address not found", recordedAt: t };
  hero.attempts = 1;
  hero.window = { start: now - 60 * MIN, end: now + 120 * MIN };
  const ctx = w.contexts[hero.id];
  ctx.address = {
    confidence: 0.5,
    firstDeliveryToAddress: true,
    pastFailuresAtAddress: 0,
    checks: [
      { label: "National Address short code", result: "pass", detail: "Valid code" },
      { label: "Customer pin vs registered address", result: "fail", detail: "Pin is 320 m from the registered address" },
    ],
  };
  ctx.telemetry = { attempt: { at: t, distanceToAddressM: 320, dwellSec: 150, callAttempts: 1 } };
  w.journeys[hero.id].push(ev(hero.id, t, "Delivery attempt failed · ADR", "Door dwell 2m 30s · customer pin 320 m from the address", "ADR"));
  log(w, t, `${van.name} could not find the address for ${hero.id}`, "warn", hero.id);
  w.cases.push({
    scenario: "A", label: "Address not found", parcelId: hero.id, driverId: van.id, affectedDriverIds: [van.id], exposedParcelIds: [],
    problem: { title: "Address not found", detail: `${van.name} · stop ${hero.seq} · ${hero.service}, SAR ${hero.valueSar} · failed ${fmtTime(t)}` },
  });
}

function stageB(w: OpsWorld, now: number) {
  const hero = w.parcels["DL-20655"];
  const van = w.drivers[hero.driverId];
  van.nav = { distanceM: 5610, speedMps: 9, updatedAt: now };
  const t = now - 8 * MIN;
  hero.state = "attempt_failed";
  hero.headline = "Delivery attempt failed · nobody answered";
  hero.exception = { code: "RNA", label: "Recipient not available", recordedAt: t };
  hero.attempts = 1;
  hero.window = { start: now - 40 * MIN, end: now + 100 * MIN };
  const ctx = w.contexts[hero.id];
  ctx.address = { confidence: 0.9, firstDeliveryToAddress: false, pastFailuresAtAddress: 0, checks: [{ label: "National Address short code", result: "pass", detail: "Valid code" }] };
  ctx.recipient = { preferredChannel: "WhatsApp", responsiveness: "medium", missedWindows: [{ at: now - 26 * 60 * MIN, window: "15:00-17:00", note: "No answer at the door" }] };
  ctx.telemetry = { attempt: { at: t, distanceToAddressM: 35, dwellSec: 150, callAttempts: 2 } };
  w.journeys[hero.id].push(ev(hero.id, t, "Delivery attempt failed · RNA", "Door dwell 2m 30s · 2 calls unanswered", "RNA"));
  log(w, t, `${van.name}: nobody answered for ${hero.id}`, "warn", hero.id);
  w.cases.push({
    scenario: "B", label: "Customer not answering", parcelId: hero.id, driverId: van.id, affectedDriverIds: [van.id], exposedParcelIds: [],
    problem: { title: "Customer not answering", detail: `${van.name} · stop ${hero.seq} · ${hero.service}, SAR ${hero.valueSar} · failed ${fmtTime(t)}` },
  });
}

/** Parcels of a driver by stop distance (stable even though plain ids are generated). */
const at = (w: OpsWorld, driverId: string, stopAtM: number) => Object.values(w.parcels).find((p) => p.driverId === driverId && p.stopAtM === stopAtM)!;

function stageC(w: OpsWorld, now: number) {
  // Vans queue behind a lane blockage near 8.4 km on King Fahd Rd (all three routes share this road).
  const queue: [string, number, number][] = [["salem", 7350, 7650], ["nawaf", 6000, 6300], ["majid", 5200, 5500]];
  for (const [id, dist, hold] of queue) w.drivers[id] = { ...w.drivers[id], nav: { distanceM: dist, speedMps: 0.5, updatedAt: now, holdAtM: hold }, note: "Slow traffic on King Fahd Rd" };
  const affected: [string, number, number][] = [["salem", 7700, 3], ["nawaf", 6400, 7], ["nawaf", 7100, 11], ["majid", 5600, 15]];
  const exposed: [string, number][] = [["salem", 8900], ["salem", 11000], ["nawaf", 9300], ["nawaf", 11500], ["majid", 9100], ["majid", 11700]];
  // Remaining promise time (minutes) per parcel, in plan order: they are what the joint plan has to protect.
  const slack = [53, 62, 39, 90, 48, 67, 84, 34, 78, 56];
  const byOrder = [["salem", 7700], ["salem", 8900], ["salem", 11000], ["nawaf", 6400], ["nawaf", 7100], ["nawaf", 9300], ["nawaf", 11500], ["majid", 5600], ["majid", 9100], ["majid", 11700]] as [string, number][];
  byOrder.forEach(([d, m], i) => {
    const p = at(w, d, m);
    p.window = { start: now - 30 * MIN, end: now + slack[i] * MIN };
    p.incident = true;
    w.contexts[p.id].telemetry = { corridorSpeedKmh: 28, corridorTypicalKmh: 62 };
  });
  for (const [d, m, minsAgo] of affected) {
    const p = at(w, d, m);
    const t = now - minsAgo * MIN;
    p.state = "at_risk";
    p.headline = "Delayed in traffic";
    p.exception = { code: "DLY", label: "Traffic delay", recordedAt: t };
    w.journeys[p.id].push(ev(p.id, t, "Exception recorded · DLY", "Van stuck in slow traffic on King Fahd Rd", "DLY"));
    log(w, t, `${w.drivers[d].name}: ${p.id} delayed in traffic`, "warn", p.id);
  }
  for (const [d, m] of exposed) {
    const p = at(w, d, m);
    p.state = "at_risk";
    p.headline = "Route passes the slow section";
  }
  const hero = at(w, "salem", 7700);
  const r = routes[w.drivers.salem.routeKey];
  w.blockage = { coord: r ? pointAt(r, 8360) : [50.19, 26.35], radiusM: 340, label: "King Fahd Rd · lane blockage" };
  w.cases.push({
    scenario: "C", label: "Road blockage", parcelId: hero.id, driverId: "salem", affectedDriverIds: ["salem", "nawaf", "majid"], exposedParcelIds: exposed.map(([d, m]) => at(w, d, m).id),
    problem: { title: "Road blockage · King Fahd Rd", detail: "3 drivers · 4 delayed · 6 exposed" },
  });
}

/** The operation as the product opens: three situations are already open on three different routes. */
export function stageAll(w: OpsWorld, now: number) {
  w.cases = [];
  stageA(w, now);
  stageB(w, now);
  stageC(w, now);
}
