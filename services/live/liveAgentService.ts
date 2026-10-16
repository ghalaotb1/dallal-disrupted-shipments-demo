import { people } from "@/data/people";
import { api, ApiError } from "@/lib/live/client";
import { buildCase } from "@/lib/live/payload";
import { demoAgentService, outcomeToState } from "@/services/demo/agentService";
import { demoNow, getWorld, nextId, updateWorld } from "@/store/world";
import { setLive } from "@/store/live";
import { pushToast } from "@/store/ui";
import type { AgentService } from "@/services/contracts";
import type { AgentRun, AgentState } from "@/types/domain";

/** Backend run -> shared world store. Every screen reads the store, so one write keeps the whole app consistent. */
export function applyLiveRun(ui: AgentRun) {
  const now = demoNow();
  updateWorld((d) => {
    const awaiting = ui.backendStatus === "awaiting_response";
    const prev = d.agentRuns[ui.id];
    // A live run finishes on the OPERATIONS clock when the backend completes it, not at the synthetic per-step offsets used for display.
    const run: AgentRun = { ...ui, source: "live", startedAt: ui.startedAt || now, finishedAt: awaiting ? undefined : (prev?.finishedAt ?? now) };
    // Replace any pending placeholder for this shipment.
    for (const [id, r] of Object.entries(d.agentRuns)) if (id.startsWith("RUN-pending-") && r.shipmentId === ui.shipmentId) delete d.agentRuns[id];
    d.agentRuns[ui.id] = run;
    const s = d.shipments[ui.shipmentId];
    if (s) {
      const state: AgentState = awaiting ? "awaiting_reply" : ui.outcome ? outcomeToState(ui.outcome) : "investigating";
      s.agent = { state, headline: awaiting ? "Waiting for an answer" : ui.outcome?.headline, lastRunId: ui.id, updatedAt: now };
    }
    d.scenario.holdUntilReal = Date.now() + (ui.backendStatus === "awaiting_response" ? 90_000 : 10_000);
  });
}

function placeholder(shipmentId: string): string {
  const id = `RUN-pending-${nextId("P")}`;
  const now = demoNow();
  updateWorld((d) => {
    d.agentRuns[id] = { id, shipmentId, mode: "investigation", trigger: "analyst", status: "running", startedAt: now, steps: [], source: "live" };
    const s = d.shipments[shipmentId];
    if (s) s.agent = { state: "investigating", headline: "Investigating case", lastRunId: id, updatedAt: now };
    d.scenario.holdUntilReal = Date.now() + 60_000;
  });
  return id;
}

function dropPlaceholder(id: string) {
  updateWorld((d) => void delete d.agentRuns[id]);
}

export function latestLiveRun(shipmentId: string): AgentRun | undefined {
  return Object.values(getWorld().agentRuns)
    .filter((r) => r.shipmentId === shipmentId && r.source === "live" && r.mode === "investigation" && !r.id.startsWith("RUN-pending-"))
    .sort((a, b) => b.startedAt - a.startedAt)[0];
}

export const liveAgentService: AgentService = {
  async investigate(shipmentId) {
    const pid = placeholder(shipmentId);
    try {
      const res = await api.frontendRun(buildCase(shipmentId));
      dropPlaceholder(pid);
      applyLiveRun(res.ui);
      setLive({ status: "connected" });
      return getWorld().agentRuns[res.ui.id];
    } catch (e) {
      dropPlaceholder(pid);
      if (e instanceof ApiError && e.status === 0) {
        setLive({ status: "offline", lastError: e.message });
        pushToast({ tone: "warn", title: "Backend unreachable", body: "Showing the in-browser prototype planner instead. Results below are simulated.", href: undefined });
        return demoAgentService.investigate(shipmentId);
      }
      throw e;
    }
  },

  async execute(shipmentId, actionId, opts) {
    const run = latestLiveRun(shipmentId);
    const action = run?.actions?.find((a) => a.id === actionId);
    if (!run || !action) return demoAgentService.execute(shipmentId, actionId, opts);
    // 1) The backend authorises (approval level), logs the decision/action and keeps the outcome PENDING.
    // The approver role comes from the backend DECISION, not the action's base level: a 'recommend' means the autonomy gates failed (e.g. value
    // above the bound) so a person must approve - here the analyst who clicked. 'escalate' needs a supervisor (opts.approvedBy). Only
    // 'auto_eligible' may run without a person.
    const dtype = run.backend?.decision.type;
    const role = opts?.approvedBy ? "supervisor" : dtype === "auto_eligible" ? undefined : dtype === "recommend" ? "analyst" : "supervisor";
    const by = opts?.approvedBy ?? (role === "analyst" ? people.analyst.name : undefined);
    let exec;
    try {
      exec = await api.execute(run.id, { approved_by: by, role, action: action.kind });
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "backend error";
      pushToast({ tone: "warn", title: "Backend refused the action", body: msg, href: undefined });
      return run; // nothing was executed; the run stays as it is
    }
    // 2) The browser still owns the simulated physical world: play the action's effect there.
    const result = await demoAgentService.execute(shipmentId, actionId, opts);
    // 3) The result observed in the SIMULATED environment is recorded - labelled as such - as the action's outcome. The agent never grades itself.
    const s = getWorld().shipments[shipmentId];
    // Report exactly what the simulated world now shows, so the backend ledger and every screen agree.
    const h = s?.health;
    const kind = s?.outcome?.kind === "prevented" || h === "prevented" ? "prevented" : s?.outcome?.kind === "recovered" || h === "recovered" || h === "recovering" ? "recovered" : "no_effect";
    void api.outcome(exec.action_id, { kind, source: "frontend-simulated-environment", note: s?.outcome?.label ?? "outcome observed in the simulated operations world" }).catch(() => {});
    return result;
  },
};
