/**
 * Where the live Dallal backend lives.
 *  - NEXT_PUBLIC_DALLAL_API_URL (build-time) - set on Vercel for the hosted demo
 *  - ?backend=<url> once on any page - remembered in localStorage (lets judges point a hosted frontend at a backend they run)
 *  - in `next dev` with neither, http://localhost:8000
 * With no backend reachable the app keeps working on the in-browser prototype logic and says so ("Simulated").
 */
const KEY = "dallal.backend";

function remembered(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const q = new URLSearchParams(window.location.search).get("backend");
    if (q !== null) {
      if (q === "off" || q === "") window.localStorage.removeItem(KEY);
      else window.localStorage.setItem(KEY, q);
    }
    return window.localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function resolveApiUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_DALLAL_API_URL ?? "";
  const url = remembered() || fromEnv || (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "");
  return url.replace(/\/$/, "");
}

export const API_KEY = process.env.NEXT_PUBLIC_DALLAL_API_KEY ?? "";
