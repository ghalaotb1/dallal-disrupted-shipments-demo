import { places } from "@/data/network";
import { SCENARIO_START } from "@/lib/time";
import { api, ApiError, planApi, type RunEnvelope } from "@/lib/live/client";
import { buildCase, buildPlanSnapshot } from "@/lib/ops/case";
import { cancelAssistant } from "@/lib/ops/assistantChat";
import { revealTotal } from "@/lib/ops/narrative";
import { freshWorld, getOps, getUi, opsNow, runtime, setUi, toast, updateOps } from "@/store/ops";
import { setLive } from "@/store/live";
import type { LivePlan } from "@/types/live";
import type { OpsWorld, Parcel, ScenarioCase, ScenarioId } from "@/types/ops";

const MIN = 60_000;
const SPARE_ETA: Record<string, number> = { S1: 20, S2: 28 };
export const MANAGER_NAME = "Faisal Al-Dosari";
export const AUTO_NAME = "Dallal (automatic)";

/** Everything asynchronous started for the current scenario is dropped when the generation changes (reset / another scenario). */
const gen = () => getOps().generation;
/** Runs whose automatic action was already sent (an action must never be sent twice). */
const executed = new Set<string>();

function note(w: OpsWorld, text: string, tone: "info" | "ok" | "warn" | "review" = "info", parcelId?: string) {
  w.events.unshift({ id: `E-${w.events.length + 1}-${Date.now().toString(36)}`, at: opsNow(), text, tone, parcelId });
}

function errText(e: unknown): string {
  if (e instanceof ApiError) return e.status === 0 ? "The Dallal backend is not reachable. Start it with npm run demo." : e.message;
  return e instanceof Error ? e.message : "Something went wrong";
}

// ── scenario lifecycle ────────────────────────────────────────────────────────────────────────────────────────────────

export async function resetDemo(): Promise<void> {
  setUi({ busy: "reset" });
  try {
    await api.demoReset();
  } catch (e) {
    toast("warn", `Backend history was not cleared: ${errText(e)}`);
  }
  executed.clear();
  cancelAssistant();
  const g = gen() + 1;
  const w = freshWorld(g);
  w.clock = { ...w.clock, baseReal: Date.now(), running: true };
  updateOps(() => w);
  setUi({ selectedDriverId: null, selectedParcelId: null, expandedDriverIds: [], detailsOpen: false, revealed: {}, busy: null, role: "operator", tab: "cases", openCaseId: null, kpiFilter: "all", assistant: [] });
}

const caseOf = (id: ScenarioId): ScenarioCase | undefined => getOps().cases.find((c) => c.scenario === id);
const caseOfRun = (runId: string): ScenarioCase | undefined => getOps().cases.find((c) => c.runId === runId);
const updateCase = (id: ScenarioId, fn: (c: ScenarioCase) => void) =>
  updateOps((w) => {
    const c = w.cases.find((x) => x.scenario === id);
    if (c) fn(c);
  });

/** Open a case: Dallal starts investigating on its own. */
export function openCase(id: ScenarioId): void {
  const c = caseOf(id);
  if (!c) return;
  setUi({ openCaseId: id, tab: "cases", selectedDriverId: c.driverId, selectedParcelId: c.parcelId, expandedDriverIds: [c.driverId], role: "operator" });
  if (!c.runId && !c.running) void investigateCase(id);
}

export function closeCase(): void {
  setUi({ openCaseId: null, selectedParcelId: null });
}

// ── backend runs ──────────────────────────────────────────────────────────────────────────────────────────────────────

function applyEnvelope(env: RunEnvelope, g: number) {
  if (gen() !== g) return;
  const raw = env.run as Record<string, unknown>;
  updateOps((w) => {
    w.runs[env.ui.id] = {
      ui: env.ui,
      decision: (raw.decision as Record<string, unknown>) ?? {},
      status: String(raw.status ?? env.ui.backendStatus ?? ""),
      inquiries: (raw.inquiries_live as RunEnvelope["run"]["inquiries_live"]) ?? [],
      trajectory: (raw.belief_trajectory as { after: string; top: [string, number][] }[]) ?? [],
    };
  });
}

export async function connectBackend(): Promise<void> {
  try {
    const meta = await api.meta();
    setLive({ status: "connected", meta, lastError: undefined });
  } catch (e) {
    setLive({ status: "offline", lastError: errText(e) });
  }
}

