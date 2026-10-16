import { api, lastEventId, planApi } from "@/lib/live/client";
import { resolveApiUrl } from "@/lib/live/config";
import { applyLiveRun } from "@/services/live/liveAgentService";
import { applyPlanToWorld } from "@/services/live/planEffects";
import { addEvent, notify } from "@/services/demo/mutations";
import { getWorld, demoNow, updateWorld } from "@/store/world";
import { getLive, setLive, setPlan } from "@/store/live";
import type { LiveEvent } from "@/types/live";

/**
 * Keeps the world store in step with the backend audit feed: replies, delivery states, timeouts, reviews, executions, outcomes.
 * Polling is deliberate (works through any proxy/Vercel; the backend also exposes SSE at /v1/events/stream).
 */
const REFRESH = new Set(["run_awaiting_response", "run_completed", "reply_received", "inquiry_timed_out", "message_status", "needs_human_review", "review_resolved", "inquiry_sent", "action_executed", "decision", "recipient_opted_out"]);
/** Single instance guard that survives hot reloads and React strict-mode double effects (a module-level flag would not). */
const G = globalThis as unknown as { __dallalFeed?: { gen: number; timer?: ReturnType<typeof setTimeout> } };
const pendingRefresh = new Map<string, ReturnType<typeof setTimeout>>();

async function refreshRun(runId: string) {
  const existing = getWorld().agentRuns[runId];
  if (!existing || existing.source !== "live") return;
  try {
    const res = await api.run(runId, existing.startedAt);
    applyLiveRun(res.ui);
  } catch {
    /* transient - the next event will refresh again */
  }
}

function scheduleRefresh(runId: string) {
  if (pendingRefresh.has(runId)) return;
  pendingRefresh.set(runId, setTimeout(() => {
    pendingRefresh.delete(runId);
    void refreshRun(runId);
  }, 250));
}

function describe(e: LiveEvent): { title: string; detail?: string; source: "agent" | "recipient" | "courier" | "system" | "supervisor"; tone: "agent" | "ok" | "warn" | "neutral" } | null {
  const p = e.payload as Record<string, string | number | null | undefined>;
  switch (e.kind) {
    case "inquiry_sent":
      return { title: `Agent asked the ${p.target} via WhatsApp (${(p.receipt as unknown as { mode?: string })?.mode ?? "sandbox"})`, detail: String(p.question ?? ""), source: "agent", tone: "agent" };
    case "reply_received":
      return { title: p.answer ? `Reply from the ${e.payload.target ?? "contact"}: ${p.answer}` : "Reply received but not understood - needs human review", detail: `interpreted via ${p.method} (confidence ${Number(p.confidence ?? 0).toFixed(2)})`, source: "recipient", tone: p.answer ? "ok" : "warn" };
    case "inquiry_timed_out":
      return { title: "No answer before the deadline - the silence is recorded as evidence", source: "system", tone: "warn" };
    case "needs_human_review":
      return { title: "Unclear reply held for human review", source: "system", tone: "warn" };
    case "action_executed":
      return { title: `Action executed (simulated): ${p.action}`, detail: `approved by ${p.approved_by}`, source: "agent", tone: "ok" };
    default:
      return null;
  }
}

const PLAN_COPY: Record<string, { title: string; tone: "info" | "warn" | "ok" }> = {
  plan_created: { title: "Coordinated recovery plan created", tone: "info" },
  plan_ready: { title: "Coordinated plan is ready for supervisor approval", tone: "info" },
  plan_executed: { title: "Coordinated plan approved and executed (simulated)", tone: "ok" },
  plan_rejected: { title: "Coordinated plan rejected by the supervisor", tone: "warn" },
};

function handlePlan(e: LiveEvent) {
  const copy = PLAN_COPY[e.kind];
  const p = e.payload as Record<string, string | undefined>;
  if (!copy || !p.incident_id) return;
  const incidentId = p.incident_id;
  void planApi.get(String(p.plan_id)).then((plan) => { setPlan(incidentId, plan); applyPlanToWorld(incidentId, plan); }).catch(() => undefined);
  if (e.kind === "plan_created") return; // the page that created it is already showing it
  updateWorld((w) => {
    if (w.incidents[incidentId]) notify(w, { at: demoNow(), kind: "agent", tone: copy.tone, title: copy.title, body: incidentId, target: { type: "incident", id: incidentId }, actor: "Dallal Agent" });
  });
}

function handle(e: LiveEvent) {
  handlePlan(e);
  const d = describe(e);
  if (d && e.subject_id && getWorld().shipments[e.subject_id]) {
    updateWorld((w) => {
      addEvent(w, e.subject_id as string, { at: demoNow(), title: d.title, detail: d.detail, source: d.source, tone: d.tone });
      if (e.kind === "reply_received" || e.kind === "inquiry_timed_out" || e.kind === "needs_human_review")
        notify(w, { at: demoNow(), kind: "agent", tone: d.tone === "warn" ? "warn" : "info", title: d.title, body: e.subject_id as string, target: { type: "shipment", id: e.subject_id as string }, actor: "Dallal Agent" });
    });
  }
  if (e.run_id && REFRESH.has(e.kind)) scheduleRefresh(e.run_id);
}

async function connect(): Promise<boolean> {
  try {
    const meta = await api.meta();
    const cur = getLive();
    setLive({ status: "connected", meta, lastError: undefined });
    if (cur.lastEventId === 0) setLive({ lastEventId: (await lastEventId()).id });
    return true;
  } catch (err) {
    setLive({ status: "offline", lastError: err instanceof Error ? err.message : "offline" });
    return false;
  }
}

async function loop(gen: number) {
  if (G.__dallalFeed?.gen !== gen) return; // a newer instance took over
  const live = getLive();
  if (live.status !== "connected") {
    await connect();
  } else {
    try {
      const events = await api.events(live.lastEventId);
      if (events.length) {
        setLive({ lastEventId: events[events.length - 1].id, events: [...getLive().events, ...events].slice(-300) });
        for (const e of events) handle(e);
      }
    } catch {
      setLive({ status: "offline" });
    }
  }
  if (G.__dallalFeed?.gen === gen) G.__dallalFeed.timer = setTimeout(() => void loop(gen), getLive().status === "connected" ? 1200 : 6000);
}

export function startLiveFeed() {
  if (typeof window === "undefined") return;
  if (!resolveApiUrl()) {
    setLive({ status: "offline", lastError: "no backend configured" });
    return;
  }
  if (G.__dallalFeed?.timer) clearTimeout(G.__dallalFeed.timer);
  const gen = (G.__dallalFeed?.gen ?? 0) + 1;
  G.__dallalFeed = { gen };
  setLive({ status: "unknown", lastEventId: 0 });
  void loop(gen);
}

export function stopLiveFeed() {
  if (G.__dallalFeed?.timer) clearTimeout(G.__dallalFeed.timer);
  G.__dallalFeed = { gen: (G.__dallalFeed?.gen ?? 0) + 1 };
}

/** Refresh one run immediately (used right after a UI action so the screen does not wait for the next poll). */
export async function refreshRunNow(runId: string) {
  await refreshRun(runId);
}
