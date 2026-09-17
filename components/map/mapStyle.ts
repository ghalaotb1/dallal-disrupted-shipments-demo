import type { StyleSpecification } from "maplibre-gl";

/**
 * Basemap: OpenStreetMap vector tiles via OpenFreeMap (no key), CARTO Positron as
 * fallback, and a local "network only" style if both are unreachable (e.g. venue
 * Wi-Fi). The style is re-tinted into Dallal's cool light palette.
 */

const SOURCES = [
  { id: "openfreemap", url: "https://tiles.openfreemap.org/styles/positron" },
  { id: "carto", url: "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json" },
] as const;

export type BasemapSource = (typeof SOURCES)[number]["id"] | "offline";

const PALETTE = {
  background: "#eef2f7",
  land: "#eaeff5",
  park: "#e3ece6",
  water: "#cddff1",
  waterLabel: "#5a7fb0",
  building: "#e1e7ef",
  roadMinor: "#ffffff",
  roadMajor: "#ffffff",
  roadCasing: "#d5dde8",
  rail: "#d3dbe6",
  boundary: "#b7c3d3",
  label: "#4f5e75",
  labelMinor: "#7b8aa0",
  halo: "#f7f9fc",
};

async function fetchWithTimeout(url: string, ms: number) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  try {
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as StyleSpecification;
  } finally {
    clearTimeout(timer);
  }
}

export async function loadBasemap(): Promise<{ style: StyleSpecification; source: BasemapSource }> {
  for (const src of SOURCES) {
    try {
      const style = await fetchWithTimeout(src.url, 6000);
      return { style: tint(style), source: src.id };
    } catch {
      // try next provider
    }
  }
  return { style: offlineStyle(), source: "offline" };
}

export function offlineStyle(): StyleSpecification {
  return { version: 8, sources: {}, layers: [{ id: "background", type: "background", paint: { "background-color": PALETTE.background } }] };
}

function tint(style: StyleSpecification): StyleSpecification {
  const layers = style.layers.filter((l) => !/shield|poi|housenum|aerialway|ferry/i.test(l.id));
  for (const layer of layers) {
    const id = layer.id.toLowerCase();
    const paint = (layer.paint ?? {}) as Record<string, unknown>;
    const layout = (layer.layout ?? {}) as Record<string, unknown>;
    switch (layer.type) {
      case "background":
        paint["background-color"] = PALETTE.background;
        break;
      case "fill":
        if (id.includes("water")) paint["fill-color"] = PALETTE.water;
        else if (id.includes("park") || id.includes("wood") || id.includes("grass") || id.includes("landcover")) paint["fill-color"] = PALETTE.park;
        else if (id.includes("building")) {
          paint["fill-color"] = PALETTE.building;
          paint["fill-outline-color"] = PALETTE.roadCasing;
        } else if (id.includes("aeroway") || id.includes("pier")) paint["fill-color"] = PALETTE.land;
        else paint["fill-color"] = PALETTE.land;
        break;
      case "line":
        if (id.includes("water")) paint["line-color"] = PALETTE.water;
        else if (id.includes("boundary") || id.includes("admin")) paint["line-color"] = PALETTE.boundary;
        else if (id.includes("rail")) paint["line-color"] = PALETTE.rail;
        else if (id.includes("casing") || id.includes("case") || id.includes("subtle")) paint["line-color"] = PALETTE.roadCasing;
        else if (id.includes("motorway") || id.includes("major") || id.includes("trunk") || id.includes("primary")) paint["line-color"] = PALETTE.roadMajor;
        else if (id.includes("highway") || id.includes("road") || id.includes("street") || id.includes("path") || id.includes("tunnel") || id.includes("bridge")) paint["line-color"] = PALETTE.roadMinor;
        else if (id.includes("aeroway")) paint["line-color"] = PALETTE.roadMinor;
        break;
      case "symbol":
        if (id.includes("water")) paint["text-color"] = PALETTE.waterLabel;
        else if (id.includes("city") || id.includes("town") || id.includes("state") || id.includes("country") || id.includes("place")) paint["text-color"] = PALETTE.label;
        else paint["text-color"] = PALETTE.labelMinor;
        paint["text-halo-color"] = PALETTE.halo;
        paint["text-halo-width"] = 1.4;
        if (id.includes("country") || id.includes("state")) layout.visibility = "none";
        break;
    }
    (layer as { paint?: unknown }).paint = paint;
    (layer as { layout?: unknown }).layout = layout;
  }
  return { ...style, layers };
}
