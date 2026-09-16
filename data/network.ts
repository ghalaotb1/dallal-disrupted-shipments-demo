import placesJson from "@/data/geo/places.json";
import routesJson from "@/data/geo/routes.generated.json";
import { boundsOf, buildPath, pointAt } from "@/lib/geo";
import type { Corridor, LngLat, Place, RoutePath } from "@/types/domain";

/**
 * Demo logistics network for the Eastern Province.
 * Facility names are fictional operational nodes placed at real locations;
 * route geometry follows real roads (OpenStreetMap via OSRM, see scripts/generate-routes.mjs).
 */

type RawPlace = Omit<Place, "id" | "coord"> & { coord: number[] };
type RawRoute = { coords: number[][]; distanceM: number; roads: string[] };

export const places: Record<string, Place> = Object.fromEntries(
  Object.entries(placesJson as Record<string, RawPlace>).map(([id, p]) => [id, { ...p, id, coord: p.coord as LngLat }]),
);

export const corridors: Record<string, Corridor> = {
  "DK-04": { id: "DK-04", code: "DK-04", name: "King Fahd Rd", description: "Dammam Hub → Al Khobar via King Fahd Rd" },
  "DK-07": { id: "DK-07", code: "DK-07", name: "King Saud Rd · Dhahran", description: "Alternate corridor via King Saud Rd and Prince Sultan Rd" },
  "DM-02": { id: "DM-02", code: "DM-02", name: "Dammam North", description: "Dammam Central → northern districts and coast" },
  "DM-05": { id: "DM-05", code: "DM-05", name: "Dammam West", description: "Dammam Central / Hub → western districts" },
  "KH-01": { id: "KH-01", code: "KH-01", name: "Khobar Local", description: "Khobar Branch → Khobar neighbourhoods" },
  "SH-03": { id: "SH-03", code: "SH-03", name: "Saihat", description: "Dammam Central → Saihat" },
};

export const routes: Record<string, RoutePath> = Object.fromEntries(
  Object.entries(routesJson as Record<string, RawRoute>).map(([key, r]) => [key, buildPath(key, r.coords as LngLat[], r.roads)]),
);

export function getRoute(key: string | undefined): RoutePath | undefined {
  return key ? routes[key] : undefined;
}

/** Simulated lane closure on King Fahd Rd southbound, used by the headline incident. */
export const DK04_BLOCKAGE = {
  coord: [50.19275, 26.35001] as LngLat,
  distanceOnCorridorM: 8260,
  radiusM: 950,
  label: "King Fahd Rd southbound · near Ar Rakah",
  segment: { routeKey: "DL-20481", fromM: 3200, toM: 8700 },
};

export const NETWORK_BOUNDS = boundsOf([
  ...Object.values(places).map((p) => p.coord),
  [50.035, 26.478],
  [50.218, 26.205],
]);

export const blockagePoint = () => pointAt(routes["DL-20481"], DK04_BLOCKAGE.distanceOnCorridorM);
