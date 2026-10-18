"use client";

import { useEffect, useRef, useState } from "react";
import { LngLatBounds, Map as MLMap, Marker, setWorkerUrl, type GeoJSONSource } from "maplibre-gl";
import { el, MarkerLayer } from "@/components/ops/markerLayer";
import "maplibre-gl/dist/maplibre-gl.css";
import { CloudOff } from "lucide-react";
import { NETWORK_BOUNDS, places, routes } from "@/data/network";
import { circlePolygon, slicePath } from "@/lib/geo";
import { isHeld, parcelHealth, vanDistance, vanPosition } from "@/lib/ops/derive";
import { useOpsNow } from "@/hooks/useOpsNow";
import { loadBasemap, type BasemapSource } from "@/components/map/mapStyle";
import { HEALTH } from "@/components/common/status";
import { setUi, useOps, useOpsUi } from "@/store/ops";
import type { ShipmentHealth } from "@/types/domain";
import type { Driver, OpsWorld, Parcel } from "@/types/ops";

if (typeof window !== "undefined") setWorkerUrl("/vendor/maplibre-gl/maplibre-gl-worker.mjs");

type FC = GeoJSON.FeatureCollection;
const empty: FC = { type: "FeatureCollection", features: [] };
const RANK: Record<ShipmentHealth, number> = { disrupted: 6, review: 5, at_risk: 4, recovering: 3, on_track: 2, recovered: 1, prevented: 1, delivered: 0 };
const worstOf = (hs: ShipmentHealth[]): ShipmentHealth => hs.reduce<ShipmentHealth>((a, h) => (RANK[h] > RANK[a] ? h : a), "delivered");

function buildData(w: Pick<OpsWorld, "drivers" | "parcels" | "blockage">, now: number, selectedDriver: string | null, selectedParcel: string | null) {
  const lines: GeoJSON.Feature[] = [];
  const traveled: GeoJSON.Feature[] = [];
  const stops: GeoJSON.Feature[] = [];
  const recovery: GeoJSON.Feature[] = [];
  for (const d of Object.values(w.drivers)) {
    const r = routes[d.routeKey];
    if (!r) continue;
    const ps = Object.values(w.parcels).filter((p) => p.driverId === d.id);
    const hs = ps.map((p) => parcelHealth(p, d, now));
    const worst = worstOf(hs.filter((h) => h !== "delivered" && h !== "prevented" && h !== "recovered"));
    const issue = worst === "disrupted" || worst === "at_risk" || worst === "review";
    const sel = d.id === selectedDriver;
    lines.push({ type: "Feature", properties: { id: d.id, color: issue ? HEALTH[worst].map : sel ? "#2f6be6" : "#7f93b2", width: sel ? 5 : issue ? 4 : 3, sel: sel ? 1 : 0, issue: issue ? 1 : 0 }, geometry: { type: "LineString", coordinates: r.coords } });
    if (sel) traveled.push({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: slicePath(r, 0, vanDistance(d, now)) } });
    ps.forEach((p, i) => {
      const h = hs[i];
      if (p.recovery && (p.recovery.kind === "spare" || p.recovery.kind === "pickup")) {
        const from = p.recovery.kind === "spare" ? places["br-khobar"].coord : (places[Object.keys(places).find((k) => places[k].name === p.recovery!.label) ?? ""]?.coord ?? places["br-khobar"].coord);
        recovery.push({ type: "Feature", properties: { kind: p.recovery.kind }, geometry: { type: "LineString", coordinates: [from, p.dest] } });
      }
      stops.push({
        type: "Feature",
        properties: { id: p.id, color: HEALTH[h].map, r: p.id === selectedParcel ? 8 : sel ? 6 : h === "delivered" ? 3 : 4.5, faded: h === "delivered" ? 1 : 0 },
        geometry: { type: "Point", coordinates: p.dest },
      });
    });
  }
  const blockage: FC = w.blockage ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "Polygon", coordinates: [circlePolygon(w.blockage.coord, w.blockage.radiusM)] } }] } : empty;
  return { lines: { type: "FeatureCollection", features: lines } as FC, traveled: { type: "FeatureCollection", features: traveled } as FC, stops: { type: "FeatureCollection", features: stops } as FC, recovery: { type: "FeatureCollection", features: recovery } as FC, blockage };
}

