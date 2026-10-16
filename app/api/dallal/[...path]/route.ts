import type { NextRequest } from "next/server";

/**
 * Same-origin proxy to the Dallal backend (optional deployment mode).
 *
 * Browser -> /api/dallal/v1/... -> this function -> DALLAL_BACKEND_URL/v1/...  (adds the secret DALLAL_API_KEY server-side).
 * Why: the browser never holds the key, no CORS setup is needed, and the backend can stay private. Set on Vercel:
 *   DALLAL_BACKEND_URL=https://<your-backend-host>      (server-only)
 *   DALLAL_API_KEY=<same value as the backend's DALLAL_API_KEY>   (server-only, optional)
 *   NEXT_PUBLIC_DALLAL_API_URL=/api/dallal
 * Only /v1/* is forwarded, to the single configured origin. Without DALLAL_BACKEND_URL it answers 503 and the UI falls back to "Simulated".
 */
export const dynamic = "force-dynamic";

async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const base = (process.env.DALLAL_BACKEND_URL ?? "").replace(/\/$/, "");
  if (!base) return Response.json({ detail: "backend not configured" }, { status: 503 });
  const { path } = await ctx.params;
  if (path[0] !== "v1" || path.some((p) => p === ".." || p === ".")) return Response.json({ detail: "not found" }, { status: 404 });
  const url = `${base}/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers: Record<string, string> = {};
  const ct = req.headers.get("content-type");
  if (ct) headers["content-type"] = ct;
  const key = process.env.DALLAL_API_KEY;
  if (key) headers["x-api-key"] = key;
  const hasBody = req.method !== "GET" && req.method !== "HEAD";
  try {
    const res = await fetch(url, { method: req.method, headers, body: hasBody ? await req.text() : undefined, cache: "no-store", signal: AbortSignal.timeout(25_000) });
    return new Response(res.body, { status: res.status, headers: { "content-type": res.headers.get("content-type") ?? "application/json" } });
  } catch {
    return Response.json({ detail: "backend unreachable" }, { status: 502 });
  }
}

export const GET = forward;
export const POST = forward;
