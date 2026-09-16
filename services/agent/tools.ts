import { corridorBaselines } from "@/data/scenario/seedIncidents";
import { corridors, places } from "@/data/network";
import { people } from "@/data/people";
import { fmtSar } from "@/lib/format";
import { fmtDuration, fmtTime, fmtWindow } from "@/lib/time";
import { analyzeDisruption } from "@/services/logic/diagnosis";
import { evaluateCorridor, type CorridorEvaluation } from "@/services/logic/incidentDetector";
import { rankRecoveryActions } from "@/services/logic/ranking";
import { assessRisk } from "@/services/logic/risk";
import type {
  AgentStep,
  DemoTime,
  Diagnosis,
  Incident,
  JourneyEvent,
  RecoveryAction,
  RiskAssessment,
  Shipment,
  ShipmentContext,
  ToolName,
} from "@/types/domain";

/**
 * Agent tools. Read tools fetch case data, analysis tools run Dallal's
 * deterministic logic, action tools only ever touch the demo environment.
 * Tools return facts; the agent never invents numbers.
 */

export interface ToolWorld {
  shipments: Record<string, Shipment>;
  journeys: Record<string, JourneyEvent[]>;
  contexts: Record<string, ShipmentContext>;
  incidents: Record<string, Incident>;
}

export interface AgentMemory {
  called: ToolName[];
  risk?: RiskAssessment;
  addressLow?: boolean;
  routeSlow?: boolean;
  diagnosis?: Diagnosis;
  incidentId?: string;
  evaluation?: CorridorEvaluation;
  actions?: RecoveryAction[];
  policy?: { approval: RecoveryAction["approval"]; reason?: string; automatable: boolean };
}

export interface ToolOutput {
  status: AgentStep["status"];
  summary: string;
  facts: string[];
}

export const TOOL_META: Record<ToolName, { kind: AgentStep["kind"]; durationMs: number }> = {
  get_shipment: { kind: "read", durationMs: 650 },
  get_journey: { kind: "read", durationMs: 950 },
  get_address_context: { kind: "read", durationMs: 1050 },
  get_route_context: { kind: "read", durationMs: 1150 },
  predict_risk: { kind: "analysis", durationMs: 1100 },
  analyze_disruption: { kind: "analysis", durationMs: 1350 },
  check_incident_context: { kind: "analysis", durationMs: 1050 },
  rank_recovery_actions: { kind: "analysis", durationMs: 1000 },
  retrieve_policy_constraints: { kind: "read", durationMs: 750 },
  contact_recipient: { kind: "action", durationMs: 1200 },
  reschedule_delivery: { kind: "action", durationMs: 1100 },
  redirect_to_pickup: { kind: "action", durationMs: 1100 },
  escalate_case: { kind: "action", durationMs: 900 },
};

export function describeTool(tool: ToolName, s: Shipment): { args: string; checking: string } {
  switch (tool) {
    case "get_shipment":
      return { args: `id="${s.id}"`, checking: "Reading shipment record, service level and delivery promise" };
    case "get_journey":
      return { args: `id="${s.id}"`, checking: "Reading scans, delivery attempts and courier events" };
    case "get_address_context":
      return { args: `id="${s.id}"`, checking: "Checking National Address, customer pin and delivery history" };
    case "get_route_context":
      return { args: `corridor="${s.corridorId}"`, checking: "Reading corridor telemetry and vehicle movement" };
    case "predict_risk":
      return { args: `id="${s.id}"`, checking: "Scoring failure risk from current signals" };
    case "analyze_disruption":
      return { args: `id="${s.id}"`, checking: "Comparing recorded exception with independent evidence" };
    case "check_incident_context":
      return { args: `corridor="${s.corridorId}", window="30m"`, checking: "Looking for related failures across shipments" };
    case "rank_recovery_actions":
      return { args: `id="${s.id}"`, checking: "Scoring eligible recovery actions" };
    case "retrieve_policy_constraints":
      return { args: `action="top"`, checking: "Checking approval and automation policy" };
    case "contact_recipient":
      return { args: `channel="WhatsApp"`, checking: "Sending message to recipient" };
    case "reschedule_delivery":
      return { args: `id="${s.id}"`, checking: "Updating delivery plan" };
    case "redirect_to_pickup":
      return { args: `id="${s.id}"`, checking: "Redirecting parcel to pickup point" };
    case "escalate_case":
      return { args: `to="shift_supervisor"`, checking: "Opening escalation for human review" };
  }
}