export default function OpsMap() {
  const box = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const layerRef = useRef<MarkerLayer | null>(null);
  const [ready, setReady] = useState(false);
  const [source, setSource] = useState<BasemapSource | null>(null);
  const now = useOpsNow(600);
  const drivers = useOps((s) => s.drivers);
  const parcels = useOps((s) => s.parcels);
  const blockage = useOps((s) => s.blockage);
  const active = useOps((s) => s.active);
  const generation = useOps((s) => s.generation);
  const selDriver = useOpsUi((s) => s.selectedDriverId);
  const selParcel = useOpsUi((s) => s.selectedParcelId);

  // ── create the map once ───────────────────────────────────────────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    let map: MLMap | null = null;
    void loadBasemap().then(({ style, source: src }) => {
      if (cancelled || !box.current) return;
      setSource(src);
      map = new MLMap({ container: box.current, style, bounds: NETWORK_BOUNDS, fitBoundsOptions: { padding: 40 }, attributionControl: { compact: true }, dragRotate: false, pitchWithRotate: false });
      mapRef.current = map;
      layerRef.current = new MarkerLayer(map);
      if (process.env.NODE_ENV !== "production") (window as unknown as { __opsMap?: MLMap }).__opsMap = map; // handy for browser debugging in dev
      map.touchZoomRotate.disableRotation();
      // "style.load" (not "load"): routes, stops and vans must appear even while basemap tiles are still arriving or the venue network is slow.
      map.once("style.load", () => {
        if (!map) return;
        for (const id of ["lines", "traveled", "stops", "recovery", "blockage"]) map.addSource(id, { type: "geojson", data: empty });
        map.addLayer({ id: "blockage-fill", type: "fill", source: "blockage", paint: { "fill-color": "#df3b30", "fill-opacity": 0.2 } });
        map.addLayer({ id: "blockage-line", type: "line", source: "blockage", paint: { "line-color": "#df3b30", "line-width": 2, "line-dasharray": [2, 2] } });
        map.addLayer({ id: "route-casing", type: "line", source: "lines", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#ffffff", "line-width": ["+", ["get", "width"], 3], "line-opacity": 0.9 } });
        map.addLayer({ id: "route-line", type: "line", source: "lines", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": ["get", "color"], "line-width": ["get", "width"], "line-opacity": ["case", ["==", ["get", "issue"], 1], 0.95, ["==", ["get", "sel"], 1], 0.95, 0.7] } });
        map.addLayer({ id: "route-traveled", type: "line", source: "traveled", layout: { "line-cap": "round" }, paint: { "line-color": "#ffffff", "line-width": 2, "line-opacity": 0.65 } });
        map.addLayer({ id: "recovery-line", type: "line", source: "recovery", paint: { "line-color": "#2f6be6", "line-width": 1.6, "line-opacity": 0.55, "line-dasharray": [1.5, 2.5] } });
        map.addLayer({ id: "stops-circle", type: "circle", source: "stops", paint: { "circle-radius": ["get", "r"], "circle-color": ["get", "color"], "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.8, "circle-opacity": ["case", ["==", ["get", "faded"], 1], 0.55, 1] } });
        map.on("click", "stops-circle", (e) => {
          const f = e.features?.[0];
          const p = f ? useOps.getState().parcels[String(f.properties?.id)] : undefined;
          if (p) setUi({ selectedParcelId: p.id, selectedDriverId: p.driverId });
        });
        map.on("click", "route-line", (e) => {
          const id = e.features?.[0]?.properties?.id;
          if (id) setUi({ selectedDriverId: String(id) });
        });
        for (const l of ["stops-circle", "route-line"]) {
          map.on("mouseenter", l, () => map && (map.getCanvas().style.cursor = "pointer"));
          map.on("mouseleave", l, () => map && (map.getCanvas().style.cursor = ""));
        }
        // static places
        for (const p of Object.values(places)) {
          const major = p.kind === "hub" || p.kind === "branch";
          const node = el(major ? `<span class="block size-3 rounded-[4px] bg-ink ring-2 ring-white shadow"></span><span class="mt-0.5 block rounded bg-white/90 px-1 text-[10px] font-semibold text-ink-2 whitespace-nowrap shadow-sm">${p.short}</span>` : `<span class="block size-2.5 rounded-[3px] bg-white ring-1 ring-ink-4 shadow"></span>`, "flex flex-col items-center pointer-events-none");
          new Marker({ element: node }).setLngLat(p.coord).addTo(map);
        }
        setReady(true);
      });
    });
    return () => {
      cancelled = true;
      layerRef.current?.clear();
      layerRef.current = null;
      map?.remove();
      mapRef.current = null;
      setReady(false);
    };
  }, []);

  // ── data layers ───────────────────────────────────────────────────────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const d = buildData({ drivers, parcels, blockage }, now, selDriver, selParcel);
    (map.getSource("lines") as GeoJSONSource | undefined)?.setData(d.lines);
    (map.getSource("traveled") as GeoJSONSource | undefined)?.setData(d.traveled);
    (map.getSource("stops") as GeoJSONSource | undefined)?.setData(d.stops);
    (map.getSource("recovery") as GeoJSONSource | undefined)?.setData(d.recovery);
    (map.getSource("blockage") as GeoJSONSource | undefined)?.setData(d.blockage);
  }, [ready, drivers, parcels, blockage, now, selDriver, selParcel]);

  // ── vans and numbered stops (DOM markers) ─────────────────────────────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const layer = layerRef.current;
    if (!layer) return;
    layer.begin();
    const upsert = layer.upsert.bind(layer);
    const stateOf = (d: Driver) => {
      const hs = Object.values(parcels).filter((p) => p.driverId === d.id).map((p) => parcelHealth(p, d, now)).filter((h) => h !== "delivered" && h !== "prevented" && h !== "recovered");
      return worstOf(hs);
    };
    for (const d of Object.values(drivers)) {
      const worst = stateOf(d);
      const issue = worst === "disrupted" || worst === "at_risk" || worst === "review";
      const sel = d.id === selDriver;
      upsert(
        `van:${d.id}`,
        vanPosition(d, now),
        () => {
          const n = el("", "flex flex-col items-center cursor-pointer");
          n.addEventListener("click", (e) => {
            e.stopPropagation();
            setUi({ selectedDriverId: d.id });
          });
          return n;
        },
        (n) => {
          const color = issue ? HEALTH[worst].map : "#0f1e36";
          n.innerHTML = `<span class="relative flex size-7 items-center justify-center rounded-full text-[11px] font-bold text-white shadow-[0_2px_6px_rgb(15_30_54/0.35)] ring-[2.5px] ${sel ? "ring-brand-600" : "ring-white"}" style="background:${color}">${d.name[0]}${isHeld(d, now) ? '<span class="absolute -top-1 -right-1 size-3 rounded-full bg-crit-500 ring-2 ring-white"></span>' : ""}</span><span class="mt-0.5 rounded bg-ink px-1 text-[10px] font-semibold text-white whitespace-nowrap">${d.name}</span>`;
        },
        sel ? 40 : issue ? 30 : 20,
      );
    }
    // numbered stops of the selected route and the case parcel
    const showIds = new Set<string>();
    if (selDriver) Object.values(parcels).filter((p) => p.driverId === selDriver).forEach((p) => showIds.add(p.id));
    if (active) showIds.add(active.parcelId);
    for (const id of showIds) {
      const p: Parcel | undefined = parcels[id];
      if (!p) continue;
      const d = drivers[p.driverId];
      const h = parcelHealth(p, d, now);
      const hero = active?.parcelId === id;
      const sel = selParcel === id;
      upsert(
        `stop:${id}`,
        p.dest,
        () => {
          const n = el("", "cursor-pointer");
          n.addEventListener("click", (e) => {
            e.stopPropagation();
            setUi({ selectedParcelId: id, selectedDriverId: p.driverId });
          });
          return n;
        },
        (n) => {
          n.innerHTML = `<span class="relative flex ${hero ? "size-6" : "size-[18px]"} items-center justify-center rounded-full text-[10px] font-bold text-white ring-2 ${sel ? "ring-brand-600" : "ring-white"} shadow-[0_1px_4px_rgb(15_30_54/0.4)]" style="background:${HEALTH[h].map}">${p.seq}${hero || sel ? `<span class="absolute top-full left-1/2 mt-0.5 -translate-x-1/2 rounded bg-white px-1 font-mono text-[10px] font-semibold text-ink shadow whitespace-nowrap">${p.id}</span>` : ""}</span>`;
        },
        hero || sel ? 35 : 10,
      );
    }
    if (blockage) {
      upsert(
        "blockage",
        blockage.coord,
        () => el(`<span class="rounded-md bg-crit-700 px-1.5 py-0.5 text-[10.5px] font-semibold text-white shadow whitespace-nowrap">${blockage.label}</span>`, "pointer-events-none"),
        () => undefined,
        25,
        "left",
        [26, 0],
      );
    }
    layer.end();
  }, [ready, drivers, parcels, blockage, now, selDriver, selParcel, active]);

  // ── camera: follow the story ──────────────────────────────────────────────────────────────────────────────────────
  const focusKey = `${generation}:${selDriver ?? ""}:${active?.scenario ?? ""}`;
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const b = new LngLatBounds();
    const w = useOps.getState();
    if (active?.scenario === "C" && (!selDriver || active.affectedDriverIds.includes(selDriver))) {
      for (const id of active.affectedDriverIds) routes[w.drivers[id].routeKey]?.coords.slice(0, Math.ceil(routes[w.drivers[id].routeKey].coords.length * 0.85)).forEach((c) => b.extend(c));
    } else if (selDriver) {
      routes[w.drivers[selDriver]?.routeKey]?.coords.forEach((c) => b.extend(c));
    } else {
      b.extend(NETWORK_BOUNDS[0]);
      b.extend(NETWORK_BOUNDS[1]);
    }
    if (!b.isEmpty()) map.fitBounds(b, { padding: { top: 70, bottom: 60, left: 50, right: 50 }, duration: 900, maxZoom: 14.2 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, focusKey]);

  return (
    <div className="relative size-full overflow-hidden bg-muted">
      <div className="absolute inset-0">
        <div ref={box} className="size-full" />
      </div>
      {!ready ? <div className="skeleton absolute inset-0" aria-label="Loading map" /> : null}
      {source === "offline" ? (
        <div className="absolute bottom-3 left-3 flex items-center gap-1.5 rounded-lg bg-surface/95 px-2.5 py-1.5 text-xs text-ink-3 shadow-float">
          <CloudOff className="size-3.5" aria-hidden /> Basemap offline · routes and stops still shown
        </div>
      ) : null}
    </div>
  );
}
