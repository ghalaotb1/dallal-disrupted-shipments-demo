// One-time generator for real road geometry used by the demo scenario.
// Shipments are simulated; the roads they follow are real (OpenStreetMap via
// the public OSRM demo router). Output is committed so the app never depends
// on a routing service at runtime.
//
//   npm run routes:generate                 # all routes
//   npm run routes:generate -- --only A,B   # refresh selected keys
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const places = JSON.parse(readFileSync(join(root, "data/geo/places.json"), "utf8"));
const { routes } = JSON.parse(readFileSync(join(root, "data/geo/routeSpecs.json"), "utf8"));
const OSRM = "https://router.project-osrm.org/route/v1/driving/";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const toCoord = (ref) => (typeof ref === "string" ? places[ref].coord : ref);
const round = (n) => Math.round(n * 1e5) / 1e5;

// Douglas–Peucker simplification in local metres (≈ equirectangular at 26°N).
function simplify(points, toleranceM) {
  if (points.length < 3) return points;
  const k = 111320;
  const cosLat = Math.cos((26.35 * Math.PI) / 180);
  const xy = points.map(([lon, lat]) => [lon * k * cosLat, lat * k]);
  const keep = new Uint8Array(points.length);
  keep[0] = keep[points.length - 1] = 1;
  const stack = [[0, points.length - 1]];
  while (stack.length) {
    const [a, b] = stack.pop();
    let maxD = 0;
    let idx = -1;
    const [ax, ay] = xy[a];
    const [bx, by] = xy[b];
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy || 1;
    for (let i = a + 1; i < b; i++) {
      const [px, py] = xy[i];
      const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
      const d = Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
      if (d > maxD) {
        maxD = d;
        idx = i;
      }
    }
    if (maxD > toleranceM && idx > 0) {
      keep[idx] = 1;
      stack.push([a, idx], [idx, b]);
    }
  }
  return points.filter((_, i) => keep[i]);
}

const outFile = join(root, "data/geo/routes.generated.json");
const onlyArg = process.argv.indexOf("--only");
const only = onlyArg > -1 ? new Set(process.argv[onlyArg + 1].split(",")) : null;
const previous = only && existsSync(outFile) ? JSON.parse(readFileSync(outFile, "utf8")) : {};
const out = {};
for (const [key, spec] of Object.entries(routes)) {
  if (only && !only.has(key)) {
    if (previous[key]) out[key] = previous[key];
    continue;
  }
  const pts = [toCoord(spec.from), ...(spec.via ?? []), toCoord(spec.to)];
  const url = `${OSRM}${pts.map(([lon, lat]) => `${lon},${lat}`).join(";")}?overview=full&geometries=geojson&steps=true`;
  const res = await fetch(url, { headers: { "User-Agent": "dallal-demo-route-generator/1.0" } });
  if (!res.ok) throw new Error(`${key}: HTTP ${res.status}`);
  const json = await res.json();
  const route = json.routes?.[0];
  if (!route) throw new Error(`${key}: no route`);
  const coords = simplify(route.geometry.coordinates, 4).map(([lon, lat]) => [round(lon), round(lat)]);
  const roads = [];
  for (const leg of route.legs) {
    for (const step of leg.steps) {
      if (step.name && step.distance > 400 && roads.at(-1) !== step.name) roads.push(step.name);
    }
  }
  out[key] = {
    coords,
    distanceM: Math.round(route.distance),
    durationS: Math.round(route.duration),
    roads,
    destination: coords.at(-1),
  };
  console.log(`${key.padEnd(14)} ${(route.distance / 1000).toFixed(1).padStart(5)} km  ${String(coords.length).padStart(4)} pts  ${roads.slice(0, 4).join(" → ")}`);
  await sleep(1100);
}

writeFileSync(outFile, JSON.stringify(out) + "\n");
console.log(`\nWrote ${Object.keys(out).length} routes to data/geo/routes.generated.json`);
