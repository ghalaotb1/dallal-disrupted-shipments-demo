import { corridors, places } from "@/data/network";
import { plural, fmtSar } from "@/lib/format";
import { fmtDuration, fmtTime, fmtWindow } from "@/lib/time";
import type { EscalationInput } from "@/services/contracts";
import type { AgentRun, DemoTime, Incident, Shipment, ToolName } from "@/types/domain";

/** Human-readable names for what each tool checked (used in escalations and emails). */
export const TOOL_LABEL: Record<ToolName, string> = {
  get_shipment: "Shipment record & delivery promise",
  get_journey: "Journey scans & delivery attempts",
  get_address_context: "National Address & customer pin",
  get_route_context: "Corridor telemetry & vehicle movement",
  predict_risk: "Failure risk score (prototype heuristic)",
  analyze_disruption: "Recorded code vs. independent evidence",
  check_incident_context: "Related failures across shipments",
  rank_recovery_actions: "Eligible recovery actions",
  retrieve_policy_constraints: "Approval & automation policy",
  contact_recipient: "Recipient contact",
  reschedule_delivery: "Delivery plan update",
  redirect_to_pickup: "Pickup point redirect",
  escalate_case: "Escalation",
};

export interface EscalationDraft extends EscalationInput {
  title: string;
  urgency: string;
  location: string;
}

export function draftForShipment(s: Shipment, run: AgentRun | undefined, now: DemoTime): EscalationDraft {
  const outcome = run?.outcome;
  const d = run?.diagnosis;
  const actions = run?.actions ?? [];
  const top = outcome && "actionId" in outcome ? actions.find((a) => a.id === outcome.actionId) : actions[0];
  const slaLeft = s.slaDeadline - now;
  const pay = s.payment.type === "COD" ? ` · COD ${fmtSar(s.payment.amountSar)}` : "";

  return {
    title: `Escalate ${s.id} to shift supervisor`,
    target: { type: "shipment", id: s.id },
    priority: s.priority,
    reason: outcome?.type === "escalate" ? outcome.rationale : d ? `${d.headline}. Human review requested by the analyst.` : "Analyst requested supervisor review.",
    question: outcome?.type === "escalate" ? outcome.question : top ? `Approve “${top.title}” for ${s.id}?` : `How should ${s.id} be handled?`,
    options: [...actions.slice(0, 3).map((a) => `${a.title}${a.approval === "supervisor" ? " (needs your approval)" : ""}`), "Hold and review manually"],
    checks: run ? [...new Set(run.steps.map((st) => TOOL_LABEL[st.tool]))] : ["No agent investigation yet"],
    evidence: d ? d.evidence.filter((e) => e.stance !== "context").slice(0, 4).map((e) => `${e.label} — ${e.detail}`) : s.headline ? [s.headline] : [],
    recommendation: top ? `${top.title}. ${top.reason}` : "Review the case and decide the recovery path.",
    summary: [
      { label: "Shipment", value: `${s.id} · ${s.merchant} · ${s.service}${pay}` },
      { label: "Route", value: `${places[s.originId].short} → ${s.destination.label} (${corridors[s.corridorId].code})` },
      { label: "Priority", value: `${s.priority} · SLA ${fmtTime(s.slaDeadline)} (${slaLeft > 0 ? `in ${fmtDuration(slaLeft)}` : "passed"})` },
      { label: "Diagnosis", value: d ? `${d.causeLabel} · confidence ${d.confidence}${d.agreement === "conflicts" ? ` · conflicts with ${d.recorded?.code}` : ""}` : "Not investigated" },
    ],
    urgency: slaLeft > 0 ? `SLA ${fmtTime(s.slaDeadline)} · ${fmtDuration(slaLeft)} left · window ${fmtWindow(s.window)}` : `SLA passed at ${fmtTime(s.slaDeadline)}`,
    location: s.movement.mode === "facility" ? `At ${places[s.movement.facilityId!].name}` : `En route on ${corridors[s.corridorId].name} to ${s.destination.label}`,
  };
}

export function draftForIncident(inc: Incident, shipments: Record<string, Shipment>, now: DemoTime): EscalationDraft {
  const members = [...inc.affected, ...inc.exposed].map((id) => shipments[id]).filter(Boolean);
  const earliest = members.reduce<number | null>((min, s) => (min === null || s.slaDeadline < min ? s.slaDeadline : min), null);
  return {
    title: `Send ${inc.id} to shift supervisor`,
    target: { type: "incident", id: inc.id },
    priority: inc.severity === "critical" || inc.severity === "high" ? "P1" : "P2",
    reason: `${plural(inc.affected.length, "shipment failure")} share one cause (${inc.sharedFactor.label}); ${plural(inc.exposed.length, "more shipment")} exposed. The group response needs supervisor approval.`,
    question: `Approve the group response for ${inc.id}: ${inc.response.summary.toLowerCase()}?`,
    options: ["Approve group response as proposed", "Hold exposed departures only", "Assign a field lead to the corridor"],
    checks: ["Incident detector (rolling baseline)", "Corridor telemetry", "Journey scans for every member", "Recorded codes vs. GPS evidence"],
    evidence: inc.signals.map((sig) => `${sig.label}: ${sig.value} — ${sig.detail}`).slice(0, 4),
    recommendation: `Apply the group response: ${inc.response.summary}.`,
    summary: [
      { label: "Incident", value: `${inc.id} · ${inc.title} · ${inc.severity}` },
      { label: "Shared factor", value: inc.sharedFactor.label },
      { label: "Shipments", value: `${inc.affected.length} affected · ${inc.exposed.length} exposed` },
      { label: "Detector", value: `${inc.detector.observed} failures vs baseline ${inc.detector.baselineMean.toFixed(1)} (z = ${inc.detector.z.toFixed(1)})` },
    ],
    urgency: earliest ? `Earliest SLA among members ${fmtTime(earliest)} · ${earliest > now ? `${fmtDuration(earliest - now)} left` : "passed"}` : "—",
    location: inc.sharedFactor.label,
  };
}
