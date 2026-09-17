import type { Feature, FeatureCollection, LineString, Polygon } from "geojson";
import { DK04_BLOCKAGE, getRoute } from "@/data/network";
import { circlePolygon, slicePath } from "@/lib/geo";
import { distanceAt } from "@/services/logic/movement";
import type { Incident, Shipment } from "@/types/domain";
import { HEALTH, TRAVELED_COLOR } from "@/components/common/status";

export type MapVariant = "overview" | "shipment" | "incident";

export interface RouteRenderOptions {
  variant: MapVariant;
  selectedId: string | null;
  visibleIds: Set<string>;
  highlightIds: Set<string> | null;
  incident?: Incident;
  now: number;
}

type RouteProps = {
  id: string;
  part: "traveled" | "upcoming" | "planned" | "alternate";
  color: string;
  width: number;
  opacity: number;
  dashed: boolean;
  flow: boolean;
};

/**
 * Route visual language (from the reference recording, adapted):
 *  traveled segment → muted blue-gray · upcoming segment → status color ·
 *  human review → dashed violet · planned-but-not-departed → dashed.
 */
export function buildRouteFeatures(shipments: Record<string, Shipment>, o: RouteRenderOptions): FeatureCollection<LineString, RouteProps> {
  const features: Feature<LineString, RouteProps>[] = [];
  const push = (id: string, part: RouteProps["part"], coords: [number, number][], props: Omit<RouteProps, "id" | "part">) => {
    if (coords.length < 2) return;
    features.push({ type: "Feature", properties: { id, part, ...props }, geometry: { type: "LineString", coordinates: coords } });
  };

  for (const id of o.visibleIds) {
    const s = shipments[id];
    if (!s || (s.closed && o.variant !== "shipment")) continue;
    const route = getRoute(s.routeKey);
    if (!route) continue;
    if (s.closed) {
      push(id, "traveled", route.coords, { color: TRAVELED_COLOR, width: 4, opacity: 0.95, dashed: false, flow: false });
      continue;
    }
    const selected = o.selectedId === id;
    const dim = o.highlightIds ? !o.highlightIds.has(id) : false;
    const normal = s.health === "on_track";
    const color = HEALTH[s.health].map;
    const atFacility = s.movement.mode === "facility";

    let emphasis = 0;
    if (o.variant === "shipment") emphasis = 3;
    else if (selected) emphasis = 3;
    else if (o.variant === "incident") emphasis = s.incident?.role === "affected" || s.health === "recovering" ? 2 : 1.5;
    else if (!normal && !atFacility) emphasis = 2;
    else if (normal && !atFacility) emphasis = 1;
    else if (atFacility && o.incident && s.incident?.id === o.incident.id) emphasis = 1.2;
    if (emphasis === 0) continue;

    const alpha = dim ? 0.18 : 1;

    if (atFacility) {
      // Not yet departed: show the planned path dashed.
      push(id, "planned", route.coords, { color, width: selected ? 3.5 : 2.4, opacity: 0.85 * alpha, dashed: true, flow: false });
      if (o.variant === "incident" && s.altRouteKey && o.incident?.response.state !== "applied") {
        const alt = getRoute(s.altRouteKey);
        if (alt) push(id, "alternate", alt.coords, { color: HEALTH.recovering.map, width: 2, opacity: 0.55 * alpha, dashed: true, flow: false });
      }
      continue;
    }

    const d = distanceAt(s.movement, route.lengthM, o.now);
    const travelled = slicePath(route, 0, d);
    const upcoming = slicePath(route, d, route.lengthM);
    const width = emphasis >= 3 ? 5 : emphasis >= 2 ? 3.6 : emphasis >= 1.5 ? 3 : 2.2;

    if (emphasis >= 1.5) push(id, "traveled", travelled, { color: TRAVELED_COLOR, width: Math.max(2, width - 1.4), opacity: 0.9 * alpha, dashed: false, flow: false });
    push(id, "upcoming", upcoming, {
      color,
      width,
      opacity: (emphasis <= 1 ? 0.55 : 0.95) * alpha,
      dashed: s.health === "review",
      flow: emphasis >= 3 || (o.variant !== "overview" && emphasis >= 2),
    });
  }
  return { type: "FeatureCollection", features };
}

export function incidentZoneFeatures(incident: Incident | undefined): {
  zone: FeatureCollection<Polygon>;
  corridor: FeatureCollection<LineString>;
} {
  const empty = { type: "FeatureCollection" as const, features: [] };
  if (!incident || incident.status === "resolved") return { zone: empty, corridor: empty };
  const zone: FeatureCollection<Polygon> = {
    type: "FeatureCollection",
    features: [{ type: "Feature", properties: { severity: incident.severity }, geometry: { type: "Polygon", coordinates: [circlePolygon(incident.sharedFactor.coord, incident.sharedFactor.radiusM)] } }],
  };
  const seg = incident.sharedFactor.segment ?? (incident.kind === "route" ? DK04_BLOCKAGE.segment : undefined);
  const route = seg ? getRoute(seg.routeKey) : undefined;
  const corridor: FeatureCollection<LineString> =
    seg && route
      ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: slicePath(route, seg.fromM, seg.toM) } }] }
      : empty;
  return { zone, corridor };
}
