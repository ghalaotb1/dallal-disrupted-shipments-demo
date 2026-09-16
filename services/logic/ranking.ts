import { places } from "@/data/network";
import { fmtSar } from "@/lib/format";
import { fmtDuration } from "@/lib/time";
import type { ActionKind, DemoTime, Diagnosis, Level3, RecoveryAction, Shipment, ShipmentContext } from "@/types/domain";

/**
 * Transparent recovery ranking (blueprint §6). Every term is a rule, a stated
 * assumption, or a simulated input — it is never presented as an expected
 * value or a causal uplift.
 *
 *   score = 4·fit + 2·urgency + 1·(low impact) + 0.5·reversible
 */

type Candidate = Pick<RecoveryAction, "kind" | "title" | "reason" | "tool" | "fit" | "impact" | "reversible"> & {
  custodyChange?: boolean;
  slaChange?: boolean;
};

const PTS = { strong: 3, moderate: 2, weak: 1, high: 3, medium: 2, low: 1 } as const;

function urgencyOf(s: Shipment, now: DemoTime): Level3 {
  const slackMin = (s.slaDeadline - now) / 60_000;
  if (slackMin < 90 || s.health === "disrupted") return "high";
  if (slackMin < 240) return "medium";
  return "low";
}

function candidatesFor(s: Shipment, d: Diagnosis, ctx: ShipmentContext): Candidate[] {
  const cod = s.payment.type === "COD" ? s.payment.amountSar : 0;
  const nearestPickup = s.destination.city === "Dammam" ? places["pp-faisaliyah"] : places["pp-rawabi"];
  switch (d.cause) {
    case "address_issue":
      return [
        {
          kind: "verify_address",
          title: "Ask recipient to confirm location pin",
          reason: `National Address and pin disagree; recipient is responsive on ${ctx.recipient.preferredChannel}, so a confirmation request resolves it before the courier arrives.`,
          tool: "contact_recipient",
          fit: "strong",
          impact: "low",
          reversible: true,
        },
        {
          kind: "contact_recipient",
          title: "Courier calls recipient on approach",
          reason: "Resolves the address at the door, but only after the van has already arrived.",
          tool: "contact_recipient",
          fit: "moderate",
          impact: "low",
          reversible: true,
        },
        {
          kind: "redirect_pickup",
          title: `Redirect to ${nearestPickup.name}`,
          reason: "Avoids the address entirely but adds effort for the recipient.",
          tool: "redirect_to_pickup",
          fit: "weak",
          impact: "medium",
          reversible: true,
          custodyChange: true,
        },
      ];
    case "recipient_unavailable": {
      const repeated = ctx.recipient.missedWindows.length >= 2;
      const exhausted = s.attempts >= 3;
      return [
        {
          kind: "offer_window",
          title: "Offer evening window or pickup point",
          reason: exhausted
            ? "A fourth home attempt is unlikely to succeed after three misses."
            : repeated
              ? "Two daytime windows were missed; letting the recipient choose an evening slot or a nearby pickup point avoids a third failure."
              : "Recipient was not home; a new window chosen by the recipient is the lowest-effort recovery.",
          tool: "contact_recipient",
          fit: exhausted ? "moderate" : "strong",
          impact: "low",
          reversible: true,
        },
        {
          kind: "redirect_pickup",
          title: `Redirect to ${nearestPickup.name}`,
          reason: repeated ? "Breaks the missed-window pattern; recipient can collect any time within 7 days." : "Useful if the recipient cannot commit to a window.",
          tool: "redirect_to_pickup",
          fit: repeated ? "strong" : "moderate",
          impact: "medium",
          reversible: true,
          custodyChange: true,
        },
        {
          kind: "retry_delivery",
          title: "Retry in the same window tomorrow",
          reason: "Repeats the conditions that already failed.",
          tool: "reschedule_delivery",
          fit: "weak",
          impact: "low",
          reversible: true,
        },
      ];
    }
    case "attempt_not_completed":
      return [
        {
          kind: "reassign_courier",
          title: "Reassign to Khobar Branch courier (evening wave)",
          reason: "Recipient is available until the window closes; a local courier avoids the held corridor and keeps today's delivery.",
          tool: "reschedule_delivery",
          fit: "strong",
          impact: "high",
          reversible: false,
          custodyChange: true,
          slaChange: true,
        },
        {
          kind: "correct_exception",
          title: `Void recorded code ${s.exception?.code ?? ""} and flag attempt for review`,
          reason: "Keeps the recipient's record clean and protects exception-code data quality.",
          tool: "escalate_case",
          fit: "moderate",
          impact: "low",
          reversible: true,
        },
        {
          kind: "retry_delivery",
          title: "Retry today once the corridor clears",
          reason: "No custody change, but the window is likely to close first.",
          tool: "reschedule_delivery",
          fit: "moderate",
          impact: "low",
          reversible: true,
        },
        {
          kind: "contact_recipient",
          title: "Tell recipient about the delay and confirm availability",
          reason: `Recipient confirmed the window; a proactive update avoids a complaint${cod ? ` on a ${fmtSar(cod)} COD order` : ""}.`,
          tool: "contact_recipient",
          fit: "moderate",
          impact: "low",
          reversible: true,
        },
      ];
    case "route_disruption":
      return [
        {
          kind: "reroute",
          title: "Reroute via King Saud Rd (DK-07)",
          reason: "Avoids the congested segment; adds ~4 km.",
          tool: "reschedule_delivery",
          fit: "strong",
          impact: "medium",
          reversible: true,
        },
        {
          kind: "contact_recipient",
          title: "Send revised ETA to recipient",
          reason: "Sets expectations while the vehicle is delayed.",
          tool: "contact_recipient",
          fit: "moderate",
          impact: "low",
          reversible: true,
        },
      ];
    case "facility_backlog":
      return [
        {
          kind: "branch_escalation",
          title: "Prioritise in branch sort queue",
          reason: "Parcel has been waiting since arrival; branch can pull it forward for the next wave.",
          tool: "escalate_case",
          fit: "strong",
          impact: "medium",
          reversible: true,
        },
        {
          kind: "contact_recipient",
          title: "Notify recipient of 1-day delay",
          reason: "Protects experience if the backlog cannot clear today.",
          tool: "contact_recipient",
          fit: "moderate",
          impact: "low",
          reversible: true,
        },
      ];
    case "capacity_sequence":
      return [
        {
          kind: "resequence_stops",
          title: "Move parcel forward in the van's stop sequence",
          reason: "Meets the same-day promise; delays three Standard parcels by ~15 min, all still inside their windows.",
          tool: "reschedule_delivery",
          fit: "strong",
          impact: "medium",
          reversible: true,
        },
        {
          kind: "contact_recipient",
          title: "Offer a later window to recipient",
          reason: "Avoids breaching the promise if resequencing is declined.",
          tool: "contact_recipient",
          fit: "moderate",
          impact: "low",
          reversible: true,
        },
      ];
    case "pickup_point_unavailable":
      return [
        {
          kind: "redirect_pickup",
          title: "Redirect to Ar Rawabi Pickup Point",
          reason: "Nearest online pickup point with capacity.",
          tool: "redirect_to_pickup",
          fit: "strong",
          impact: "low",
          reversible: true,
          custodyChange: true,
        },
      ];
    case "custody_anomaly":
      return [
        {
          kind: "supervisor_escalation",
          title: "Escalate to shift supervisor for custody review",
          reason: "Evidence is contradictory and no known cause fits; a human must decide.",
          tool: "escalate_case",
          fit: "strong",
          impact: "medium",
          reversible: true,
        },
      ];
    default:
      return [];
  }
}

