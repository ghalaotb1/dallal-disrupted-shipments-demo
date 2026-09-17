import { corridors, DK04_BLOCKAGE, getRoute } from "@/data/network";
import { people } from "@/data/people";
import { baselineLabels, corridorBaselines } from "@/data/scenario/seedIncidents";
import { plural } from "@/lib/format";
import { fmtTime } from "@/lib/time";
import { addEvent, addLedger, completeStep, notify, rescore, setHealth } from "@/services/demo/mutations";
import { evaluateCorridor, findExposed } from "@/services/logic/incidentDetector";
import { anchorMovement } from "@/services/logic/movement";
import { demoNow, getWorld, nextId, updateWorld, type WorldState } from "@/store/world";
import { pushToast } from "@/store/ui";
import type { IncidentService } from "@/services/contracts";
import type { Incident, ResponseStep } from "@/types/domain";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function buildResponseSteps(w: Pick<WorldState, "shipments">, affected: string[], exposed: string[]): ResponseStep[] {
  const conflicts = affected.filter((id) => w.shipments[id]?.flags.includes("code_conflict"));
  return [
    { id: "reroute", title: "Reroute exposed shipments via King Saud Rd (DK-07)", detail: "Departing vans avoid the closed segment · +4–6 km", shipments: exposed, tool: "reschedule_delivery" },
    { id: "resume", title: "Resume held vans through the managed lane", detail: "Traffic control opened one lane · reduced speed", shipments: affected, tool: "reschedule_delivery" },
    { id: "notify", title: "Send revised ETAs to recipients", detail: "WhatsApp / SMS with new delivery estimate", shipments: [...affected, ...exposed], tool: "contact_recipient" },
    ...(conflicts.length
      ? [{ id: "codes", title: "Void conflicting RNA codes for review", detail: "Codes contradicted by GPS evidence", shipments: conflicts, tool: "escalate_case" }]
      : []),
  ];
}

function markMember(d: WorldState, incidentId: string, id: string, role: "affected" | "exposed") {
  const s = d.shipments[id];
  if (!s) return;
  const now = demoNow();
  s.incident = { id: incidentId, role };
  if (role === "exposed") {
    if (!s.flags.includes("exposed")) s.flags.push("exposed");
    if (s.health === "on_track") setHealth(d, id, "at_risk");
    s.headline = "Exposed — planned route crosses incident zone";
  }
  if (s.agent.state !== "awaiting_supervisor") {
    s.agent = { ...s.agent, state: "incident", headline: `Handled at incident level · ${incidentId}`, updatedAt: now };
  }
  addEvent(d, id, {
    at: now,
    title: role === "affected" ? `Grouped into incident ${incidentId}` : `Exposed to incident ${incidentId}`,
    detail: role === "affected" ? "Shared cause detected across shipments on DK-04" : "Planned route crosses the incident zone",
    source: "system",
    tone: role === "affected" ? "crit" : "warn",
  });
  rescore(d, id, now);
}

