import { places } from "@/data/network";
import { fmtKm } from "@/lib/format";
import { fmtDuration, fmtTime, fmtWindow } from "@/lib/time";
import { estimateEta } from "@/services/logic/movement";
import type { CauseCode, DemoTime, Diagnosis, Evidence, Shipment, ShipmentContext } from "@/types/domain";

/**
 * Deterministic evidence layer (blueprint §6): compare the recorded exception
 * code against independent signals and state agreement or conflict plainly.
 * Real logic, running on simulated case data.
 */

const CODE_TO_CAUSE: Record<string, CauseCode> = {
  RNA: "recipient_unavailable",
  ADR: "address_issue",
  DLY: "route_disruption",
  NSC: "facility_backlog",
  LKR: "pickup_point_unavailable",
  RSC: "route_disruption",
  POD: "none",
};

export const CAUSE_LABEL: Record<CauseCode, string> = {
  address_issue: "Address quality issue",
  recipient_unavailable: "Recipient unavailable",
  attempt_not_completed: "Attempt not physically completed",
  route_disruption: "Route disruption",
  facility_backlog: "Facility backlog",
  pickup_point_unavailable: "Pickup point unavailable",
  capacity_sequence: "Route capacity / stop sequence",
  custody_anomaly: "Unexplained custody pattern",
  none: "No disruption signal",
};

export interface DiagnosisInput {
  shipment: Shipment;
  context: ShipmentContext;
  now: DemoTime;
  corridorPeers: Shipment[];
}