/** The backend reasons over the moment the disruption was detected, not over the wall clock that keeps the vans moving. */
const CASE_NOW = SCENARIO_START;

async function runFor(parcelId: string, g: number): Promise<string> {
  const p = getOps().parcels[parcelId];
  const trigger = p.exception ? { kind: "exception_recorded", detail: p.exception.label } : { kind: "analyst_request" };
  const env = await api.frontendRun(buildCase(getOps(), parcelId, CASE_NOW, trigger));
  if (gen() !== g) throw new Error("superseded");
  applyEnvelope(env, g);
  setLive({ status: "connected" });
  return env.ui.id;
}

export async function investigateCase(id: ScenarioId): Promise<void> {
  const c = caseOf(id);
  if (!c || c.runId || c.running) return;
  const g = gen();
  updateCase(id, (x) => {
    x.running = true;
    x.error = undefined;
  });
  try {
    const runId = await runFor(c.parcelId, g);
    updateCase(id, (x) => {
      x.runId = runId;
      x.running = false;
    });
    updateOps((w) => note(w, `Dallal investigated ${c.parcelId}`, "info", c.parcelId));
    await afterRun(runId, g);
  } catch (e) {
    if (gen() === g) updateCase(id, (x) => {
      x.running = false;
      x.error = errText(e);
    });
  }
}

/** Check any single parcel (the individual-shipment view). */
export async function investigateParcel(parcelId: string): Promise<void> {
  if (getUi().busy) return;
  const g = gen();
  setUi({ busy: "investigate" });
  try {
    const runId = await runFor(parcelId, g);
    await afterRun(runId, g);
  } catch (e) {
    if (gen() === g) toast("warn", errText(e));
  } finally {
    if (gen() === g) setUi({ busy: null });
  }
}

/** React to what the backend decided. Only an `auto_eligible` decision may execute without a person; everything else waits for the right role. */
async function afterRun(runId: string, g: number) {
  const rec = getOps().runs[runId];
  if (!rec || gen() !== g) return;
  const type = rec.decision.type as string | undefined;
  if (rec.status === "awaiting_response") {
    void pollRun(runId, g);
    return;
  }
  const a = caseOfRun(runId);
  if (type === "auto_eligible" && !executed.has(runId)) {
    executed.add(runId);
    await executeRun(runId, undefined, undefined);
  } else if (type === "incident" && a && !a.planId) {
    await createPlan(g, a);
  } else if (type === "escalate" || type === "recommend") {
    updateOps((w) => {
      const p = w.parcels[w.runs[runId].ui.shipmentId];
      if (p && type === "escalate") {
        p.state = "awaiting_manager";
        p.headline = "Waiting for the manager";
      }
      note(w, type === "escalate" ? "Dallal escalated the case to the manager" : "Dallal recommends an action and needs an operator to confirm", "review", p?.id);
    });
  }
}

async function pollRun(runId: string, g: number) {
  for (let i = 0; i < 90 && gen() === g; i++) {
    await new Promise((r) => setTimeout(r, 1200));
    try {
      const rec = getOps().runs[runId];
      const env = await api.run(runId, rec?.ui.startedAt ?? 0);
      applyEnvelope(env, g);
      if (env.run.status !== "awaiting_response") {
        await afterRun(runId, g);
        return;
      }
    } catch {
      /* transient; keep polling */
    }
  }
}

export async function refreshRun(runId: string): Promise<void> {
  const g = gen();
  const env = await api.run(runId, getOps().runs[runId]?.ui.startedAt ?? 0);
  applyEnvelope(env, g);
  if (env.run.status !== "awaiting_response") await afterRun(runId, g);
  else void pollRun(runId, g);
}

// ── replies (simulated recipient / courier / dispatcher device) ───────────────────────────────────────────────────────

export async function sendReply(inquiryId: string, runIdOrPlan: { run?: string; plan?: string }, body: { kind: "button"; answer_id: string } | { kind: "text"; text: string }): Promise<void> {
  const g = gen();
  setUi({ busy: "reply" });
  try {
    await api.sandboxReply({ inquiry_id: inquiryId, ...body });
    if (runIdOrPlan.run) await refreshRun(runIdOrPlan.run);
    if (runIdOrPlan.plan) await refreshPlan(runIdOrPlan.plan);
  } catch (e) {
    toast("warn", errText(e));
  } finally {
    if (gen() === g) setUi({ busy: null });
  }
}

