import type { Priority, Shipment } from "@/types/domain";

/** Queue priority: urgency of a human decision, not just model risk. */
export function computePriority(s: Shipment): Priority {
  if (s.closed || s.health === "delivered" || s.health === "prevented" || s.health === "recovered") return "P3";
  const valuable = s.service !== "Standard" || (s.payment.type === "COD" && s.payment.amountSar >= 1000);
  if (s.health === "review") return "P1";
  if (s.health === "disrupted" && (valuable || s.incident?.role === "affected" || s.risk.level === "critical")) return "P1";
  if (s.health === "disrupted" || s.risk.level === "high" || s.risk.level === "critical") return "P2";
  if (s.health === "at_risk") return "P2";
  return "P3";
}

const HEALTH_ORDER: Record<Shipment["health"], number> = {
  review: 0,
  disrupted: 1,
  at_risk: 2,
  recovering: 3,
  on_track: 4,
  recovered: 5,
  prevented: 6,
  delivered: 7,
};

export function compareByPriority(a: Shipment, b: Shipment) {
  return (
    a.priority.localeCompare(b.priority) ||
    HEALTH_ORDER[a.health] - HEALTH_ORDER[b.health] ||
    b.risk.score - a.risk.score ||
    a.slaDeadline - b.slaDeadline
  );
}
