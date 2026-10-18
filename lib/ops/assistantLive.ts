import { fmtTime } from "@/lib/time";
import { API_KEY, resolveApiUrl } from "@/lib/live/config";
import { caseStatus } from "@/lib/ops/narrative";
import { computeKpis, parcelHealth, summarize } from "@/lib/ops/derive";
import { clockNow } from "@/store/ops";
import type { AssistantMessage, OpsWorld } from "@/types/ops";

/**
 * The live operation as the assistant's backend sees it: drivers, parcels, cases, KPIs and recent activity from the operation, plus the ids of the
 * agent runs and plans. The backend adds its OWN records (runs, replies, plans, ledger) to this, so answers are grounded in both.
 */
export function buildAssistantSnapshot(w: OpsWorld) {
  const now = clockNow(w.clock);
  const k = computeKpis(w, now);
  const heroIds = new Set(w.cases.map((c) => c.parcelId));
  return {
    now: fmtTime(now),
    kpis: { active_parcels: k.active, at_risk: k.atRisk, disrupted: k.disrupted, with_manager: k.review, open_cases: k.open, resolved_by_dallal: k.resolved, drivers: Object.keys(w.drivers).length },
    drivers: summarize(w, now).map((r) => ({
      id: r.driver.id,
      name: r.driver.name,
      name_ar: r.driver.nameAr,
      vehicle: r.driver.vehicle,
      corridor: r.driver.corridorId,
      done: r.done,
      total: r.total,
      held: r.held,
      note: r.driver.note,
      parcels: r.parcels.map((p) => ({
        id: p.id,
        journey: heroIds.has(p.id) || p.exception || p.recovery ? w.journeys[p.id].slice(-3).map((e) => `${fmtTime(e.at)} ${e.title}${e.detail ? ` (${e.detail})` : ""}`) : undefined,
        seq: p.seq,
        district: p.address.district,
        health: parcelHealth(p, r.driver, now),
        headline: p.headline,
        exception: p.exception?.label,
        recovery: p.recovery?.label,
        value: p.valueSar,
        service: p.service,
      })),
    })),
    cases: w.cases.map((c) => ({ id: c.scenario, label: c.label, problem: `${c.problem.title} - ${c.problem.detail}`, parcel_id: c.parcelId, driver_id: c.driverId, status: caseStatus(w, c).label, run_id: c.runId, plan_id: c.planId })),
    plans: Object.keys(w.planBefore).map((id) => ({ id, before: w.planBefore[id] })),
    events: w.events.slice(0, 8).map((e) => ({ at: fmtTime(e.at), text: e.text })),
  };
}

export interface AssistantStatus {
  model: string;
  available: boolean;
  reason?: string | null;
  loaded?: boolean;
  seconds?: number;
}

const base = () => resolveApiUrl();
const headers = () => ({ "Content-Type": "application/json", ...(API_KEY ? { "X-API-Key": API_KEY } : {}) });

export async function assistantWarmup(): Promise<AssistantStatus> {
  const url = base();
  if (!url) return { model: "", available: false, reason: "no backend configured" };
  const res = await fetch(`${url}/v1/assistant/warmup`, { method: "POST", headers: headers() });
  if (!res.ok) throw new Error(`warm-up failed (${res.status})`);
  return (await res.json()) as AssistantStatus;
}

export type AssistantEvent =
  | { type: "start"; model: string }
  | { type: "context"; sources: NonNullable<AssistantMessage["sources"]>; runs: number; plans: number; chars: number }
  | { type: "delta"; text: string }
  | { type: "done"; model: string; latency_s: number; first_token_s: number | null; grounded: boolean; violations: string[] }
  | { type: "error"; code: string; message: string };

/** Stream an answer from the local model. Resolves when the stream ends; rejects on network failure or timeout (the caller falls back). */
export async function streamAssistant(question: string, history: { role: string; content: string }[], snapshot: unknown, onEvent: (e: AssistantEvent) => void, signal: AbortSignal, firstTokenTimeoutMs = 90_000): Promise<void> {
  const url = base();
  if (!url) throw new Error("no backend configured");
  const ctl = new AbortController();
  const onAbort = () => ctl.abort();
  signal.addEventListener("abort", onAbort);
  let first = false;
  const timer = setTimeout(() => {
    if (!first) ctl.abort();
  }, firstTokenTimeoutMs);
  try {
    const res = await fetch(`${url}/v1/assistant/chat`, { method: "POST", headers: headers(), body: JSON.stringify({ question, history, snapshot }), signal: ctl.signal });
    if (!res.ok || !res.body) throw new Error(`assistant request failed (${res.status})`);
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i: number;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (!line) continue;
        const ev = JSON.parse(line) as AssistantEvent;
        if (ev.type === "delta") first = true;
        onEvent(ev);
      }
    }
  } catch (e) {
    if (ctl.signal.aborted && !signal.aborted) throw new Error("The local model took too long to answer");
    throw e;
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", onAbort);
  }
}
