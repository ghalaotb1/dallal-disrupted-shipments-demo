import { API_KEY, resolveApiUrl } from "@/lib/live/config";
import type { AgentRun } from "@/types/domain";
import type { LiveCase, LiveEvent, LiveInquiry, LiveMeta } from "@/types/live";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown, timeoutMs = 15_000): Promise<T> {
  const base = resolveApiUrl();
  if (!base) throw new ApiError("no backend configured", 0);
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeoutMs);
  try {
    const res = await fetch(`${base}${path}`, {
      method,
      signal: ctl.signal,
      headers: { ...(body ? { "Content-Type": "application/json" } : {}), ...(API_KEY ? { "X-API-Key": API_KEY } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const j = await res.json();
        detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
      } catch {}
      throw new ApiError(detail, res.status);
    }
    return (await res.json()) as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError(e instanceof Error ? e.message : "network error", 0);
  } finally {
    clearTimeout(timer);
  }
}

export interface RunEnvelope {
  run: { run_id: string; inquiries_live: LiveInquiry[] } & Record<string, unknown>;
  ui: AgentRun;
}

export const api = {
  demoReset: () => request<{ cleared: Record<string, number> }>("POST", "/v1/admin/demo-reset", undefined, 8000),
  meta: () => request<LiveMeta>("GET", "/v1/meta", undefined, 4000),
  frontendRun: (c: LiveCase, lang = "ar") => request<RunEnvelope>("POST", "/v1/frontend/runs", { case: c, lang }),
  run: (id: string, startedAtMs: number) => request<RunEnvelope>("GET", `/v1/runs/${encodeURIComponent(id)}?started_at_ms=${Math.round(startedAtMs)}`),
  execute: (id: string, body: { approved_by?: string; role?: string; action?: string }) =>
    request<{ action_id: string; action: string; status: string; detail: string; external_effect: boolean; outcome: string }>("POST", `/v1/runs/${encodeURIComponent(id)}/execute`, body),
  outcome: (actionId: string, body: { kind: string; source: string; note?: string }) => request<unknown>("POST", `/v1/actions/${encodeURIComponent(actionId)}/outcome`, body),
  events: (after: number) => request<LiveEvent[]>("GET", `/v1/events?after=${after}&limit=100`, undefined, 6000),
  sandboxReply: (body: { inquiry_id: string; kind: "button" | "text" | "location" | "image"; answer_id?: string; text?: string; lat?: number; lng?: number }) =>
    request<Record<string, unknown>>("POST", "/v1/sandbox/reply", body),
  expire: (inquiryId: string) => request<RunEnvelope>("POST", `/v1/inquiries/${encodeURIComponent(inquiryId)}/expire`),
  sendApprove: (inquiryId: string, body: { approver: string; role: string }) => request<RunEnvelope>("POST", `/v1/inquiries/${encodeURIComponent(inquiryId)}/send/approve`, body),
  sendDecline: (inquiryId: string, body: { approver: string; role: string }) => request<RunEnvelope>("POST", `/v1/inquiries/${encodeURIComponent(inquiryId)}/send/decline`, body),
  review: (inquiryId: string, body: { answer_id: string | null; reviewer: string }) => request<RunEnvelope>("POST", `/v1/inquiries/${encodeURIComponent(inquiryId)}/review`, body),
  inquiries: (subjectId: string) => request<LiveInquiry[]>("GET", `/v1/inquiries?subject_id=${encodeURIComponent(subjectId)}`),
};

export const lastEventId = () => request<{ id: number }>("GET", "/v1/events/last", undefined, 4000);

import type { LiveReplay2, LiveReplayOutcome, LiveModelCard, LiveModelSummary, LivePlan, LiveReplay, LiveScore, PlanSnapshot } from "@/types/live";

export const planApi = {
  create: (snapshot: PlanSnapshot, lang = "ar") => request<LivePlan>("POST", "/v1/frontend/incidents/plan", { snapshot, lang }),
  get: (id: string) => request<LivePlan>("GET", `/v1/plans/${encodeURIComponent(id)}`),
  decide: (id: string, body: { decision: "approve" | "reject"; by: string; role: string; note?: string }) => request<LivePlan>("POST", `/v1/plans/${encodeURIComponent(id)}/decision`, body),
};

export const modelApi = {
  list: () => request<LiveModelSummary[]>("GET", "/v1/models"),
  card: (id: string) => request<LiveModelCard>("GET", `/v1/models/${encodeURIComponent(id)}`),
  score: (id: string, features: Record<string, number>) => request<LiveScore>("POST", `/v1/models/${encodeURIComponent(id)}/score`, { features }),
  replay: (id: string, n = 8, seed = 0) => request<LiveReplay>("GET", `/v1/models/${encodeURIComponent(id)}/replay?n=${n}&seed=${seed}`),
  replayStatus: () => request<{ available: boolean; reason: string | null }>("GET", "/v1/replay/lade/status"),
  replayRun: (seed: number) => request<LiveReplay2>("POST", `/v1/replay/lade?seed=${seed}`, undefined, 120_000),
  replayOutcome: (id: string) => request<LiveReplayOutcome>("GET", `/v1/replay/lade/${encodeURIComponent(id)}/outcome`),
  experiment: <T,>(name: string) => request<T>("GET", `/v1/experiments/${name}`),
};
