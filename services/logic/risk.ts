import { estimateEta } from "@/services/logic/movement";
import type { DemoTime, RiskAssessment, RiskDriver, RiskLevel, Shipment, ShipmentContext } from "@/types/domain";

/**
 * PROTOTYPE RISK HEURISTIC — not a trained model.
 * A transparent additive score over simulated case signals so the demo can show
 * risk moving for the right reasons. In the next phase `predict_risk()` calls the
 * trained failure-risk model; this function's interface stays the same.
 */
export function assessRisk(s: Shipment, ctx: ShipmentContext, now: DemoTime): RiskAssessment {
  const parts: { label: string; points: number; source: string }[] = [];
  const add = (label: string, points: number, source: string) => {
    if (Math.abs(points) >= 1) parts.push({ label, points, source });
  };

  const c = ctx.address.confidence;
  if (c < 0.8) add(`Address confidence ${c.toFixed(2)}`, (0.8 - c) * 95, "Address validation");
  add(
    `${ctx.address.pastFailuresAtAddress} recent address-related failures nearby`,
    Math.min(18, ctx.address.pastFailuresAtAddress * 7),
    "Delivery history",
  );
  if (ctx.address.firstDeliveryToAddress) add("First delivery to this address", 4, "Delivery history");

  const resolved = s.health === "recovered" || s.health === "prevented" || s.health === "recovering";
  const missed = ctx.recipient.missedWindows.length;
  if (missed > 0 && !resolved) add(`${missed} missed delivery window${missed > 1 ? "s" : ""}`, Math.min(44, missed * 19), "Attempt history");
  if (ctx.recipient.responsiveness === "low" && !resolved) add("Recipient rarely responds", 10, "Contact history");
  if (ctx.recipient.confirmedWindow) add("Recipient confirmed today's window", -9, "Contact history");

  if (s.exception && !resolved) add(`Recorded exception ${s.exception.code}`, 18, "Journey scans");
  if (s.movement.stationarySince && s.movement.mode === "route" && !resolved) {
    const min = Math.round((now - s.movement.stationarySince) / 60_000);
    if (min >= 10) add(`Vehicle stationary ${min} min`, 12, "Courier GPS");
  }
  if (s.flags.includes("code_conflict")) add("Exception conflicts with journey evidence", 8, "Evidence check");

  const t = ctx.telemetry;
  if (t.corridorSpeedKmh !== undefined && t.corridorTypicalKmh) {
    const ratio = t.corridorSpeedKmh / t.corridorTypicalKmh;
    if (ratio < 0.45) add(`Corridor speed ${t.corridorSpeedKmh} km/h vs ${t.corridorTypicalKmh} typical`, 24, "Route telemetry");
  }

  if (ctx.facility) {
    const hours = (now - ctx.facility.lastScanAt) / 3_600_000;
    if (hours > 4) add(`No scan for ${hours.toFixed(1)} h`, 30, "Facility scans");
    else if (hours > 1 && ctx.facility.backlogParcels) add("Waiting in branch sorting backlog", 26, "Facility scans");
  }
  if (ctx.custody?.conflictingScans) add("Conflicting custody scans", 30, "Journey scans");
  if (ctx.pickupPoint?.status === "offline") add("Assigned pickup point offline", 22, "Pickup network");

  const eta = estimateEta(s, now);
  if (eta && !s.closed) {
    const slack = (s.slaDeadline - eta) / 60_000;
    if (slack < 0) add(`ETA beyond SLA by ${Math.round(-slack)} min`, 26, "ETA estimate");
    else if (slack < 30) add("ETA within 30 min of SLA", 8, "ETA estimate");
  }
  if (s.service !== "Standard") add(`${s.service} service`, s.service === "Same-day" ? 6 : 3, "Order");
  if (s.payment.type === "COD") add("Cash on delivery", 3, "Order");

  const raw = 7 + parts.reduce((sum, p) => sum + p.points, 0);
  const score = Math.round(Math.max(3, Math.min(97, raw)));
  const drivers: RiskDriver[] = parts
    .sort((a, b) => Math.abs(b.points) - Math.abs(a.points))
    .slice(0, 5)
    .map((p) => ({
      label: p.label,
      effect: p.points >= 0 ? "raises" : "lowers",
      weight: Math.abs(p.points) >= 16 ? "strong" : Math.abs(p.points) >= 7 ? "moderate" : "weak",
      source: p.source,
    }));
  return { score, level: riskLevel(score), drivers, updatedAt: now, method: "prototype-heuristic" };
}

export function riskLevel(score: number): RiskLevel {
  if (score >= 80) return "critical";
  if (score >= 55) return "high";
  if (score >= 30) return "elevated";
  return "low";
}
