import type { LngLat, RoutePath } from "@/types/domain";

const R = 6_371_008.8;
const toRad = (d: number) => (d * Math.PI) / 180;

export function haversine(a: LngLat, b: LngLat) {
  const dLat = toRad(b[1] - a[1]);
  const dLon = toRad(b[0] - a[0]);
  const s = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a[1])) * Math.cos(toRad(b[1])) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

export function buildPath(key: string, coords: LngLat[], roads: string[] = []): RoutePath {
  const cumulative = [0];
  for (let i = 1; i < coords.length; i++) cumulative.push(cumulative[i - 1] + haversine(coords[i - 1], coords[i]));
  return { key, coords, cumulative, lengthM: cumulative[cumulative.length - 1], roads };
}

function segmentIndex(path: RoutePath, d: number) {
  const c = path.cumulative;
  let lo = 0;
  let hi = c.length - 1;
  while (lo < hi - 1) {
    const mid = (lo + hi) >> 1;
    if (c[mid] <= d) lo = mid;
    else hi = mid;
  }
  return lo;
}

export function pointAt(path: RoutePath, distance: number): LngLat {
  const d = Math.max(0, Math.min(path.lengthM, distance));
  const i = segmentIndex(path, d);
  const a = path.coords[i];
  const b = path.coords[Math.min(i + 1, path.coords.length - 1)];
  const span = path.cumulative[i + 1] - path.cumulative[i] || 1;
  const t = (d - path.cumulative[i]) / span;
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

export function slicePath(path: RoutePath, from: number, to: number): LngLat[] {
  const a = Math.max(0, Math.min(path.lengthM, from));
  const b = Math.max(a, Math.min(path.lengthM, to));
  const out: LngLat[] = [pointAt(path, a)];
  for (let i = 0; i < path.coords.length; i++) {
    const c = path.cumulative[i];
    if (c > a && c < b) out.push(path.coords[i]);
  }
  out.push(pointAt(path, b));
  return out;
}

/** Closest distance-along-path to a coordinate (coarse; fine for scenario setup). */
export function projectOnPath(path: RoutePath, p: LngLat) {
  let best = { d: 0, gap: Infinity };
  const steps = Math.ceil(path.lengthM / 20);
  for (let i = 0; i <= steps; i++) {
    const d = (i / steps) * path.lengthM;
    const gap = haversine(pointAt(path, d), p);
    if (gap < best.gap) best = { d, gap };
  }
  return best;
}

export function circlePolygon(center: LngLat, radiusM: number, steps = 64): LngLat[] {
  const coords: LngLat[] = [];
  const latR = radiusM / 111_320;
  const lonR = radiusM / (111_320 * Math.cos(toRad(center[1])));
  for (let i = 0; i <= steps; i++) {
    const t = (i / steps) * Math.PI * 2;
    coords.push([center[0] + lonR * Math.cos(t), center[1] + latR * Math.sin(t)]);
  }
  return coords;
}

export function boundsOf(points: LngLat[]): [LngLat, LngLat] {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const [x, y] of points) {
    minX = Math.min(minX, x);
    minY = Math.min(minY, y);
    maxX = Math.max(maxX, x);
    maxY = Math.max(maxY, y);
  }
  return [
    [minX, minY],
    [maxX, maxY],
  ];
}