export const demoIncidentService: IncidentService = {
  async list() {
    return Object.values(getWorld().incidents);
  },
  async get(id) {
    return getWorld().incidents[id];
  },

  detect(corridorId) {
    const w = getWorld();
    const existing = Object.values(w.incidents).find((i) => i.sharedFactor.corridorId === corridorId && i.status !== "resolved");
    if (existing) return existing;
    const now = demoNow();
    const baseline = corridorBaselines[corridorId];
    const ev = evaluateCorridor(corridorId, Object.values(w.shipments), now, baseline);
    if (!ev.triggered) return null;

    const affected = ev.members;
    const exposed = findExposed(Object.values(w.shipments), corridorId, affected, now);
    const id = "INC-2417";
    const corridor = corridors[corridorId];
    const conflicts = affected.filter((sid) => w.shipments[sid].flags.includes("code_conflict")).length;
    const firstAt = Math.min(...affected.map((sid) => w.shipments[sid].exception?.recordedAt ?? now));

    const incident: Incident = {
      id,
      kind: "route",
      title: `Route ${corridor.code} disruption`,
      subtitle: DK04_BLOCKAGE.label,
      severity: affected.length >= 6 ? "critical" : "high",
      status: "active",
      detectedAt: now,
      sharedFactor: {
        label: DK04_BLOCKAGE.label,
        detail: "Corridor speed 7 km/h vs 52 km/h typical · lane closure reported (simulated)",
        coord: DK04_BLOCKAGE.coord,
        radiusM: DK04_BLOCKAGE.radiusM,
        corridorId,
        segment: DK04_BLOCKAGE.segment,
      },
      signals: [
        { label: "Same corridor", value: `${corridor.code} · ${corridor.name}`, detail: `All ${affected.length} failures on vans routed via ${corridor.name}` },
        { label: "Same time window", value: now - firstAt < 2 * 60_000 ? "Last 30 min" : `${fmtTime(firstAt)}–${fmtTime(now)}`, detail: "Failures clustered inside one detector window" },
        { label: "Same pattern", value: "Vans stationary > 20 min", detail: "Held before the Ar Rakah segment" },
        { label: "Corridor speed", value: "7 km/h", detail: "52 km/h typical at this hour" },
        ...(conflicts ? [{ label: "Code conflicts", value: String(conflicts), detail: "RNA codes contradicted by GPS — symptoms, not causes" }] : []),
      ],
      detector: {
        method: "Rolling baseline z-score · failures per corridor",
        window: "30 min",
        baselineMean: ev.mean,
        baselineStd: ev.std,
        observed: ev.observed,
        z: ev.z,
        threshold: 3,
        series: [...baseline.map((count, i) => ({ label: baselineLabels[i], count })), { label: "Now", count: ev.observed, current: true }],
      },
      affected,
      exposed,
      owner: { name: people.supervisor.name, role: people.supervisor.role },
      response: {
        state: "proposed",
        summary: `Reroute ${plural(exposed.length, "exposed shipment")}, resume ${plural(affected.length, "held van")}, notify ${affected.length + exposed.length} recipients`,
        steps: buildResponseSteps(w, affected, exposed),
        approvalRequired: true,
      },
      timeline: [
        { id: nextId("IE"), at: firstAt, title: "First failure on corridor", detail: w.shipments[affected[0]]?.exception?.label, tone: "warn", actor: "Journey scans" },
        { id: nextId("IE"), at: now, title: "Incident detected", detail: `${ev.observed} failures vs baseline ${ev.mean.toFixed(1)} ± ${ev.std.toFixed(1)} · z = ${ev.z.toFixed(1)}`, tone: "crit", actor: "Incident detector" },
        { id: nextId("IE"), at: now, title: `${affected.length} alerts consolidated into one incident`, detail: `${exposed.length} more shipments exposed`, tone: "info", actor: "Dallal" },
      ],
      simulatedCause: "Lane closure after a collision on King Fahd Rd (simulated scenario)",
    };

    updateWorld((d) => {
      d.incidents[id] = incident;
      affected.forEach((sid) => markMember(d, id, sid, "affected"));
      exposed.forEach((sid) => markMember(d, id, sid, "exposed"));
      // Individual alerts for these shipments are now represented by the incident.
      d.notifications.forEach((n) => {
        if (n.target.type === "shipment" && affected.includes(n.target.id) && n.kind === "risk") n.read = true;
      });
      notify(d, {
        at: now,
        kind: "incident",
        tone: "crit",
        title: `New route incident · ${corridor.code} ${corridor.name}`,
        body: `${plural(affected.length, "failure")} grouped into ${id} · ${exposed.length} more exposed`,
        target: { type: "incident", id },
        actor: "Incident detector",
      });
      completeStep(d, "incident");
    });
    pushToast({ tone: "crit", title: "1 operational incident detected", body: `${affected.length} failures on ${corridor.code} grouped · ${exposed.length} exposed`, href: `/incidents/${id}`, actionLabel: "Open incident" });
    return getWorld().incidents[id];
  },

  async applyGroupResponse(id, onProgress) {
    const inc = getWorld().incidents[id];
    if (!inc || inc.response.state === "applied") return;
    updateWorld((d) => {
      d.incidents[id].response.state = "awaiting_approval";
      d.incidents[id].timeline.push({ id: nextId("IE"), at: demoNow(), title: `Approval requested from ${people.supervisor.name}`, tone: "review", actor: people.analyst.name });
      d.scenario.holdUntilReal = Date.now() + 60_000;
    });
    onProgress?.({ stage: "approval_requested" });
    await sleep(2600);
    updateWorld((d) => {
      const i = d.incidents[id];
      i.response.state = "approved";
      i.response.approvedBy = people.supervisor.name;
      i.timeline.push({ id: nextId("IE"), at: demoNow(), title: "Group response approved", detail: "Simulated supervisor response", tone: "ok", actor: people.supervisor.name });
      notify(d, { at: demoNow(), kind: "approval", tone: "ok", title: `Supervisor approved group response · ${id}`, body: i.response.summary, target: { type: "incident", id }, actor: people.supervisor.name });
    });
    onProgress?.({ stage: "approved", by: people.supervisor.name });

    for (const st of getWorld().incidents[id].response.steps) {
      onProgress?.({ stage: "step_started", stepId: st.id });
      await sleep(1100);
      updateWorld((d) => {
        const now = demoNow();
        for (const sid of st.shipments) {
          const s = d.shipments[sid];
          if (!s) continue;
          if (st.id === "reroute" && s.altRouteKey && getRoute(s.altRouteKey)) {
            s.routeKey = s.altRouteKey;
            s.corridorId = "DK-07";
            s.movement = { mode: "route", distanceM: 0, speedMps: 10.4, updatedAt: now };
            s.stage = "out_for_delivery";
            setHealth(d, sid, "recovering");
            s.headline = "Rerouted via King Saud Rd (DK-07)";
            addEvent(d, sid, { at: now, title: "Rerouted via King Saud Rd (DK-07)", detail: `Group response ${id} · approved by ${people.supervisor.name}`, source: "supervisor", tone: "ok", location: "DMM Hub" });
          }
          if (st.id === "resume" || (st.id === "reroute" && !s.altRouteKey)) {
            s.movement = anchorMovement(s, now);
            s.movement.holdAtM = undefined;
            s.movement.speedMps = 4.2;
            s.movement.stationarySince = undefined;
            setHealth(d, sid, "recovering");
            s.headline = "Resuming via managed lane · revised ETA";
            s.agent = { ...s.agent, state: "acting", headline: `Recovering under ${id} response`, updatedAt: now };
            addEvent(d, sid, { at: now, title: "Van resuming via managed lane", detail: `Group response ${id}`, source: "supervisor", tone: "ok" });
          }
          if (st.id === "notify") addEvent(d, sid, { at: now, title: "Revised ETA sent to recipient", detail: "contact_recipient() · group response", source: "agent", tone: "agent" });
          if (st.id === "codes") {
            addEvent(d, sid, { at: now, title: "Recorded RNA code voided for review", detail: "Contradicted by GPS evidence", source: "system", tone: "review" });
            if (s.exception) s.exception = { ...s.exception, label: `${s.exception.label} (voided — under review)` };
          }
          rescore(d, sid, now);
        }
      });
      onProgress?.({ stage: "step_done", stepId: st.id });
    }

    updateWorld((d) => {
      const now = demoNow();
      const i = d.incidents[id];
      i.response.state = "applied";
      i.response.appliedAt = now;
      i.status = "mitigating";
      i.timeline.push({ id: nextId("IE"), at: now, title: "Group response applied", detail: i.response.summary, tone: "ok", actor: people.analyst.name });
      for (const e of d.escalations) {
        if (e.target.type === "shipment" && i.affected.includes(e.target.id) && e.status === "awaiting") {
          e.status = "resolved";
          addEvent(d, e.target.id, { at: now, title: `Escalation resolved via ${id} response`, detail: `Approved by ${people.supervisor.name}`, source: "supervisor", tone: "ok" });
        }
      }
      addLedger(d, { at: now, incidentId: id, decision: `Group response · ${plural(i.affected.length + i.exposed.length, "shipment")}`, decidedBy: "Shift supervisor", basis: "Route incident · one shared cause", outcome: "pending" });
      notify(d, { at: now, kind: "outcome", tone: "ok", title: `Group response applied · ${id}`, body: i.response.summary, target: { type: "incident", id }, actor: people.analyst.name });
      d.scenario.holdUntilReal = Date.now() + 8000;
    });
    onProgress?.({ stage: "done" });
    pushToast({ tone: "ok", title: `Group response applied · ${id}`, body: "One action for every affected and exposed shipment", href: `/incidents/${id}` });
  },

  async resolve(id) {
    await sleep(700);
    updateWorld((d) => {
      const now = demoNow();
      const i = d.incidents[id];
      if (!i) return;
      i.status = "resolved";
      i.resolvedAt = now;
      i.timeline.push({ id: nextId("IE"), at: now, title: "Incident resolved", detail: "Corridor speed back to normal", tone: "ok", actor: people.analyst.name });
      for (const sid of [...i.affected, ...i.exposed]) {
        const s = d.shipments[sid];
        if (s && s.health === "recovering") {
          setHealth(d, sid, "recovered");
          s.outcome = { kind: "recovered", label: `Recovered via ${id} response`, at: now };
        }
        if (s) s.agent = { ...s.agent, state: "resolved", headline: `Recovered via ${id}`, updatedAt: now };
      }
      for (const e of d.ledger) if (e.incidentId === id && e.outcome === "pending") Object.assign(e, { outcome: "resolved", outcomeAt: now });
      notify(d, { at: now, kind: "outcome", tone: "ok", title: `Incident resolved · ${id}`, body: `${plural(i.affected.length + i.exposed.length, "shipment")} recovered through one response`, target: { type: "incident", id }, actor: people.analyst.name });
    });
    pushToast({ tone: "ok", title: `${id} resolved`, href: `/incidents/${id}` });
  },
};

