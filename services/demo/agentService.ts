import { places } from "@/data/network";
import { people } from "@/data/people";
import { at, fmtTime, fmtWindow } from "@/lib/time";
import { conclude, planNext } from "@/services/agent/planner";
import { describeTool, runReadOrAnalysisTool, TOOL_META, type AgentMemory, type ToolOutput, type ToolWorld } from "@/services/agent/tools";
import { addEvent, addLedger, completeStep, notify, rescore, setHealth } from "@/services/demo/mutations";
import { anchorMovement } from "@/services/logic/movement";
import { demoNow, getWorld, nextId, updateWorld, type WorldState } from "@/store/world";
import { pushToast } from "@/store/ui";
import type { AgentService } from "@/services/contracts";
import type { AgentOutcome, AgentRun, AgentState, AgentStep, DemoTime, ToolName } from "@/types/domain";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const reducedMotion = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
const pace = (ms: number) => (reducedMotion() ? Math.min(ms, 250) : ms);

export function outcomeToState(o: AgentOutcome): AgentState {
  switch (o.type) {
    case "recommend":
    case "escalate":
      return "recommendation";
    case "auto_eligible":
      return "auto_eligible";
    case "incident":
      return "incident";
    default:
      return "monitoring";
  }
}

/** Synchronous investigation used to seed earlier runs with the same planner and tools. */
export function investigateSync(w: ToolWorld, shipmentId: string, startedAt: DemoTime): AgentRun {
  const mem: AgentMemory = { called: [] };
  const steps: AgentStep[] = [];
  let t = startedAt;
  for (let guard = 0; guard < 12; guard++) {
    const s = w.shipments[shipmentId];
    const tool = planNext(mem, s, w.contexts[shipmentId]);
    if (!tool) break;
    const out = runReadOrAnalysisTool(tool, w, s, t, mem);
    steps.push(makeStep(tool, s, t, out));
    t += TOOL_META[tool].durationMs * 10;
  }
  const outcome = conclude(mem, w.shipments[shipmentId]);
  return {
    id: `RUN-${shipmentId.slice(3)}-seed`,
    shipmentId,
    mode: "investigation",
    trigger: "scheduled",
    status: "completed",
    startedAt,
    finishedAt: t,
    steps,
    outcome,
    diagnosis: mem.diagnosis,
    actions: mem.actions,
  };
}

function makeStep(tool: ToolName, s: WorldState["shipments"][string], startedAt: DemoTime, out?: ToolOutput): AgentStep {
  const desc = describeTool(tool, s);
  return {
    id: nextId("ST"),
    tool,
    args: desc.args,
    checking: desc.checking,
    kind: TOOL_META[tool].kind,
    status: out ? out.status : "running",
    summary: out?.summary,
    facts: out?.facts,
    startedAt,
    durationMs: out ? TOOL_META[tool].durationMs : undefined,
  };
}

function startRun(shipmentId: string, mode: AgentRun["mode"]): string {
  const id = nextId("RUN");
  const now = demoNow();
  updateWorld((d) => {
    d.agentRuns[id] = { id, shipmentId, mode, trigger: "analyst", status: "running", startedAt: now, steps: [] };
    const s = d.shipments[shipmentId];
    s.agent = { state: mode === "investigation" ? "investigating" : "acting", headline: mode === "investigation" ? "Investigating case" : "Executing action", lastRunId: id, updatedAt: now };
    d.scenario.holdUntilReal = Date.now() + 60_000;
  });
  return id;
}

async function step(runId: string, tool: ToolName, perform: () => ToolOutput | Promise<ToolOutput>, opts?: { checking?: string; waitMs?: number }) {
  const shipmentId = getWorld().agentRuns[runId].shipmentId;
  const st = makeStep(tool, getWorld().shipments[shipmentId], demoNow());
  if (opts?.checking) st.checking = opts.checking;
  updateWorld((d) => void d.agentRuns[runId].steps.push(st));
  await sleep(pace(opts?.waitMs ?? TOOL_META[tool].durationMs));
  const out = await perform();
  updateWorld((d) => {
    const target = d.agentRuns[runId].steps.find((x) => x.id === st.id);
    if (target) Object.assign(target, { status: out.status, summary: out.summary, facts: out.facts, durationMs: TOOL_META[tool].durationMs });
  });
  await sleep(pace(220));
}

