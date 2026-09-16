import { computePriority } from "@/services/logic/priority";
import { assessRisk } from "@/services/logic/risk";
import { nextId, type WorldState } from "@/store/world";
import type { AppNotification, DemoTime, JourneyEvent, LedgerEntry, Shipment } from "@/types/domain";

/** Draft-level helpers shared by demo adapters and scenario beats (call inside updateWorld). */

export function addEvent(d: WorldState, shipmentId: string, e: Omit<JourneyEvent, "id" | "shipmentId">) {
  const list = (d.journeys[shipmentId] ??= []);
  list.push({ ...e, id: nextId("EV"), shipmentId });
  list.sort((a, b) => a.at - b.at);
  const s = d.shipments[shipmentId];
  if (s) s.lastEventAt = Math.max(s.lastEventAt, e.at);
}

export function rescore(d: WorldState, shipmentId: string, now: DemoTime) {
  const s = d.shipments[shipmentId];
  const ctx = d.contexts[shipmentId];
  if (!s || !ctx) return;
  s.risk = assessRisk(s as Shipment, ctx, now);
  s.priority = computePriority(s as Shipment);
}

export function setHealth(d: WorldState, shipmentId: string, health: Shipment["health"]) {
  const s = d.shipments[shipmentId];
  if (!s) return;
  s.health = health;
  s.priority = computePriority(s as Shipment);
}

export function notify(d: WorldState, n: Omit<AppNotification, "id" | "read">): AppNotification {
  const full: AppNotification = { ...n, id: nextId("N"), read: false };
  d.notifications.unshift(full);
  return full;
}

export function addLedger(d: WorldState, e: Omit<LedgerEntry, "id">) {
  d.ledger.unshift({ ...e, id: nextId("L") });
}

export function completeStep(d: WorldState, step: string) {
  if (!d.scenario.completedSteps.includes(step)) d.scenario.completedSteps.push(step);
}
