"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { LngLatBounds, Map as MLMap, Marker, setWorkerUrl, type FilterSpecification, type GeoJSONSource, type LngLatLike, type PositionAnchor } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useShallow } from "zustand/react/shallow";
import { CloudOff, LocateFixed, Minus, Plus } from "lucide-react";
import { getRoute, NETWORK_BOUNDS, places } from "@/data/network";
import { cn } from "@/lib/cn";
import { shipmentPosition } from "@/services/logic/movement";
import { clockNow, getWorld, useWorld } from "@/store/world";
import type { MapFocus } from "@/store/ui";
import type { LngLat, Shipment } from "@/types/domain";
import { loadBasemap, type BasemapSource } from "@/components/map/mapStyle";
import { buildRouteFeatures, incidentZoneFeatures, type MapVariant } from "@/components/map/routeFeatures";
import { DestinationPin, FacilityMarker, IncidentMarker, ShipmentMarker } from "@/components/map/markers";
import { MapLegend } from "@/components/map/MapLegend";

if (typeof window !== "undefined") setWorkerUrl("/vendor/maplibre-gl/maplibre-gl-worker.mjs");

const FLOW_DASHES: number[][] = [
  [0, 4, 3],
  [0.5, 4, 2.5],
  [1, 4, 2],
  [1.5, 4, 1.5],
  [2, 4, 1],
  [2.5, 4, 0.5],
  [3, 4, 0],
  [0, 0.5, 3, 3.5],
  [0, 1, 3, 3],
  [0, 1.5, 3, 2.5],
  [0, 2, 3, 2],
  [0, 2.5, 3, 1.5],
  [0, 3, 3, 1],
  [0, 3.5, 3, 0.5],
];

/** MapLibre markers per map instance, so the animation loop can move them without React renders. */
const markerRegistry = new WeakMap<MLMap, Map<string, Marker>>();
const registryFor = (map: MLMap) => {
  let r = markerRegistry.get(map);
  if (!r) markerRegistry.set(map, (r = new Map()));
  return r;
};

/** A DOM marker owned by React: MapLibre positions it, React renders its content through a portal. */
function MapMarker({ map, markerKey, lngLat, anchor = "center", offset, children }: { map: MLMap; markerKey: string; lngLat: LngLatLike; anchor?: PositionAnchor; offset?: [number, number]; children: ReactNode }) {
  const [el] = useState(() => document.createElement("div"));
  const initial = useRef({ lngLat, anchor, offset });
  useEffect(() => {
    const { lngLat: position, anchor: a, offset: o } = initial.current;
    const marker = new Marker({ element: el, anchor: a, offset: o }).setLngLat(position).addTo(map);
    const registry = registryFor(map);
    registry.set(markerKey, marker);
    return () => {
      marker.remove();
      if (registry.get(markerKey) === marker) registry.delete(markerKey);
    };
  }, [map, el, markerKey]);
  return createPortal(children, el);
}

export interface NetworkMapProps {
  variant: MapVariant;
  /** Restrict individually drawn shipments to these ids (shipment & incident views). */
  shipmentIds?: string[];
  /** Emphasise these ids and dim everything else. */
  highlightIds?: string[] | null;
  selectedId?: string | null;
  onSelectShipment?: (id: string | null) => void;
  selectedFacilityId?: string | null;
  onSelectFacility?: (id: string | null) => void;
  onSelectIncident?: (id: string) => void;
  incidentId?: string | null;
  focus?: MapFocus | null;
  className?: string;
  children?: ReactNode;
  legend?: boolean;
  compactControls?: boolean;
  /** Shift zoom controls left when a floating card occupies the top-right corner. */
  controlsOffset?: boolean;
}

const EMPTY: string[] = [];