function setStepChecking(runId: string, checking: string) {
  updateWorld((d) => {
    const steps = d.agentRuns[runId].steps;
    const last = steps[steps.length - 1];
    if (last) last.checking = checking;
  });
}

function finishRun(runId: string, outcome: AgentOutcome, extra?: (d: WorldState) => void) {
  const now = demoNow();
  updateWorld((d) => {
    const run = d.agentRuns[runId];
    run.status = "completed";
    run.finishedAt = now;
    run.outcome = outcome;
    const s = d.shipments[run.shipmentId];
    s.agent = { state: run.mode === "execution" && outcome.type === "resolved" ? "resolved" : outcomeToState(outcome), headline: outcome.headline, lastRunId: runId, updatedAt: now };
    extra?.(d);
    d.scenario.holdUntilReal = Date.now() + 8000;
  });
}

export const demoAgentService: AgentService = {
  async investigate(shipmentId) {
    const runId = startRun(shipmentId, "investigation");
    const mem: AgentMemory = { called: [] };
    for (let guard = 0; guard < 12; guard++) {
      const w = getWorld();
      const tool = planNext(mem, w.shipments[shipmentId], w.contexts[shipmentId]);
      if (!tool) break;
      await step(runId, tool, () => {
        const out = runReadOrAnalysisTool(tool, getWorld(), getWorld().shipments[shipmentId], demoNow(), mem);
        updateWorld((d) => {
          if (mem.diagnosis) d.agentRuns[runId].diagnosis = mem.diagnosis;
          if (mem.actions) d.agentRuns[runId].actions = mem.actions;
        });
        return out;
      });
    }
    const outcome = conclude(mem, getWorld().shipments[shipmentId]);
    finishRun(runId, outcome, (d) => {
      addEvent(d, shipmentId, {
        at: demoNow(),
        title: "Agent investigation completed",
        detail: `${mem.called.length} tools · ${outcome.headline}`,
        source: "agent",
        tone: "agent",
      });
    });
    return getWorld().agentRuns[runId];
  },

  async execute(shipmentId, actionId, opts) {
    const w0 = getWorld();
    const lastRun = Object.values(w0.agentRuns)
      .filter((r) => r.shipmentId === shipmentId && r.actions?.length)
      .sort((a, b) => b.startedAt - a.startedAt)[0];
    const action = lastRun?.actions?.find((a) => a.id === actionId);
    if (!action) throw new Error(`Unknown action ${actionId}`);
    const runId = startRun(shipmentId, "execution");
    const s0 = w0.shipments[shipmentId];
    const recipient = s0.recipient.name;
    const channel = w0.contexts[shipmentId].recipient.preferredChannel;
    const decidedBy = opts?.approvedBy ? "Shift supervisor" : action.approval === "analyst" ? "Analyst" : "Agent (automated)";

    await step(runId, "retrieve_policy_constraints", () => ({
      status: "ok",
      summary: opts?.approvedBy ? `Approved by ${opts.approvedBy}` : action.approval === "analyst" ? `Approved by ${people.analyst.name}` : "Automated action allowed",
      facts: [action.reversible ? "Reversible action" : "Not reversible after handover", `Impact ${action.impact}`],
    }));

    const ledger = (d: WorldState, outcome: "pending" | "prevented" | "recovered" | "resolved") =>
      addLedger(d, { at: demoNow(), shipmentId, decision: action.title, decidedBy, basis: lastRun?.diagnosis?.causeLabel ?? "Recovery action", outcome });

    switch (action.kind) {
      case "verify_address": {
        await step(
          runId,
          "contact_recipient",
          async () => {
            setStepChecking(runId, `Location-pin request delivered · waiting for ${recipient} to reply…`);
            await sleep(pace(2600));
            const now = demoNow();
            updateWorld((d) => {
              addEvent(d, shipmentId, { at: now - 90_000, title: `Location-pin request sent via ${channel}`, detail: "contact_recipient() · automated, reversible", source: "agent", tone: "agent" });
              addEvent(d, shipmentId, { at: now, title: "Recipient shared location pin", detail: "Bldg 7342 confirmed · pin within 40 m of National Address", source: "recipient", tone: "ok" });
              const ctx = d.contexts[shipmentId];
              ctx.address.confidence = 0.94;
              ctx.address.checks = ctx.address.checks.map((c) => ({ ...c, result: "pass" as const, detail: c.label.includes("pin") ? "Recipient pin confirmed (within 40 m)" : "Confirmed by recipient" }));
              ctx.address.pastFailuresAtAddress = 0;
            });
            return { status: "ok", summary: "Recipient confirmed location pin", facts: ["Bldg 7342 matches National Address", "Courier notes updated with pin"] };
          },
          { checking: `Sending location-pin request to ${recipient} via ${channel}` },
        );
        await step(runId, "predict_risk", () => {
          const before = getWorld().shipments[shipmentId].risk.score;
          updateWorld((d) => rescore(d, shipmentId, demoNow()));
          const after = getWorld().shipments[shipmentId].risk;
          return { status: "ok", summary: `Risk ${before} → ${after.score} · ${after.level}`, facts: ["Address no longer a risk driver"] };
        });
        finishRun(runId, { type: "resolved", headline: "Failure prevented — address confirmed before arrival", rationale: "The recipient confirmed the pin; the courier can deliver on this run." }, (d) => {
          const now = demoNow();
          const s = d.shipments[shipmentId];
          s.movement = anchorMovement(s, now);
          s.movement.holdAtM = undefined;
          setHealth(d, shipmentId, "prevented");
          s.headline = "Failure prevented — address confirmed before arrival";
          s.outcome = { kind: "prevented", label: "Address confirmed before arrival", at: now };
          addEvent(d, shipmentId, { at: now, title: "Risk dropped · failure prevented", detail: `Risk now ${s.risk.score} (prototype heuristic)`, source: "model", tone: "ok" });
          notify(d, { at: now, kind: "outcome", tone: "ok", title: `Failure prevented · ${shipmentId}`, body: "Recipient confirmed the address before the courier arrived", target: { type: "shipment", id: shipmentId }, actor: "Dallal Agent" });
          ledger(d, "pending");
          if (shipmentId === "DL-20417") completeStep(d, "prevented");
        });
        pushToast({ tone: "ok", title: `Failure prevented · ${shipmentId}`, body: "Address confirmed before arrival", href: `/shipments/${shipmentId}` });
        break;
      }

      case "offer_window": {
        const evening = { start: at("19:00"), end: at("21:00") };
        await step(
          runId,
          "contact_recipient",
          async () => {
            setStepChecking(runId, `Options sent · waiting for ${recipient} to choose…`);
            await sleep(pace(2600));
            updateWorld((d) => {
              const now = demoNow();
              addEvent(d, shipmentId, { at: now - 120_000, title: `New-window options sent via ${channel}`, detail: `Today ${fmtWindow(evening)} · ${places["pp-rawabi"].name}`, source: "agent", tone: "agent" });
              addEvent(d, shipmentId, { at: now, title: `Recipient chose today ${fmtWindow(evening)}`, source: "recipient", tone: "ok" });
            });
            return { status: "ok", summary: `Recipient chose today ${fmtWindow(evening)}`, facts: [`Offered: ${fmtWindow(evening)} or ${places["pp-rawabi"].short}`] };
          },
          { checking: `Sending window options to ${recipient} via ${channel}` },
        );
        await step(runId, "reschedule_delivery", () => {
          updateWorld((d) => {
            const s = d.shipments[shipmentId];
            s.window = evening;
            d.contexts[shipmentId].recipient.confirmedWindow = { ...evening, at: demoNow() };
            addEvent(d, shipmentId, { at: demoNow(), title: `Delivery rescheduled ${fmtWindow(evening)}`, detail: "reschedule_delivery()", source: "agent", tone: "ok" });
          });
          return { status: "ok", summary: `Window updated to ${fmtWindow(evening)}`, facts: ["Courier stop moved to evening wave"] };
        });
        finishRun(runId, { type: "resolved", headline: "Recovered — recipient chose a new window", rationale: "Recipient-selected window avoids a third missed attempt." }, (d) => {
          const now = demoNow();
          setHealth(d, shipmentId, "recovered");
          rescore(d, shipmentId, now);
          const s = d.shipments[shipmentId];
          s.headline = `Rescheduled to ${fmtWindow(evening)} by recipient choice`;
          s.outcome = { kind: "recovered", label: "Rescheduled · recipient confirmed", at: now };
          notify(d, { at: now, kind: "agent", tone: "ok", title: `Agent rescheduled ${shipmentId}`, body: `Recipient chose ${fmtWindow(evening)} · automated, reversible`, target: { type: "shipment", id: shipmentId }, actor: "Dallal Agent" });
          ledger(d, "pending");
        });
        pushToast({ tone: "ok", title: `${shipmentId} recovered`, body: `Recipient chose ${fmtWindow(evening)}`, href: `/shipments/${shipmentId}` });
        break;
      }

      case "redirect_pickup": {
        const pickup = s0.destination.city === "Dammam" ? places["pp-faisaliyah"] : places["pp-rawabi"];
        await step(runId, "redirect_to_pickup", () => {
          updateWorld((d) => {
            addEvent(d, shipmentId, { at: demoNow(), title: `Redirected to ${pickup.name}`, detail: "Return to sender cancelled · 7-day collection", source: "analyst", tone: "ok" });
          });
          return { status: "ok", summary: `Redirected to ${pickup.name}`, facts: ["Return to sender cancelled", "Collection window 7 days"] };
        });
        await step(runId, "contact_recipient", () => {
          updateWorld((d) => addEvent(d, shipmentId, { at: demoNow(), title: `Collection code sent via ${channel}`, source: "agent", tone: "agent" }));
          return { status: "ok", summary: `Collection code sent to ${recipient}`, facts: [`Ready from tomorrow 10:00 at ${pickup.short}`] };
        });
        finishRun(runId, { type: "resolved", headline: `Recovered — redirected to ${pickup.short}`, rationale: "Breaks the missed-attempt pattern." }, (d) => {
          const now = demoNow();
          const s = d.shipments[shipmentId];
          setHealth(d, shipmentId, "recovered");
          s.stage = "at_pickup_point";
          s.headline = `Redirected to ${pickup.name}`;
          s.outcome = { kind: "recovered", label: `Redirected to ${pickup.short}`, at: now };
          rescore(d, shipmentId, now);
          notify(d, { at: now, kind: "outcome", tone: "ok", title: `${shipmentId} redirected to pickup point`, body: `${pickup.name} · return to sender cancelled`, target: { type: "shipment", id: shipmentId }, actor: people.analyst.name });
          ledger(d, "pending");
        });
        pushToast({ tone: "ok", title: `${shipmentId} redirected`, body: pickup.name, href: `/shipments/${shipmentId}` });
        break;
      }

      case "resequence_stops": {
        await step(runId, "reschedule_delivery", () => {
          updateWorld((d) => {
            const now = demoNow();
            const s = d.shipments[shipmentId];
            s.movement = anchorMovement(s, now);
            s.movement.stopsAhead = 2;
            s.movement.speedMps = 9;
            addEvent(d, shipmentId, { at: now, title: "Moved to stop 3 of 18 on van DMM-118", detail: "3 Standard parcels delayed ~15 min, still within windows", source: "analyst", tone: "ok" });
          });
          return { status: "ok", summary: "Parcel moved to stop 3 of 18", facts: ["3 Standard parcels shift ~15 min · all within window"] };
        });
        await step(runId, "predict_risk", () => {
          updateWorld((d) => rescore(d, shipmentId, demoNow()));
          const r = getWorld().shipments[shipmentId].risk;
          return { status: "ok", summary: `Risk ${r.score} · ${r.level}`, facts: ["ETA now within same-day promise"] };
        });
        finishRun(runId, { type: "resolved", headline: "Recovering — ETA back within promise", rationale: "Stop resequenced with analyst approval." }, (d) => {
          const now = demoNow();
          setHealth(d, shipmentId, "recovering");
          d.shipments[shipmentId].headline = "Resequenced · ETA within same-day promise";
          notify(d, { at: now, kind: "agent", tone: "ok", title: `${shipmentId} resequenced`, body: "ETA back within same-day promise", target: { type: "shipment", id: shipmentId }, actor: people.analyst.name });
          ledger(d, "pending");
        });
        pushToast({ tone: "ok", title: `${shipmentId} back within promise`, href: `/shipments/${shipmentId}` });
        break;
      }

      case "reassign_courier":
      case "reroute":
      case "retry_delivery": {
        await step(runId, "reschedule_delivery", () => {
          updateWorld((d) => {
            const now = demoNow();
            const s = d.shipments[shipmentId];
            s.movement = anchorMovement(s, now);
            s.movement.holdAtM = undefined;
            s.movement.speedMps = Math.max(4, s.movement.speedMps * 0.6);
            addEvent(d, shipmentId, { at: now, title: action.title, detail: opts?.approvedBy ? `Approved by ${opts.approvedBy}` : "reschedule_delivery()", source: opts?.approvedBy ? "supervisor" : "agent", tone: "ok" });
          });
          return { status: "ok", summary: action.title, facts: ["Delivery plan updated", `New ETA shared with courier`] };
        });
        await step(runId, "contact_recipient", () => {
          updateWorld((d) => addEvent(d, shipmentId, { at: demoNow(), title: `Revised ETA sent via ${channel}`, source: "agent", tone: "agent" }));
          return { status: "ok", summary: `Revised ETA sent to ${recipient}`, facts: [] };
        });
        finishRun(runId, { type: "resolved", headline: `Recovering — ${action.title.toLowerCase()}`, rationale: "Action executed in the demo environment." }, (d) => {
          const now = demoNow();
          setHealth(d, shipmentId, "recovering");
          d.shipments[shipmentId].headline = action.title;
          rescore(d, shipmentId, now);
          notify(d, { at: now, kind: "agent", tone: "ok", title: `${shipmentId}: ${action.title}`, body: "Recovery in progress", target: { type: "shipment", id: shipmentId }, actor: "Dallal Agent" });
          ledger(d, "pending");
        });
        break;
      }

      default: {
        const tool: ToolName = action.tool as ToolName;
        await step(runId, tool, () => {
          updateWorld((d) => addEvent(d, shipmentId, { at: demoNow(), title: action.title, detail: `${action.tool}()`, source: action.approval === "analyst" ? "analyst" : "agent", tone: "agent" }));
          return { status: "ok", summary: action.title, facts: [] };
        });
        finishRun(runId, { type: "resolved", headline: action.title, rationale: "Action executed in the demo environment." }, (d) => {
          ledger(d, "pending");
          if (action.kind === "branch_escalation") setHealth(d, shipmentId, "recovering");
        });
      }
    }
    return getWorld().agentRuns[runId];
  },
};

export const describeWindow = (w: { start: number; end: number }) => `${fmtTime(w.start)}–${fmtTime(w.end)}`;
