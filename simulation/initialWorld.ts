import { buildShipment } from "@/data/scenario/builders";
import { seedIncidents } from "@/data/scenario/seedIncidents";
import { seedEmails, seedEscalations, seedLedger, seedNotifications } from "@/data/scenario/seedNotifications";
import { seedShipments } from "@/data/scenario/seedShipments";
import { at, DEMO_TIME_SCALE, SCENARIO_START } from "@/lib/time";
import { investigateSync, outcomeToState } from "@/services/demo/agentService";
import { computePriority } from "@/services/logic/priority";
import { assessRisk } from "@/services/logic/risk";
import type { WorldState } from "@/store/world";
import type { AgentRun } from "@/types/domain";

/** Build the deterministic 15:10 world. Earlier agent runs are produced by the real planner. */
export function createInitialWorld(generation: number, autoplay: boolean): WorldState {
  const world: WorldState = {
    ready: true,
    clock: { baseDemo: SCENARIO_START, baseReal: Date.now(), running: true, scale: DEMO_TIME_SCALE },
    shipments: {},
    journeys: {},
    contexts: {},
    incidents: Object.fromEntries(seedIncidents.map((i) => [i.id, structuredClone(i)])),
    agentRuns: {},
    notifications: structuredClone(seedNotifications),
    emails: Object.fromEntries(seedEmails.map((e) => [e.id, structuredClone(e)])),
    escalations: structuredClone(seedEscalations),
    ledger: structuredClone(seedLedger),
    scenario: {
      autoplay,
      firedBeats: [],
      completedSteps: ["overview"],
      nextLaneSeq: 21001,
      nextDispatchAt: SCENARIO_START + 30_000,
      holdUntilReal: 0,
      generation,
    },
  };

  for (const seed of seedShipments) {
    const { shipment, journey, context } = buildShipment(seed);
    world.shipments[shipment.id] = shipment;
    world.journeys[shipment.id] = journey;
    world.contexts[shipment.id] = context;
  }
  for (const s of Object.values(world.shipments)) {
    s.risk = assessRisk(s, world.contexts[s.id], s.closed ? s.lastEventAt : SCENARIO_START);
    s.priority = computePriority(s);
  }

  // Earlier investigations — same planner and tools as live runs.
  const seededRuns: [string, string][] = [
    ["DL-20910", "13:28"],
    ["DL-20655", "14:05"],
    ["DL-20598", "14:38"],
    ["DL-20776", "14:55"],
  ];
  for (const [id, time] of seededRuns) {
    const run = investigateSync(world, id, at(time));
    if (id === "DL-20598") {
      run.steps.push({
        id: `${run.id}-esc`,
        tool: "escalate_case",
        args: 'to="shift_supervisor"',
        checking: "Opening escalation for human review",
        kind: "action",
        status: "ok",
        summary: "Escalated to Faisal Al-Dosari (shift supervisor)",
        facts: ["Policy: unknown patterns are never auto-resolved", "In-app + email notification (simulated)"],
        startedAt: at("14:42"),
        durationMs: 900,
      });
    }
    world.agentRuns[run.id] = run;
    const s = world.shipments[id];
    if (id === "DL-20910") {
      const exec: AgentRun = {
        id: "RUN-20910-exec",
        shipmentId: id,
        mode: "execution",
        trigger: "auto",
        status: "completed",
        startedAt: at("13:30"),
        finishedAt: at("13:37"),
        steps: [
          { id: "e1", tool: "retrieve_policy_constraints", args: 'action="top"', checking: "Checking approval and automation policy", kind: "read", status: "ok", summary: "Automated action allowed", facts: ["Low impact · reversible"], startedAt: at("13:30"), durationMs: 750 },
          { id: "e2", tool: "contact_recipient", args: 'channel="WhatsApp"', checking: "Sending window options", kind: "action", status: "ok", summary: "Recipient chose 18:00–20:00", facts: ["Options: 16:00–18:00 · 18:00–20:00 · Ar Rawabi Pickup Point"], startedAt: at("13:30"), durationMs: 1200 },
          { id: "e3", tool: "reschedule_delivery", args: `id="${id}"`, checking: "Updating delivery plan", kind: "action", status: "ok", summary: "Window updated to 18:00–20:00", facts: ["Courier stop moved to evening wave"], startedAt: at("13:37"), durationMs: 1100 },
        ],
        outcome: { type: "resolved", headline: "Recovered — recipient chose 18:00–20:00", rationale: "Automated, reversible action within policy." },
      };
      world.agentRuns[exec.id] = exec;
      s.agent = { state: "resolved", headline: "Rescheduled automatically · recipient confirmed 18:00–20:00", lastRunId: exec.id, updatedAt: at("13:37") };
      continue;
    }
    if (id === "DL-20598") {
      s.agent = { state: "awaiting_supervisor", headline: "Escalated — no known cause fits the evidence", lastRunId: run.id, updatedAt: at("14:42") };
      continue;
    }
    s.agent = { state: outcomeToState(run.outcome!), headline: run.outcome?.headline, lastRunId: run.id, updatedAt: run.finishedAt ?? at(time) };
    world.journeys[id].push({ id: `${id}-agent`, shipmentId: id, at: at(time), title: "Agent investigation completed", detail: `${run.steps.length} tools · ${run.outcome?.headline}`, source: "agent", tone: "agent" });
    world.journeys[id].sort((a, b) => a.at - b.at);
  }
  world.journeys["DL-20598"].push(
    { id: "DL-20598-agent", shipmentId: "DL-20598", at: at("14:38"), title: "Agent investigation: no known cause fits", detail: "Custody scans conflict · agent will not guess", source: "agent", tone: "agent" },
    { id: "DL-20598-esc", shipmentId: "DL-20598", at: at("14:42"), title: "Escalated to shift supervisor Faisal Al-Dosari", detail: "In-app + email notification (simulated)", source: "agent", tone: "review" },
  );
  world.journeys["DL-20598"].sort((a, b) => a.at - b.at);
  return world;
}