export function rankRecoveryActions(s: Shipment, d: Diagnosis, ctx: ShipmentContext, now: DemoTime): RecoveryAction[] {
  const urgency = urgencyOf(s, now);
  const cod = s.payment.type === "COD" ? s.payment.amountSar : 0;
  const slackLabel = s.slaDeadline > now ? `${fmtDuration(s.slaDeadline - now)} to SLA` : "SLA passed";

  return candidatesFor(s, d, ctx)
    .map((c) => {
      let approval: RecoveryAction["approval"] = "none";
      let approvalReason: string | undefined;
      if (c.impact === "high") {
        approval = "supervisor";
        approvalReason = "High operational impact";
      }
      if (c.custodyChange && cod >= 1000) {
        approval = "supervisor";
        approvalReason = `Custody change on ${fmtSar(cod)} COD`;
      }
      if (c.slaChange && approval === "supervisor") approvalReason = `${approvalReason} · changes committed courier & ETA`;
      if (approval === "none" && (c.kind === "resequence_stops" || c.kind === "branch_escalation" || c.kind === "correct_exception")) {
        approval = "analyst";
        approvalReason = "Affects other parcels or records";
      }
      if (approval === "none" && c.kind === "redirect_pickup" && s.attempts >= 3) {
        approval = "analyst";
        approvalReason = "Cancels the scheduled return to sender";
      }
      if (approval === "none" && c.kind === "redirect_pickup" && s.payment.type === "COD") {
        approval = "analyst";
        approvalReason = "COD collection moves to pickup point";
      }
      const score = PTS[c.fit] * 4 + PTS[urgency] * 2 + (4 - PTS[c.impact]) + (c.reversible ? 0.5 : 0);
      const action: RecoveryAction = {
        id: `${s.id}:${c.kind}`,
        kind: c.kind as ActionKind,
        title: c.title,
        reason: c.reason,
        tool: c.tool,
        rank: 0,
        fit: c.fit,
        urgency,
        impact: c.impact,
        reversible: c.reversible,
        approval,
        approvalReason,
        automatable: approval === "none" && c.reversible && d.confidence !== "low",
        factors: [
          { label: "Cause fit", value: c.fit, basis: "rule" },
          { label: "Urgency", value: `${urgency} · ${slackLabel}`, basis: "simulated" },
          { label: "Impact", value: c.impact, basis: "assumption" },
          { label: "Reversible", value: c.reversible ? "yes" : "no", basis: "rule" },
        ],
        score,
      };
      return action;
    })
    .sort((a, b) => b.score - a.score)
    .map((a, i) => ({ ...a, rank: i + 1 }));
}