export async function reviewReply(inquiryId: string, runId: string | undefined, planId: string | undefined, answerId: string | null): Promise<void> {
  setUi({ busy: "reply" });
  try {
    await api.review(inquiryId, { answer_id: answerId, reviewer: "Desk operator" });
    if (runId) await refreshRun(runId);
    if (planId) await refreshPlan(planId);
  } catch (e) {
    toast("warn", errText(e));
  } finally {
    setUi({ busy: null });
  }
}

export async function letItTimeOut(inquiryId: string, runId?: string, planId?: string): Promise<void> {
  setUi({ busy: "reply" });
  try {
    await api.expire(inquiryId);
    if (runId) await refreshRun(runId);
    if (planId) await refreshPlan(planId);
  } catch (e) {
    toast("warn", errText(e));
  } finally {
    setUi({ busy: null });
  }
}

// ── executing a single-parcel decision ───────────────────────────────────────────────────────────────────────────────

const EFFECT: Record<string, { headline: string; journey: string; outcome: { kind: "prevented" | "recovered"; label: string } }> = {
  verify_address: { headline: "Customer asked to confirm the pin · awaiting reply", journey: "WhatsApp sent to the customer to confirm the delivery pin (sandbox)", outcome: { kind: "prevented", label: "Customer confirmed the pin · re-attempt scheduled" } },
  contact_recipient: { headline: "Customer asked to confirm availability · awaiting reply", journey: "WhatsApp sent to the customer to confirm availability (sandbox)", outcome: { kind: "recovered", label: "Customer confirmed a new time · re-attempt scheduled" } },
  offer_window: { headline: "New delivery window offered · awaiting reply", journey: "New delivery window offered to the customer (sandbox)", outcome: { kind: "recovered", label: "Customer accepted the new window" } },
  branch_escalation: { headline: "Branch asked to clear the parcel", journey: "Branch asked to clear the backlog for this parcel", outcome: { kind: "recovered", label: "Branch released the parcel" } },
};

export async function executeRun(runId: string, by: string | undefined, role: "analyst" | "supervisor" | undefined): Promise<void> {
  const g = gen();
  const rec = getOps().runs[runId];
  if (!rec) return;
  const action = String(rec.decision.action ?? "");
  const parcelId = rec.ui.shipmentId;
  setUi({ busy: "execute" });
  try {
    const res = await api.execute(runId, { approved_by: by ?? AUTO_NAME, role, action });
    if (gen() !== g) return;
    const eff = EFFECT[action] ?? { headline: "Action sent", journey: `Action ${action} recorded`, outcome: { kind: "recovered" as const, label: "Action completed" } };
    const now = opsNow();
    updateOps((w) => {
      const p = w.parcels[parcelId];
      if (p) {
        p.state = "recovering";
        p.headline = eff.headline;
      }
      w.journeys[parcelId]?.push({ id: `${parcelId}-act-${now}`, shipmentId: parcelId, at: now, title: eff.journey, detail: by ? `Approved by ${by}` : "Executed automatically within policy", source: "agent", tone: "agent" });
      note(w, `${by ? "Executed" : "Dallal executed automatically"}: ${rec.decision.action_title ?? action} (simulated)`, "ok", parcelId);
    });
    setTimeout(() => settleOutcome(parcelId, eff.outcome, res.action_id, g), 7000);
  } catch (e) {
    toast("warn", `The backend refused the action: ${errText(e)}`);
  } finally {
    if (gen() === g) setUi({ busy: null });
  }
}

/** The result is observed in the SIMULATED world and recorded as such; the agent never grades itself. */
function settleOutcome(parcelId: string, outcome: { kind: "prevented" | "recovered"; label: string }, actionId: string, g: number) {
  if (gen() !== g) return;
  const now = opsNow();
  updateOps((w) => {
    const p = w.parcels[parcelId];
    if (!p) return;
    p.state = outcome.kind;
    p.headline = outcome.label;
    p.simOutcome = { ...outcome, at: now };
    p.exception = undefined;
    note(w, `${parcelId}: ${outcome.label} (simulated outcome)`, "ok", parcelId);
  });
  void api.outcome(actionId, { kind: outcome.kind, source: "frontend-simulated-environment", note: outcome.label }).catch(() => undefined);
}

