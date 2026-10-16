import { getRoute } from "@/data/network";
import { people } from "@/data/people";
import { plural } from "@/lib/format";
import { addEvent, addLedger, notify, rescore, setHealth } from "@/services/demo/mutations";
import { anchorMovement } from "@/services/logic/movement";
import { demoNow, updateWorld } from "@/store/world";
import type { ResponseStep } from "@/types/domain";
import type { LivePlan } from "@/types/live";

const applied = new Set<string>();

/**
 * Writes an executed coordinated plan into the shared world (shipment journeys, health, incident timeline, ledger) so every screen shows
 * the same state. The backend has already recorded the decisions in its ledger; the movement of parcels remains simulated.
 * Idempotent per plan id (the executor and the event feed can both call it).
 */
export function applyPlanToWorld(incidentId: string, plan: LivePlan, approvedBy: string = people.supervisor.name): void {
  if (plan.status !== "executed_simulated" || applied.has(plan.plan_id)) return;
  applied.add(plan.plan_id);
  updateWorld((d) => {
    const inc = d.incidents[incidentId];
    if (!inc) return;
    const now = demoNow();
    const counts: Record<string, number> = {};
    for (const [pid, { option, text }] of Object.entries(plan.solution.per_parcel)) {
      const s = d.shipments[pid];
      if (!s) continue;
      const kind = option.split(":")[0];
      counts[kind] = (counts[kind] ?? 0) + 1;
      const base = { at: now, detail: `Coordinated plan ${plan.plan_id} · approved by ${approvedBy}`, source: "supervisor" as const, tone: "ok" as const };
      if (kind === "reroute" && s.altRouteKey && getRoute(s.altRouteKey)) {
        s.routeKey = s.altRouteKey;
        s.corridorId = "DK-07";
        s.movement = { mode: "route", distanceM: 0, speedMps: 10.4, updatedAt: now };
        setHealth(d, pid, "recovering");
        s.headline = "Rerouted via King Saud Rd (DK-07)";
        addEvent(d, pid, { ...base, title: "Rerouted around the blockage" });
      } else if (kind === "wait" || kind === "reroute") {
        s.movement = anchorMovement(s, now);
        s.movement.holdAtM = undefined;
        s.movement.speedMps = 4.2;
        s.movement.stationarySince = undefined;
        setHealth(d, pid, "recovering");
        s.headline = "Resuming through the managed lane";
        addEvent(d, pid, { ...base, title: "Van holds on route and resumes when the lane opens" });
      } else if (kind === "spare") {
        setHealth(d, pid, "recovering");
        s.headline = `Reassigned to spare courier ${option.split(":")[1]}`;
        addEvent(d, pid, { ...base, title: text });
      } else if (kind === "pickup") {
        setHealth(d, pid, "recovering");
        s.headline = `Redirected to pickup point ${option.split(":")[1]}`;
        addEvent(d, pid, { ...base, title: text });
      } else {
        s.headline = "Planned deferral with notice to the recipient";
        addEvent(d, pid, { ...base, tone: "review", title: "Deferred with notice (no capacity to recover on time)" });
      }
      s.agent = { ...s.agent, state: "acting", headline: `Recovering under coordinated plan for ${incidentId}`, updatedAt: now };
      rescore(d, pid, now);
    }
    // The incident's response card must show what was actually decided, not the generic demo steps.
    const groups: Record<string, { title: string; detail: string; tool: string; shipments: string[] }> = {};
    for (const [pid, { option, text }] of Object.entries(plan.solution.per_parcel)) {
      const kind = option;
      const g = (groups[kind] ??= {
        title: text,
        detail: kind === "wait" ? "Van holds on its route and resumes when the lane opens" : kind === "defer" ? "No capacity can recover these on time: notice sent, delivery re-planned" : "Chosen jointly with the other shipments, within shared capacity",
        tool: kind.startsWith("spare:") ? "reassign_courier" : kind.startsWith("pickup:") ? "contact_recipient" : "reschedule_delivery",
        shipments: [],
      });
      g.shipments.push(pid);
    }
    inc.response.steps = Object.entries(groups).map(([k, g]) => ({ id: k, title: g.title, detail: g.detail, shipments: g.shipments, tool: g.tool }));
    inc.response.summary = `Coordinated plan (backend): ${Object.entries(counts).map(([k, n]) => `${n} ${k}`).join(", ")}`;
    inc.response.state = "applied";
    inc.response.appliedAt = now;
    inc.response.approvedBy = approvedBy;
    inc.status = "mitigating";
    const summary = Object.entries(counts).map(([k, n]) => `${n} ${k}`).join(" · ");
    inc.timeline.push({ id: `IE-${plan.plan_id}`, at: now, title: "Coordinated recovery plan executed (simulated)", detail: summary, tone: "ok", actor: approvedBy });
    addLedger(d, { at: now, incidentId, decision: `Coordinated plan · ${plural(Object.keys(plan.solution.per_parcel).length, "shipment")} (${summary})`, decidedBy: "Shift supervisor", basis: "Joint optimisation, backend plan " + plan.plan_id, outcome: "pending" });
    notify(d, { at: now, kind: "outcome", tone: "ok", title: `Coordinated plan applied · ${incidentId}`, body: summary, target: { type: "incident", id: incidentId }, actor: approvedBy });
  });
}
