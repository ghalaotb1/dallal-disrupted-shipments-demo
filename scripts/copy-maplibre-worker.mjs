// MapLibre GL JS v6 ships its web worker as separate ES modules.
// Bundlers can't see the dynamic worker URL, so we serve the worker
// (and the shared chunk it imports) as static files and point
// maplibregl.setWorkerUrl() at them. Runs before `dev` and `build`.
import { copyFileSync, mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = join(root, "node_modules", "maplibre-gl", "dist");
const version = JSON.parse(readFileSync(join(root, "node_modules", "maplibre-gl", "package.json"), "utf8")).version;
const dest = join(root, "public", "vendor", "maplibre-gl");

mkdirSync(dest, { recursive: true });
for (const file of ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"]) {
  copyFileSync(join(src, file), join(dest, file));
}
console.log(`maplibre-gl ${version} worker copied to public/vendor/maplibre-gl`);