export function takeOver(parcelId: string): void {
  updateOps((w) => {
    const p = w.parcels[parcelId];
    if (p) {
      p.state = "recovering";
      p.headline = "Manager took over the case";
    }
    note(w, `${MANAGER_NAME} took over ${parcelId} (no automated action)`, "review", parcelId);
  });
}

// ── coordinated plan (scenario C) ─────────────────────────────────────────────────────────────────────────────────

async function createPlan(g: number, c: ScenarioCase) {
  try {
    const plan = await planApi.create(buildPlanSnapshot(getOps(), c, CASE_NOW, opsNow(), `INC-${c.scenario}-${SCENARIO_START % 1000}`));
    if (gen() !== g) return;
    storePlan(plan);
    updateCase(c.scenario, (x) => {
      x.planId = plan.plan_id;
    });
    updateOps((w) => note(w, `Dallal grouped ${Object.keys(plan.solution.per_parcel).length} parcels from ${c.affectedDriverIds.length} drivers into one plan`, "info"));
    if (plan.status === "awaiting_evidence") {
      void pollPlan(plan.plan_id, g);
      void simulateDispatcherReply(plan, c.scenario, g);
    } else onPlanReady(plan);
  } catch (e) {
    updateCase(c.scenario, (x) => {
      x.error = errText(e);
    });
  }
}

/**
 * SANDBOX SIMULATION of the dispatcher answering the question. The blockage in this operation really is long, so a dispatcher would tap
 * "Blocked, expected > 30 min". The tap is delivered through the backend's real inbound path (a Meta-shaped webhook -> interpreter ->
 * belief update -> re-planning); only the person is simulated, and nothing reaches a phone. The delay lets the question be read first.
 */
const DISPATCHER_REPLY_DELAY_MS = 4000;
const DISPATCHER_ANSWER = "blocked_long";

async function simulateDispatcherReply(plan: LivePlan, caseId: ScenarioId, g: number) {
  const q = plan.inquiries[0];
  if (!q) return;
  updateCase(caseId, (x) => {
    x.reply = "typing";
  });
  // The dispatcher "reads" the question only once the operator can: wait until the story has revealed the plan, then a short typing delay.
  const runId = getOps().cases.find((x) => x.scenario === caseId)?.runId;
  for (let i = 0; runtime.ui && i < 100 && gen() === g; i++) {
    const rec = runId ? getOps().runs[runId] : undefined;
    if (!rec || (getUi().revealed[runId!] ?? 0) >= revealTotal(rec)) break;
    await new Promise((r) => setTimeout(r, 200));
  }
  await new Promise((r) => setTimeout(r, DISPATCHER_REPLY_DELAY_MS));
  if (gen() !== g) return;
  try {
    await api.sandboxReply({ inquiry_id: q.inquiry_id, kind: "button", answer_id: DISPATCHER_ANSWER });
    updateCase(caseId, (x) => {
      x.reply = "sent";
    });
    await refreshPlan(plan.plan_id);
  } catch (e) {
    if (gen() !== g) return;
    updateCase(caseId, (x) => {
      x.reply = "failed";
    });
    toast("warn", `Sandbox reply failed: ${errText(e)}`);
  }
}

function storePlan(plan: LivePlan) {
  updateOps((w) => {
    w.plans[plan.plan_id] = plan;
    if (plan.status === "awaiting_evidence" && !w.planBefore[plan.plan_id]) w.planBefore[plan.plan_id] = Object.fromEntries(Object.entries(plan.solution.per_parcel).map(([k, v]) => [k, v.option]));
  });
}

function onPlanReady(plan: LivePlan) {
  updateOps((w) => {
    if (Object.keys(plan.solution.per_parcel).every((pid) => w.parcels[pid]?.state === "awaiting_manager")) return; // already announced
    for (const pid of Object.keys(plan.solution.per_parcel)) {
      const p = w.parcels[pid];
      if (p && p.state !== "awaiting_manager") {
        p.state = "awaiting_manager";
        p.headline = "Plan ready · waiting for the manager";
      }
    }
    note(w, "The coordinated plan is ready and needs the manager's approval", "review");
  });
}

