"use client";

import { getRoute } from "@/data/network";
import { createLaneShipment } from "@/data/scenario/laneTraffic";
import { SCENARIO_START } from "@/lib/time";
import { addEvent, addLedger, notify } from "@/services/demo/mutations";
import { distanceAt } from "@/services/logic/movement";
import { createInitialWorld } from "@/simulation/initialWorld";
import { BEATS, beatDueAt } from "@/simulation/scenario";
import { clockNow, getWorld, updateWorld, useWorld } from "@/store/world";
import { useUi } from "@/store/ui";

/**
 * Demo simulation engine: runs the operations clock, delivers vehicles that
 * reach their destination, keeps normal lane traffic flowing, and fires story
 * beats (automatically or on demand). Pure client-side; no network.
 */

const TICK_MS = 500;
const MIN_MOVING_LANE = 7;
const MAX_DELIVERED_GENERATED = 18;
let timer: ReturnType<typeof setInterval> | null = null;
let lastBeatReal = 0;

export function startSimulation() {
  if (typeof window === "undefined") return;
  if (!getWorld().ready) {
    const manual = new URLSearchParams(window.location.search).get("demo") === "manual";
    useWorld.setState(createInitialWorld(0, !manual));
  }
  if (!timer) timer = setInterval(tick, TICK_MS);
}

function tick() {
  const w = getWorld();
  if (!w.ready || !w.clock.running) return;
  const now = clockNow(w.clock);

  // Deliveries: vehicles with no hold that reached the end of their route.
  const arrived = Object.values(w.shipments).filter((s) => {
    if (s.closed || s.movement.mode !== "route" || s.movement.holdAtM !== undefined) return false;
    const route = getRoute(s.routeKey);
    return !!route && distanceAt(s.movement, route.lengthM, now) >= route.lengthM - 1;
  });
  if (arrived.length) {
    updateWorld((d) => {
      for (const a of arrived) {
        const s = d.shipments[a.id];
        s.movement = { ...s.movement, mode: "delivered", distanceM: getRoute(s.routeKey)!.lengthM, updatedAt: now };
        s.stage = "delivered";
        s.closed = true;
        if (s.health === "recovering") s.health = "recovered";
        else if (s.health !== "prevented" && s.health !== "recovered") s.health = "delivered";
        s.outcome ??= { kind: "delivered", label: "Delivered", at: now };
        if (s.health === "prevented" && s.outcome.kind === "prevented") s.outcome = { ...s.outcome, label: "Delivered · failure prevented" };
        addEvent(d, s.id, { at: now, title: "Delivered · OTP verified", source: "scan", tone: "ok", location: s.destination.district });
        for (const l of d.ledger) {
          if (l.shipmentId === s.id && l.outcome === "pending") Object.assign(l, { outcome: s.health === "prevented" ? "prevented" : "recovered", outcomeAt: now });
        }
        if (!s.generated && s.outcome.kind !== "delivered") {
          notify(d, { at: now, kind: "outcome", tone: "ok", title: `${s.id} delivered`, body: s.outcome.label, target: { type: "shipment", id: s.id }, actor: "Journey scans" });
        }
      }
      // Keep the store bounded during long sessions.
      const deliveredGenerated = Object.values(d.shipments)
        .filter((s) => s.generated && s.closed)
        .sort((a, b) => a.lastEventAt - b.lastEventAt);
      for (const s of deliveredGenerated.slice(0, Math.max(0, deliveredGenerated.length - MAX_DELIVERED_GENERATED))) {
        delete d.shipments[s.id];
        delete d.journeys[s.id];
        delete d.contexts[s.id];
      }
    });
  }

  // Lane traffic keeps the network visibly alive.
  const movingLane = Object.values(w.shipments).filter((s) => !s.closed && s.caseType === "normal" && s.movement.mode === "route" && s.health === "on_track").length;
  if (movingLane < MIN_MOVING_LANE && now >= w.scenario.nextDispatchAt) {
    const { shipment, journey } = createLaneShipment(w.scenario.nextLaneSeq, now);
    updateWorld((d) => {
      d.shipments[shipment.id] = shipment;
      d.journeys[shipment.id] = journey;
      d.contexts[shipment.id] = {
        address: { confidence: 0.92, checks: [], pastFailuresAtAddress: 0, firstDeliveryToAddress: false },
        recipient: { preferredChannel: "WhatsApp", responsiveness: "medium", missedWindows: [] },
        telemetry: {},
      };
      d.scenario.nextLaneSeq += 1;
      d.scenario.nextDispatchAt = now + (40 + ((d.scenario.nextLaneSeq * 17) % 40)) * 1000;
    });
  }

  // Autoplay story beats, never stepping on an interaction in progress.
  if (!w.scenario.autoplay) return;
  const ui = useUi.getState();
  const busy = !!ui.escalation || !!ui.groupResponseIncidentId || Object.values(w.agentRuns).some((r) => r.status === "running");
  if (busy || Date.now() < w.scenario.holdUntilReal || Date.now() - lastBeatReal < 4000) return;
  const due = BEATS.find((b) => !w.scenario.firedBeats.includes(b.id) && now >= beatDueAt(b));
  if (due) fireBeat(due.id);
}

export function fireBeat(id: string) {
  const beat = BEATS.find((b) => b.id === id);
  if (!beat || getWorld().scenario.firedBeats.includes(id)) return;
  lastBeatReal = Date.now();
  updateWorld((d) => void d.scenario.firedBeats.push(id));
  beat.run();
}

/** Fire the next pending beat now (presenter control). The clock is not jumped, so traffic never teleports. */
export function nextBeat() {
  const w = getWorld();
  const pending = BEATS.find((b) => !w.scenario.firedBeats.includes(b.id));
  if (!pending) return;
  fireBeat(pending.id);
}

export function setRunning(running: boolean) {
  updateWorld((d) => {
    const now = clockNow(d.clock);
    d.clock.baseDemo = now;
    d.clock.baseReal = Date.now();
    d.clock.running = running;
  });
}

export function setAutoplay(autoplay: boolean) {
  updateWorld((d) => {
    d.scenario.autoplay = autoplay;
  });
}

export function resetScenario() {
  const w = getWorld();
  lastBeatReal = 0;
  useUi.setState({ selectedShipmentId: null, selectedFacilityId: null, escalation: null, groupResponseIncidentId: null, emailPreviewId: null, toasts: [], assistantMessages: [], mapFocus: { kind: "network", nonce: Date.now() } });
  useWorld.setState(createInitialWorld(w.scenario.generation + 1, w.scenario.autoplay));
}

export const pendingBeats = () => BEATS.filter((b) => !getWorld().scenario.firedBeats.includes(b.id));
export const scenarioElapsedMin = () => Math.round((clockNow(getWorld().clock) - SCENARIO_START) / 60_000);
export { addLedger };
