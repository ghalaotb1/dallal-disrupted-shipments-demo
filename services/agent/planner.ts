import { people } from "@/data/people";
import type { AgentMemory } from "@/services/agent/tools";
import type { AgentOutcome, Shipment, ShipmentContext, ToolName } from "@/types/domain";

/**
 * PROTOTYPE PLANNER — a deterministic policy that chooses the next tool from
 * what the agent has observed so far. It stands in for an LLM with function
 * calling: same tools, same trace format, different decision engine.
 * Different evidence produces different tool sequences.
 */
export function planNext(mem: AgentMemory, s: Shipment, ctx: ShipmentContext): ToolName | null {
  const did = (t: ToolName) => mem.called.includes(t);

  if (!did("get_shipment")) return "get_shipment";

  // Shipments already grouped into an incident are handled at incident level.
  if (s.incident && !did("check_incident_context")) return "check_incident_context";
  if (mem.incidentId) return null;

  const hasFailureHistory = !!s.exception || s.attempts > 0 || !!ctx.custody;
  if (hasFailureHistory && !did("get_journey")) return "get_journey";

  // Pre-failure cases start from the risk score, then follow its drivers.
  if (!s.exception && !did("predict_risk")) return "predict_risk";
  if (mem.addressLow && !did("get_address_context")) return "get_address_context";
  if (!s.exception && mem.risk?.drivers.some((d) => d.source === "ETA estimate") && !did("get_route_context")) return "get_route_context";

  if (!did("analyze_disruption")) return "analyze_disruption";

  const d = mem.diagnosis!;
  const routeRelevant = d.cause === "attempt_not_completed" || d.cause === "route_disruption" || d.cause === "custody_anomaly";
  if (routeRelevant && !did("get_route_context")) return "get_route_context";
  if ((mem.routeSlow || d.cause === "custody_anomaly") && !did("check_incident_context")) return "check_incident_context";
  if (mem.incidentId) return null;

  // Unknown patterns are never "solved" by ranking actions — hand to a human.
  if (d.agreement === "inconclusive") return null;

  if (!did("rank_recovery_actions")) return "rank_recovery_actions";
  const top = mem.actions?.[0];
  if (top && (top.approval !== "none" || top.automatable) && !did("retrieve_policy_constraints")) return "retrieve_policy_constraints";
  return null;
}

export function conclude(mem: AgentMemory, s: Shipment): AgentOutcome {
  if (mem.incidentId) {
    return {
      type: "incident",
      incidentId: mem.incidentId,
      headline: `Handle as part of ${mem.incidentId}`,
      rationale: "This failure shares a cause with other shipments. One incident response fixes it faster than individual cases.",
    };
  }
  const d = mem.diagnosis;
  if (d && d.agreement === "inconclusive") {
    return {
      type: "escalate",
      reason: "unknown_pattern",
      headline: "Escalate — no known cause fits the evidence",
      rationale: "The evidence contradicts itself and matches no known disruption pattern. The agent will not guess a cause or act on it.",
      question: "Was the parcel handed to the wrong recipient, or was the delivered scan made in error?",
    };
  }
  const top = mem.actions?.[0];
  if (!top || !d) {
    return { type: "resolved", headline: "No action needed", rationale: "Shipment is progressing normally; the agent will keep monitoring." };
  }
  if (top.approval === "supervisor") {
    return {
      type: "escalate",
      reason: d.agreement === "conflicts" ? "conflicting_evidence" : "high_impact",
      headline: `Escalate to ${people.supervisor.role.toLowerCase()} — approval needed`,
      rationale: `Top action “${top.title}” needs supervisor approval (${top.approvalReason}).${d.agreement === "conflicts" ? ` The recorded ${d.recorded?.code} code also conflicts with the evidence.` : ""}`,
      question: `Approve “${top.title}” for ${s.id}?`,
      actionId: top.id,
    };
  }
  if (top.automatable) {
    return {
      type: "auto_eligible",
      actionId: top.id,
      headline: `Eligible for automated action: ${top.title}`,
      rationale: `${d.causeLabel} (confidence ${d.confidence}). The action is low impact and reversible, so policy allows the agent to run it.`,
    };
  }
  return {
    type: "recommend",
    actionId: top.id,
    headline: `Recommended: ${top.title}`,
    rationale: `${d.causeLabel} (confidence ${d.confidence}). ${top.approvalReason ? `Needs your approval — ${top.approvalReason.toLowerCase()}.` : ""}`,
  };
}