async function pollPlan(planId: string, g: number) {
  for (let i = 0; i < 120 && gen() === g; i++) {
    await new Promise((r) => setTimeout(r, 1500));
    try {
      const plan = await planApi.get(planId);
      storePlan(plan);
      if (plan.status !== "awaiting_evidence") {
        onPlanReady(plan);
        return;
      }
    } catch {
      /* transient */
    }
  }
}

export async function refreshPlan(planId: string): Promise<void> {
  const g = gen();
  const before = getOps().plans[planId]?.status;
  const plan = await planApi.get(planId);
  storePlan(plan);
  if (before === "awaiting_evidence" && plan.status !== "awaiting_evidence" && gen() === g) onPlanReady(plan);
}

export async function decidePlan(planId: string, decision: "approve" | "reject"): Promise<void> {
  const g = gen();
  setUi({ busy: "plan" });
  try {
    const plan = await planApi.decide(planId, { decision, by: MANAGER_NAME, role: "supervisor" });
    if (gen() !== g) return;
    storePlan(plan);
    if (decision === "approve" && plan.status === "executed_simulated") applyPlan(plan);
    else rejectPlan(plan);
    setUi({ role: "operator" });
  } catch (e) {
    toast("warn", errText(e));
  } finally {
    if (gen() === g) setUi({ busy: null });
  }
}

function rejectPlan(plan: LivePlan) {
  updateOps((w) => {
    for (const pid of Object.keys(plan.solution.per_parcel)) {
      const p = w.parcels[pid];
      if (p && p.state === "awaiting_manager") {
        p.state = "at_risk";
        p.headline = "Plan rejected · back with the desk";
      }
    }
    note(w, `${MANAGER_NAME} rejected the coordinated plan`, "warn");
  });
}

/** Writes an approved plan into the simulated world: parcels move to spare couriers or pickup points, held vans move again. */
function applyPlan(plan: LivePlan) {
  const now = opsNow();
  const counts: Record<string, number> = {};
  updateOps((w) => {
    for (const [pid, { option, text }] of Object.entries(plan.solution.per_parcel)) {
      const p = w.parcels[pid];
      if (!p) continue;
      const [kind, ref] = option.split(":");
      counts[kind] = (counts[kind] ?? 0) + 1;
      apply(p, kind, ref, text, now);
      w.journeys[pid]?.push({ id: `${pid}-plan-${now}`, shipmentId: pid, at: now, title: text, detail: `Coordinated plan ${plan.plan_id} · approved by ${MANAGER_NAME}`, source: "supervisor", tone: "ok" });
    }
    for (const id of w.cases.find((x) => x.planId === plan.plan_id)?.affectedDriverIds ?? []) {
      const d = w.drivers[id];
      d.nav = { distanceM: Math.min(d.nav.holdAtM ?? d.nav.distanceM, d.nav.distanceM + (d.nav.speedMps * Math.max(0, now - d.nav.updatedAt)) / 1000), speedMps: 4, updatedAt: now };
      d.note = "Moving through the managed lane";
    }
    const summary = Object.entries(counts).map(([k, n]) => `${n} ${k}`).join(", ");
    note(w, `${MANAGER_NAME} approved the coordinated plan: ${summary} (simulated execution)`, "ok");
  });
}

function apply(p: Parcel, kind: string, ref: string | undefined, text: string, now: number) {
  p.incident = true;
  if (kind === "spare") {
    p.state = "reassigned";
    p.recovery = { kind: "spare", label: `Spare courier ${ref}`, etaAt: now + (SPARE_ETA[ref ?? ""] ?? 25) * MIN, fromPlan: true };
    p.headline = text;
  } else if (kind === "pickup") {
    p.state = "reassigned";
    p.recovery = { kind: "pickup", label: places[ref ?? ""]?.name ?? "Pickup point", fromPlan: true };
    p.headline = text;
  } else if (kind === "defer") {
    p.state = "recovering";
    p.recovery = { kind: "defer", label: "Rescheduled with notice", fromPlan: true };
    p.headline = "Rescheduled with notice to the customer";
  } else {
    p.state = "recovering";
    p.recovery = { kind: kind === "reroute" ? "reroute" : "wait", label: kind === "reroute" ? "Rerouted" : "Holds, then resumes", fromPlan: true };
    p.headline = kind === "reroute" ? "Rerouted around the blockage" : "Waits in the managed lane, then resumes";
  }
}