export function analyzeDisruption({ shipment: s, context: ctx, now, corridorPeers }: DiagnosisInput): Diagnosis {
  const ev: Evidence[] = [];
  const push = (e: Omit<Evidence, "id">) => ev.push({ ...e, id: `${s.id}-ev-${ev.length}` });
  const recorded = s.exception ? { code: s.exception.code, label: s.exception.label } : undefined;
  const t = ctx.telemetry;
  const corridorSlow = t.corridorSpeedKmh !== undefined && t.corridorTypicalKmh ? t.corridorSpeedKmh / t.corridorTypicalKmh < 0.45 : false;
  const slowPeers = corridorPeers.filter((p) => p.id !== s.id && (p.health === "disrupted" || p.flags.includes("stalled") || p.exception));

  const finish = (cause: CauseCode, confidence: Diagnosis["confidence"], headline: string, summary: string): Diagnosis => {
    let agreement: Diagnosis["agreement"] = "no_code";
    if (cause === "custody_anomaly") agreement = "inconclusive";
    else if (recorded) agreement = CODE_TO_CAUSE[recorded.code] === cause ? "agrees" : "conflicts";
    return { headline, summary, cause, causeLabel: CAUSE_LABEL[cause], confidence, agreement, recorded, evidence: ev };
  };

  // 1 ─ Custody anomaly: scans that no known pattern explains. Do not invent a cause.
  if (ctx.custody?.conflictingScans) {
    push({ label: "Conflicting custody scans", detail: ctx.custody.note, stance: "supports", source: "Journey scans" });
    if (t.attempt) {
      push({
        label: "Delivered scan without OTP",
        detail: `Photo proof only · ${t.attempt.dwellSec}s at door · no call logged`,
        stance: "context",
        source: "Courier app",
      });
    }
    push({ label: "Recipient disputes delivery", detail: "Reported parcel not received via app", stance: "contradicts", source: "Recipient" });
    push({ label: "No related incident on route", detail: "No other shipments show this sequence today", stance: "context", source: "Incident detector" });
    return finish(
      "custody_anomaly",
      "low",
      "No known pattern explains this journey",
      "Scans show the parcel delivered and then out for delivery again on another van. Dallal cannot attribute a cause with confidence.",
    );
  }

  // 2 ─ Attempt logged but vehicle was never at the door.
  if (t.attempt && (t.attempt.distanceToAddressM > 500 || t.attempt.dwellSec < 20) && t.attempt.callAttempts === 0) {
    push({
      label: "Vehicle not at address during attempt",
      detail: `GPS ${fmtKm(t.attempt.distanceToAddressM)} from address at ${fmtTime(t.attempt.at)} · ${t.attempt.dwellSec}s dwell`,
      stance: "contradicts",
      source: "Courier GPS",
    });
    push({ label: "No call or message to recipient", detail: "0 contact attempts logged before the exception", stance: "contradicts", source: "Contact log" });
    if (ctx.recipient.confirmedWindow) {
      push({
        label: "Recipient confirmed availability",
        detail: `Confirmed ${fmtWindow(ctx.recipient.confirmedWindow)} at ${fmtTime(ctx.recipient.confirmedWindow.at)}`,
        stance: "contradicts",
        source: "WhatsApp log",
      });
    }
    if (corridorSlow) {
      push({
        label: "Vehicle held in corridor congestion",
        detail: `${t.corridorSpeedKmh} km/h on corridor vs ${t.corridorTypicalKmh} km/h typical`,
        stance: "supports",
        source: "Route telemetry",
      });
    }
    if (slowPeers.length) {
      push({
        label: `${slowPeers.length} other shipment${slowPeers.length > 1 ? "s" : ""} on corridor affected`,
        detail: slowPeers.slice(0, 4).map((p) => p.id).join(", "),
        stance: "context",
        source: "Incident detector",
      });
    }
    return finish(
      "attempt_not_completed",
      ctx.recipient.confirmedWindow ? "high" : "medium",
      recorded ? `Recorded “${recorded.label}” is not supported by evidence` : "Attempt not physically completed",
      corridorSlow
        ? "The courier logged a failed attempt while the van was still held on the corridor, far from the address. The likely cause is route congestion, not the recipient."
        : "The failed attempt was logged away from the address with no contact attempt.",
    );
  }

  // 3 ─ Recipient genuinely unavailable (door dwell + calls, or repeated missed windows).
  const missed = ctx.recipient.missedWindows;
  if ((t.attempt && t.attempt.dwellSec >= 60 && t.attempt.callAttempts >= 1) || missed.length >= 2) {
    if (t.attempt) {
      push({
        label: "Courier waited at the door",
        detail: `${Math.round(t.attempt.dwellSec / 60)}m ${t.attempt.dwellSec % 60}s dwell within ${fmtKm(t.attempt.distanceToAddressM)} · ${t.attempt.callAttempts} call${t.attempt.callAttempts === 1 ? "" : "s"} unanswered`,
        stance: "supports",
        source: "Courier GPS",
      });
    }
    if (missed.length) {
      push({
        label: `${missed.length} missed delivery window${missed.length > 1 ? "s" : ""}`,
        detail: missed.map((m) => `${m.window} (${m.note})`).join(" · "),
        stance: "supports",
        source: "Attempt history",
      });
    }
    push({
      label: `Recipient responsiveness: ${ctx.recipient.responsiveness}`,
      detail: `Preferred channel ${ctx.recipient.preferredChannel}`,
      stance: ctx.recipient.responsiveness === "high" ? "context" : "supports",
      source: "Contact history",
    });
    push({
      label: `Address confidence ${ctx.address.confidence.toFixed(2)}`,
      detail: ctx.address.confidence >= 0.8 ? "Address validated — not the likely cause" : "Address may contribute",
      stance: "context",
      source: "Address validation",
    });
    return finish(
      "recipient_unavailable",
      missed.length >= 2 ? "high" : "medium",
      missed.length >= 2 ? "Pattern of missed delivery windows" : "Recipient was not available at the door",
      missed.length >= 2
        ? "Repeated attempts at a validated address went unanswered. The current window is likely to fail the same way."
        : "Door dwell and unanswered calls are consistent with the recorded exception.",
    );
  }

  // 4 ─ Address quality.
  if (ctx.address.confidence < 0.6) {
    for (const chk of ctx.address.checks.filter((x) => x.result !== "pass")) {
      push({ label: chk.label, detail: chk.detail, stance: "supports", source: "National Address validation" });
    }
    if (ctx.address.pastFailuresAtAddress) {
      push({
        label: `${ctx.address.pastFailuresAtAddress} address-related failures on this street`,
        detail: "Last 30 days (simulated history)",
        stance: "supports",
        source: "Delivery history",
      });
    }
    if (ctx.address.firstDeliveryToAddress) push({ label: "First delivery to this address", detail: "No prior successful delivery", stance: "context", source: "Delivery history" });
    push({
      label: `Recipient responsiveness: ${ctx.recipient.responsiveness}`,
      detail: `Reachable on ${ctx.recipient.preferredChannel} — address can be confirmed before arrival`,
      stance: "context",
      source: "Contact history",
    });
    return finish(
      "address_issue",
      ctx.address.confidence < 0.45 ? "high" : "medium",
      s.exception ? "Address could not be resolved" : "High likelihood of address-related failure",
      "The National Address and the customer pin disagree. The courier is likely to fail at the door unless the address is confirmed first.",
    );
  }

  // 5 ─ Route disruption.
  if (corridorSlow) {
    push({
      label: "Corridor speed collapsed",
      detail: `${t.corridorSpeedKmh} km/h vs ${t.corridorTypicalKmh} km/h typical`,
      stance: "supports",
      source: "Route telemetry",
    });
    if (s.movement.stationarySince) {
      push({ label: "Vehicle stationary", detail: `for ${fmtDuration(now - s.movement.stationarySince)}`, stance: "supports", source: "Courier GPS" });
    }
    const eta = estimateEta(s, now);
    if (eta && eta > s.window.end) {
      push({ label: "ETA beyond promised window", detail: `ETA ${fmtTime(eta)} vs window ${fmtWindow(s.window)}`, stance: "supports", source: "ETA estimate" });
    }
    if (slowPeers.length) {
      push({
        label: `${slowPeers.length} other shipments on corridor affected`,
        detail: slowPeers.slice(0, 4).map((p) => p.id).join(", "),
        stance: "context",
        source: "Incident detector",
      });
    }
    return finish("route_disruption", "high", "Delayed by route disruption", "The vehicle is held in corridor congestion; the delay is not caused by the recipient or address.");
  }

  // 6 ─ Facility backlog.
  if (ctx.facility && now - ctx.facility.lastScanAt > 2 * 3_600_000) {
    const place = places[ctx.facility.placeId];
    push({
      label: "No scan since arrival",
      detail: `Last scan ${fmtTime(ctx.facility.lastScanAt)} at ${place.short} · ${fmtDuration(now - ctx.facility.lastScanAt)} ago`,
      stance: "supports",
      source: "Facility scans",
    });
    if (ctx.facility.backlogParcels) push({ label: "Facility backlog", detail: `${ctx.facility.backlogParcels} parcels awaiting sort`, stance: "supports", source: "Branch operations" });
    if (ctx.facility.note) push({ label: "Equipment event", detail: ctx.facility.note, stance: "supports", source: "Branch operations" });
    return finish("facility_backlog", "high", "Stalled in branch backlog", "The parcel has not been scanned since arrival while the branch works through a sorting backlog.");
  }

  // 7 ─ Pickup point unavailable.
  if (ctx.pickupPoint?.status === "offline") {
    push({ label: "Pickup point offline", detail: places[ctx.pickupPoint.placeId].name, stance: "supports", source: "Pickup network" });
    return finish("pickup_point_unavailable", "high", "Assigned pickup point unavailable", "The parcel cannot be deposited at its assigned locker.");
  }

  // 8 ─ Capacity / stop sequencing (SLA at risk on a healthy route).
  const eta = estimateEta(s, now);
  if (eta && eta > s.slaDeadline) {
    push({ label: "ETA beyond service promise", detail: `ETA ${fmtTime(eta)} vs ${s.service} promise ${fmtTime(s.slaDeadline)}`, stance: "supports", source: "ETA estimate" });
    if (s.movement.stopsAhead) push({ label: `${s.movement.stopsAhead} stops ahead on van`, detail: "Parcel is late in the stop sequence", stance: "supports", source: "Route plan" });
    push({ label: "Route traffic normal", detail: "No corridor slowdown detected", stance: "context", source: "Route telemetry" });
    return finish("capacity_sequence", "medium", "Service promise at risk from stop sequence", "The route is healthy, but the parcel sits too late in the van's stop sequence to meet its promise.");
  }

  push({ label: "Journey within normal pattern", detail: "No exception or risk signal", stance: "context", source: "Journey scans" });
  return finish("none", "high", "No disruption detected", "Shipment is progressing normally.");
}