/** Beat 6: another failure on the corridor joins the incident and severity rises. */
export function escalateIncidentSeverity(incidentId: string, shipmentId: string) {
  updateWorld((d) => {
    const i = d.incidents[incidentId];
    if (!i || i.status === "resolved") return;
    i.exposed = i.exposed.filter((x) => x !== shipmentId);
    if (!i.affected.includes(shipmentId)) i.affected.push(shipmentId);
    markMember(d, incidentId, shipmentId, "affected");
    const now = demoNow();
    const before = i.severity;
    i.severity = i.affected.length >= 6 ? "critical" : i.severity;
    i.detector.observed = i.affected.length;
    i.detector.z = (i.affected.length - i.detector.baselineMean) / Math.max(i.detector.baselineStd, 0.35);
    i.detector.series[i.detector.series.length - 1].count = i.affected.length;
    i.response.steps = buildResponseSteps(d, i.affected, i.exposed);
    i.response.summary = `Reroute ${plural(i.exposed.length, "exposed shipment")}, resume ${plural(i.affected.length, "held van")}, notify ${i.affected.length + i.exposed.length} recipients`;
    i.timeline.push({ id: nextId("IE"), at: now, title: `${shipmentId} failed — now ${i.affected.length} affected`, detail: before !== i.severity ? `Severity ${before} → ${i.severity}` : undefined, tone: "crit", actor: "Incident detector" });
    notify(d, { at: now, kind: "incident", tone: "crit", title: `Incident severity increased · ${incidentId}`, body: `${shipmentId} joined · ${i.affected.length} affected, ${i.exposed.length} exposed`, target: { type: "incident", id: incidentId }, actor: "Incident detector" });
  });
  pushToast({ tone: "crit", title: `${incidentId} severity increased`, body: `${shipmentId} failed on the same corridor`, href: `/incidents/${incidentId}` });
}