export default function NetworkMap({
  variant,
  shipmentIds,
  highlightIds,
  selectedId = null,
  onSelectShipment,
  selectedFacilityId = null,
  onSelectFacility,
  onSelectIncident,
  incidentId,
  focus,
  className,
  children,
  legend = true,
  compactControls,
  controlsOffset,
}: NetworkMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [map, setMap] = useState<MLMap | null>(null);
  const [basemap, setBasemap] = useState<BasemapSource | null>(null);
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState(11.5);
  const [reducedMotion] = useState(() => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  // ── Which shipments get individual markers ──────────────────────────────
  const movingIds = useWorld(
    useShallow((w) =>
      Object.values(w.shipments)
        .filter((s) => !s.closed && s.movement.mode === "route" && (!shipmentIds || shipmentIds.includes(s.id)))
        .map((s) => s.id),
    ),
  );
  const facilityHeld = useWorld(
    useShallow((w) => {
      const out: Record<string, string[]> = {};
      for (const s of Object.values(w.shipments)) {
        if (s.closed || s.movement.mode !== "facility" || !s.movement.facilityId) continue;
        if (shipmentIds && !shipmentIds.includes(s.id)) continue;
        (out[s.movement.facilityId] ??= []).push(s.id);
      }
      return Object.entries(out).map(([k, v]) => `${k}:${v.join(",")}`);
    }),
  );
  const heldByFacility = useMemo(() => Object.fromEntries(facilityHeld.map((e) => [e.split(":")[0], e.split(":")[1].split(",")])), [facilityHeld]);
  const shipments = useWorld((w) => w.shipments);
  const incidents = useWorld((w) => w.incidents);
  const visibleIncidents = useMemo(
    () => Object.values(incidents).filter((i) => i.status !== "resolved" && (!incidentId || i.id === incidentId) && (variant !== "shipment" || shipments[shipmentIds?.[0] ?? ""]?.incident?.id === i.id)),
    [incidents, incidentId, variant, shipments, shipmentIds],
  );
  const facilityIds = useMemo(() => {
    if (variant === "overview") return Object.keys(places);
    const ids = new Set<string>(Object.keys(heldByFacility));
    for (const id of shipmentIds ?? EMPTY) {
      const s = shipments[id];
      if (s) ids.add(s.originId);
    }
    return [...ids];
  }, [variant, heldByFacility, shipmentIds, shipments]);
  const pinTarget = variant === "shipment" ? shipmentIds?.[0] : selectedId;
  const highlightSet = useMemo(() => (highlightIds ? new Set(highlightIds) : null), [highlightIds]);

  const latest = useRef({ variant, selectedId, highlightSet, movingIds, visibleIncidents, shipmentIds, pinTarget });
  useLayoutEffect(() => {
    latest.current = { variant, selectedId, highlightSet, movingIds, visibleIncidents, shipmentIds, pinTarget };
  });

  // ── Map lifecycle ───────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    let instance: MLMap | null = null;
    loadBasemap().then(({ style, source }) => {
      if (cancelled || !containerRef.current) return;
      try {
        instance = new MLMap({
          container: containerRef.current,
          style,
          bounds: NETWORK_BOUNDS as [LngLat, LngLat],
          fitBoundsOptions: { padding: 36 },
          minZoom: 9.5,
          maxZoom: 17.5,
          dragRotate: false,
          pitchWithRotate: false,
          attributionControl: { compact: true },
          fadeDuration: 150,
        });
      } catch {
        setFailed(true);
        return;
      }
      instance.touchZoomRotate.disableRotation();
      instance.keyboard.disableRotation();
      let initialised = false;
      const init = () => {
        if (cancelled || !instance || initialised) return;
        initialised = true;
        addDallalLayers(instance);
        setBasemap(source);
        setZoom(instance.getZoom());
        setMap(instance);
      };
      // Show the network as soon as the style is ready; tiles keep streaming in.
      instance.once("style.load", init);
      instance.once("load", init);
      instance.on("zoomend", () => instance && setZoom(instance.getZoom()));
    });
    return () => {
      cancelled = true;
      instance?.remove();
    };
  }, []);

  useEffect(() => {
    if (!map) return;
    const onClick = () => {
      onSelectShipment?.(null);
      onSelectFacility?.(null);
    };
    map.on("click", onClick);
    return () => void map.off("click", onClick);
  }, [map, onSelectShipment, onSelectFacility]);

  // ── Framing ─────────────────────────────────────────────────────────────
  const frameSubject = useCallback(
    (animate: boolean) => {
      if (!map) return;
      const pts: LngLat[] = [];
      const w = getWorld();
      const o = latest.current;
      if (o.variant === "shipment" && o.shipmentIds?.[0]) {
        const s = w.shipments[o.shipmentIds[0]];
        const r = s && getRoute(s.routeKey);
        if (r) pts.push(...r.coords);
      } else if (o.variant === "incident") {
        for (const inc of o.visibleIncidents) {
          pts.push(inc.sharedFactor.coord);
          for (const id of [...inc.affected, ...inc.exposed]) {
            const s = w.shipments[id];
            if (s) pts.push(shipmentPosition(s, clockNow(w.clock)));
          }
        }
      }
      const duration = animate && !reducedMotion ? 900 : 0;
      if (o.variant === "overview" || !pts.length) {
        map.fitBounds(NETWORK_BOUNDS as [LngLat, LngLat], { padding: 36, duration });
        return;
      }
      const b = pts.reduce((acc, p) => acc.extend(p), new LngLatBounds(pts[0], pts[0]));
      map.fitBounds(b, { padding: { top: 70, bottom: 60, left: 60, right: 60 }, maxZoom: 14, duration });
    },
    [map, reducedMotion],
  );
  const frameSubjectRef = useRef(frameSubject);
  useLayoutEffect(() => {
    frameSubjectRef.current = frameSubject;
  });
  useEffect(() => {
    if (map) frameSubject(false);
  }, [map, frameSubject]);

  // Keep the subject framed while the layout settles, until the user moves the map.
  const userMoved = useRef(false);
  useEffect(() => {
    if (!map || !containerRef.current) return;
    const markMoved = (e: { originalEvent?: unknown }) => {
      if (e.originalEvent) userMoved.current = true;
    };
    map.on("movestart", markMoved);
    const ro = new ResizeObserver(() => {
      map.resize();
      if (!userMoved.current) frameSubjectRef.current(false);
    });
    ro.observe(containerRef.current);
    return () => {
      ro.disconnect();
      map.off("movestart", markMoved);
    };
  }, [map]);

  // ── Programmatic focus (queue click, assistant "Show on map", incident) ─
  useEffect(() => {
    if (!map || !focus) return;
    const w = getWorld();
    const now = clockNow(w.clock);
    const duration = reducedMotion ? 0 : 1200;
    if (focus.kind === "network") {
      map.fitBounds(NETWORK_BOUNDS as [LngLat, LngLat], { padding: 36, duration });
    } else if (focus.kind === "shipment") {
      const s = w.shipments[focus.id];
      if (!s) return;
      map.flyTo({ center: shipmentPosition(s, now), zoom: Math.max(map.getZoom(), 13.2), duration, padding: { right: variant === "overview" ? 340 : 0, top: 0, bottom: 0, left: 0 }, essential: true });
    } else if (focus.kind === "incident") {
      const inc = w.incidents[focus.id];
      if (!inc) return;
      const pts: LngLat[] = [inc.sharedFactor.coord];
      for (const id of [...inc.affected, ...inc.exposed]) {
        const s = w.shipments[id];
        if (s) pts.push(shipmentPosition(s, now));
      }
      const b = pts.reduce((acc, p) => acc.extend(p), new LngLatBounds(pts[0], pts[0]));
      map.fitBounds(b, { padding: { top: 90, bottom: 60, left: 60, right: variant === "overview" ? 380 : 60 }, maxZoom: 13.5, duration });
    }
  }, [map, focus, variant, reducedMotion]);

  // ── Animation loop: marker positions every frame, routes at ~5 Hz ───────
  useEffect(() => {
    if (!map) return;
    let raf = 0;
    let lastRoutes = 0;
    let lastFlow = 0;
    let flowStep = 0;
    const registry = registryFor(map);
    const tick = (t: number) => {
      const w = getWorld();
      const now = clockNow(w.clock);
      const o = latest.current;
      for (const id of o.movingIds) {
        const s = w.shipments[id];
        const marker = registry.get(`s:${id}`);
        if (s && marker) marker.setLngLat(shipmentPosition(s, now));
      }
      if (t - lastRoutes > 200) {
        lastRoutes = t;
        const visible = new Set<string>(o.movingIds);
        if (o.variant !== "overview") for (const id of o.shipmentIds ?? EMPTY) visible.add(id);
        else if (o.selectedId) visible.add(o.selectedId);
        (map.getSource("dl-routes") as GeoJSONSource | undefined)?.setData(
          buildRouteFeatures(w.shipments, {
            variant: o.variant,
            selectedId: o.variant === "shipment" ? (o.shipmentIds?.[0] ?? null) : o.selectedId,
            visibleIds: visible,
            highlightIds: o.highlightSet,
            incident: o.visibleIncidents[0],
            now,
          }),
        );
        if (o.pinTarget) {
          const s = w.shipments[o.pinTarget];
          const r = s && getRoute(s.routeKey);
          if (r) registry.get(`d:${o.pinTarget}`)?.setLngLat(r.coords[r.coords.length - 1]);
        }
      }
      if (!reducedMotion && t - lastFlow > 75 && map.getLayer("dl-route-flow")) {
        lastFlow = t;
        flowStep = (flowStep + 1) % FLOW_DASHES.length;
        map.setPaintProperty("dl-route-flow", "line-dasharray", FLOW_DASHES[flowStep]);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [map, reducedMotion]);

  // ── Incident zones ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!map) return;
    const color = (sev: string, status: string) => (status === "mitigating" || sev === "medium" || sev === "low" ? "#e38b06" : "#df3b30");
    const zones = visibleIncidents.map((i) => ({ z: incidentZoneFeatures(i), color: color(i.severity, i.status) }));
    (map.getSource("dl-incident-zone") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: zones.flatMap(({ z, color: c }) => z.zone.features.map((f) => ({ ...f, properties: { color: c } }))),
    });
    (map.getSource("dl-incident-corridor") as GeoJSONSource | undefined)?.setData({
      type: "FeatureCollection",
      features: zones.flatMap(({ z, color: c }) => z.corridor.features.map((f) => ({ ...f, properties: { color: c } }))),
    });
  }, [map, visibleIncidents]);

  const markerScale = zoom < 11.2 ? 0.9 : zoom < 12.2 ? 0.96 : 1.04;
  const pinShipment = pinTarget ? shipments[pinTarget] : undefined;
  const pinRoute = pinShipment && (!pinShipment.closed || variant === "shipment") ? getRoute(pinShipment.routeKey) : undefined;

  return (
    <div className={cn("relative isolate overflow-hidden bg-[#eef2f7]", className)} style={{ ["--mk" as string]: markerScale }}>
      <div ref={containerRef} style={{ position: "absolute", inset: 0 }} role="region" aria-label="Live network map of Dammam and Al Khobar" />
      {!map && !failed ? (
        <div className="skeleton absolute inset-0 flex items-center justify-center">
          <span className="rounded-lg bg-surface/80 px-3 py-1.5 text-xs text-ink-3 shadow-card">Loading live map…</span>
        </div>
      ) : null}
      {failed ? <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-13 text-ink-3">Map rendering is unavailable in this browser (WebGL disabled). The queue lists every shipment.</div> : null}

      {map ? (
        <>
          {movingIds.map((id) => {
            const s = shipments[id];
            return s ? (
              <MapMarker key={`s:${id}`} map={map} markerKey={`s:${id}`} lngLat={shipmentPosition(s, clockNow(getWorld().clock))}>
                <ShipmentMarker id={id} selected={selectedId === id || (variant === "shipment" && shipmentIds?.[0] === id)} dimmed={!!highlightSet && !highlightSet.has(id)} onSelect={(x) => onSelectShipment?.(x)} />
              </MapMarker>
            ) : null;
          })}
          {facilityIds.map((id) => (
            <MapMarker key={`f:${id}`} map={map} markerKey={`f:${id}`} lngLat={places[id].coord} anchor="top" offset={[0, -15]}>
              <FacilityMarker
                placeId={id}
                held={(heldByFacility[id] ?? []).map((sid) => shipments[sid]).filter(Boolean) as Shipment[]}
                incident={Object.values(incidents).find((i) => i.sharedFactor.placeId === id && i.status !== "resolved")}
                selected={selectedFacilityId === id}
                onSelect={(x) => onSelectFacility?.(x)}
                showLabel={zoom >= 11 || variant !== "overview"}
              />
            </MapMarker>
          ))}
          {visibleIncidents
            .filter((i) => i.kind === "route")
            .map((inc) => (
              <MapMarker key={`i:${inc.id}`} map={map} markerKey={`i:${inc.id}`} lngLat={inc.sharedFactor.coord} anchor="top" offset={[0, -16]}>
                <IncidentMarker incident={inc} onSelect={() => onSelectIncident?.(inc.id)} />
              </MapMarker>
            ))}
          {pinShipment && pinRoute ? (
            <MapMarker key={`d:${pinShipment.id}`} map={map} markerKey={`d:${pinShipment.id}`} lngLat={pinRoute.coords[pinRoute.coords.length - 1]} anchor="bottom">
              <DestinationPin s={pinShipment} />
            </MapMarker>
          ) : null}

          <div className={cn("absolute top-3 z-10 flex flex-col overflow-hidden rounded-xl border border-line bg-surface shadow-float", controlsOffset ? "right-[340px]" : "right-3")}>
            <button className="flex size-9 items-center justify-center text-ink-2 hover:bg-hover" onClick={() => map.zoomIn()} aria-label="Zoom in">
              <Plus className="size-4" />
            </button>
            <span className="h-px bg-line" />
            <button className="flex size-9 items-center justify-center text-ink-2 hover:bg-hover" onClick={() => map.zoomOut()} aria-label="Zoom out">
              <Minus className="size-4" />
            </button>
            <span className="h-px bg-line" />
            <button className="flex size-9 items-center justify-center text-ink-2 hover:bg-hover" onClick={() => frameSubject(true)} aria-label={variant === "overview" ? "Fit whole network" : "Recenter"}>
              <LocateFixed className="size-4" />
            </button>
          </div>
          {legend ? <MapLegend variant={variant} compact={compactControls} /> : null}
          {basemap === "offline" ? (
            <div className="absolute top-3 left-1/2 z-10 flex -translate-x-1/2 items-center gap-1.5 rounded-lg border border-line bg-surface px-2.5 py-1 text-xs text-ink-3 shadow-card">
              <CloudOff className="size-3.5" /> Basemap offline — showing network only
            </div>
          ) : null}
        </>
      ) : null}
      {children}
    </div>
  );
}

