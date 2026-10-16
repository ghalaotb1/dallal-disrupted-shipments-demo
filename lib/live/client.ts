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
  review: (inquiryId: string, body: { answer_id: string | null; reviewer: string }) => request<RunEnvelope>("POST", `/v1/inquiries/${encodeURIComponent(inquiryId)}/review`, body),
  inquiries: (subjectId: string) => request<LiveInquiry[]>("GET", `/v1/inquiries?subject_id=${encodeURIComponent(subjectId)}`),
};

export const lastEventId = () => request<{ id: number }>("GET", "/v1/events/last", undefined, 4000);