const corridorPeers = (w: ToolWorld, s: Shipment) => Object.values(w.shipments).filter((p) => p.corridorId === s.corridorId && !p.closed);

export function runReadOrAnalysisTool(tool: ToolName, w: ToolWorld, s: Shipment, now: DemoTime, mem: AgentMemory): ToolOutput {
  const ctx = w.contexts[s.id];
  const journey = w.journeys[s.id] ?? [];
  mem.called.push(tool);

  switch (tool) {
    case "get_shipment": {
      const pay = s.payment.type === "COD" ? `COD ${fmtSar(s.payment.amountSar)}` : "Prepaid";
      return {
        status: "ok",
        summary: `${s.service} · ${pay} · ${places[s.originId].short} → ${s.destination.label}`,
        facts: [
          s.courier ? `Van ${s.courier.vehicle} · courier ${s.courier.id}` : "Not yet assigned to a van",
          `Window ${fmtWindow(s.window)} · SLA ${fmtTime(s.slaDeadline)}`,
        ],
      };
    }
    case "get_journey": {
      const failures = journey.filter((e) => e.tone === "crit");
      const last = [...journey].reverse().find((e) => e.tone === "crit" || e.tone === "warn");
      const facts = failures.slice(-3).map((e) => `${fmtTime(e.at)} · ${e.title}${e.detail ? ` — ${e.detail}` : ""}`);
      if (ctx.custody?.conflictingScans) facts.push("Sequence anomaly: “Delivered” followed by “Out for delivery”");
      if (ctx.recipient.confirmedWindow) facts.push(`Recipient confirmed ${fmtWindow(ctx.recipient.confirmedWindow)} at ${fmtTime(ctx.recipient.confirmedWindow.at)}`);
      return {
        status: ctx.custody?.conflictingScans ? "alert" : failures.length ? "warn" : "ok",
        summary: `${journey.length} events · ${failures.length ? `${failures.length} failure event${failures.length > 1 ? "s" : ""}` : "no failures"}${last && !failures.length ? ` · ${last.title}` : ""}`,
        facts: facts.length ? facts : ["Journey follows the expected scan sequence"],
      };
    }
    case "get_address_context": {
      const a = ctx.address;
      mem.addressLow = a.confidence < 0.6;
      const failing = a.checks.filter((c) => c.result !== "pass");
      return {
        status: a.confidence < 0.5 ? "alert" : a.confidence < 0.8 ? "warn" : "ok",
        summary: `Address confidence ${a.confidence.toFixed(2)} — ${a.confidence < 0.5 ? "low" : a.confidence < 0.8 ? "moderate" : "good"}`,
        facts: [
          ...failing.map((c) => `${c.label}: ${c.detail}`),
          ...(a.pastFailuresAtAddress ? [`${a.pastFailuresAtAddress} address-related failures on this street (30 days)`] : []),
        ].slice(0, 3),
      };
    }
    case "get_route_context": {
      const t = ctx.telemetry;
      const peers = corridorPeers(w, s).filter((p) => p.id !== s.id && (p.health === "disrupted" || p.exception));
      const slow = t.corridorSpeedKmh !== undefined && !!t.corridorTypicalKmh && t.corridorSpeedKmh / t.corridorTypicalKmh < 0.45;
      mem.routeSlow = slow;
      const corridor = corridors[s.corridorId];
      if (t.corridorSpeedKmh === undefined) {
        return { status: "ok", summary: `${corridor.code} · ${corridor.name}: traffic normal`, facts: ["No slowdown on corridor", `${peers.length} other open exceptions on corridor`] };
      }
      return {
        status: slow ? "alert" : "ok",
        summary: `${corridor.name}: ${t.corridorSpeedKmh} km/h vs ${t.corridorTypicalKmh} km/h typical`,
        facts: [
          ...(s.movement.stationarySince ? [`Vehicle stationary ${fmtDuration(now - s.movement.stationarySince)}`] : []),
          `${peers.length} other shipment${peers.length === 1 ? "" : "s"} on ${corridor.code} with open exceptions`,
        ],
      };
    }
    case "predict_risk": {
      const risk = assessRisk(s, ctx, now);
      mem.risk = risk;
      if (risk.drivers.some((d) => d.label.startsWith("Address"))) mem.addressLow = true;
      return {
        status: risk.level === "critical" || risk.level === "high" ? "alert" : risk.level === "elevated" ? "warn" : "ok",
        summary: `Risk ${risk.score} · ${risk.level} (prototype heuristic)`,
        facts: risk.drivers.slice(0, 3).map((d) => `${d.effect === "raises" ? "↑" : "↓"} ${d.label}`),
      };
    }
    case "analyze_disruption": {
      const d = analyzeDisruption({ shipment: s, context: ctx, now, corridorPeers: corridorPeers(w, s) });
      mem.diagnosis = d;
      const agreement =
        d.agreement === "conflicts"
          ? `Conflicts with recorded ${d.recorded?.code}`
          : d.agreement === "agrees"
            ? `Agrees with recorded ${d.recorded?.code}`
            : d.agreement === "inconclusive"
              ? "Inconclusive — no known pattern"
              : "No exception recorded yet";
      return {
        status: d.agreement === "conflicts" || d.agreement === "inconclusive" ? "alert" : d.cause === "none" ? "ok" : "warn",
        summary: d.headline,
        facts: [agreement, `Likely cause: ${d.causeLabel} · confidence ${d.confidence}`],
      };
    }
    case "check_incident_context": {
      const active = Object.values(w.incidents).find((i) => i.status !== "resolved" && (i.affected.includes(s.id) || i.exposed.includes(s.id)));
      if (active) {
        mem.incidentId = active.id;
        return {
          status: "alert",
          summary: `Part of ${active.id} · ${active.title}`,
          facts: [`${active.affected.length} affected · ${active.exposed.length} exposed`, "Handle at incident level instead of case by case"],
        };
      }
      const baseline = corridorBaselines[s.corridorId];
      if (!baseline) return { status: "ok", summary: "No related incidents", facts: ["No other shipments show this pattern"] };
      const ev = evaluateCorridor(s.corridorId, Object.values(w.shipments), now, baseline);
      mem.evaluation = ev;
      const related = ev.members.filter((id) => id !== s.id);
      return {
        status: related.length ? "warn" : "ok",
        summary: related.length
          ? `${related.length} related failure${related.length > 1 ? "s" : ""} on ${s.corridorId} · below incident threshold`
          : `No related failures on ${s.corridorId}`,
        facts: [`${ev.observed} in last 30 min vs baseline ${ev.mean.toFixed(1)} ± ${ev.std.toFixed(1)} · z = ${ev.z.toFixed(1)} (threshold 3.0)`, ...(related.length ? [related.join(", ")] : [])],
      };
    }
    case "rank_recovery_actions": {
      const d = mem.diagnosis ?? analyzeDisruption({ shipment: s, context: ctx, now, corridorPeers: corridorPeers(w, s) });
      mem.diagnosis = d;
      const actions = rankRecoveryActions(s, d, ctx, now);
      mem.actions = actions;
      const top = actions[0];
      return {
        status: "ok",
        summary: top ? `Top action: ${top.title}` : "No eligible actions",
        facts: actions.slice(0, 3).map((a) => `#${a.rank} ${a.title}${a.approval === "supervisor" ? " · needs supervisor" : a.approval === "analyst" ? " · needs analyst" : ""}`),
      };
    }
    case "retrieve_policy_constraints": {
      const top = mem.actions?.[0];
      if (!top) return { status: "ok", summary: "No action to check", facts: [] };
      mem.policy = { approval: top.approval, reason: top.approvalReason, automatable: top.automatable };
      if (top.approval === "supervisor")
        return { status: "warn", summary: "Supervisor approval required", facts: [top.approvalReason ?? "High-impact action", `Route to ${people.supervisor.name} (${people.supervisor.role})`] };
      if (top.approval === "analyst") return { status: "warn", summary: "Analyst approval required", facts: [top.approvalReason ?? "Affects other parcels"] };
      return { status: "ok", summary: "Automated action allowed", facts: ["Low impact · reversible · confidence sufficient"] };
    }
    default:
      return { status: "ok", summary: "", facts: [] };
  }
}