function addDallalLayers(map: MLMap) {
  const empty = { type: "FeatureCollection" as const, features: [] };
  map.addSource("dl-incident-zone", { type: "geojson", data: empty });
  map.addSource("dl-incident-corridor", { type: "geojson", data: empty });
  map.addSource("dl-routes", { type: "geojson", data: empty });

  map.addLayer({ id: "dl-incident-zone-fill", type: "fill", source: "dl-incident-zone", paint: { "fill-color": ["get", "color"], "fill-opacity": 0.09 } });
  map.addLayer({ id: "dl-incident-zone-line", type: "line", source: "dl-incident-zone", paint: { "line-color": ["get", "color"], "line-width": 1.5, "line-opacity": 0.55, "line-dasharray": [2, 2] } });
  map.addLayer({
    id: "dl-incident-corridor",
    type: "line",
    source: "dl-incident-corridor",
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": ["get", "color"], "line-width": ["interpolate", ["linear"], ["zoom"], 10, 10, 14, 26], "line-opacity": 0.16, "line-blur": 3 },
  });

  const width = (scale = 1) => ["interpolate", ["linear"], ["zoom"], 10, ["*", ["get", "width"], 0.62 * scale], 13, ["*", ["get", "width"], 1 * scale], 16, ["*", ["get", "width"], 1.35 * scale]] as unknown as number;
  const solid = (part: string) => ["all", ["==", ["get", "part"], part], ["==", ["get", "dashed"], false]] as unknown as FilterSpecification;

  map.addLayer({ id: "dl-route-traveled", type: "line", source: "dl-routes", filter: ["==", ["get", "part"], "traveled"], layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": ["get", "color"], "line-width": width(), "line-opacity": ["get", "opacity"] } });
  map.addLayer({
    id: "dl-route-casing",
    type: "line",
    source: "dl-routes",
    filter: ["all", ["==", ["get", "part"], "upcoming"], [">=", ["get", "width"], 3]],
    layout: { "line-cap": "round", "line-join": "round" },
    paint: { "line-color": "#ffffff", "line-width": ["interpolate", ["linear"], ["zoom"], 10, ["+", ["*", ["get", "width"], 0.62], 2.5], 16, ["+", ["*", ["get", "width"], 1.35], 4]], "line-opacity": ["*", ["get", "opacity"], 0.9] },
  });
  map.addLayer({ id: "dl-route-upcoming", type: "line", source: "dl-routes", filter: solid("upcoming"), layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": ["get", "color"], "line-width": width(), "line-opacity": ["get", "opacity"] } });
  map.addLayer({
    id: "dl-route-dashed",
    type: "line",
    source: "dl-routes",
    filter: ["any", ["all", ["==", ["get", "part"], "upcoming"], ["==", ["get", "dashed"], true]], ["==", ["get", "part"], "planned"], ["==", ["get", "part"], "alternate"]],
    layout: { "line-join": "round" },
    paint: { "line-color": ["get", "color"], "line-width": width(), "line-opacity": ["get", "opacity"], "line-dasharray": [1.4, 1.2] },
  });
  map.addLayer({
    id: "dl-route-flow",
    type: "line",
    source: "dl-routes",
    filter: ["all", ["==", ["get", "part"], "upcoming"], ["==", ["get", "flow"], true]],
    paint: { "line-color": "#ffffff", "line-width": width(0.45), "line-opacity": 0.75, "line-dasharray": FLOW_DASHES[0] },
  });
}
