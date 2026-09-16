import { getRoute, places } from "@/data/network";
import { at } from "@/lib/time";
import type {
  AgentState,
  CaseType,
  City,
  EventSource,
  EventTone,
  JourneyEvent,
  Movement,
  Owner,
  Shipment,
  ShipmentContext,
  ShipmentFlag,
  ShipmentHealth,
  ShipmentStage,
  ServiceLevel,
} from "@/types/domain";

/** "HH:MM" on the demo day, or ["HH:MM", dayOffset]. */
export type T = string | [string, number];
export const t = (v: T) => (typeof v === "string" ? at(v) : at(v[0], v[1]));

/** [time, title, source, tone, detail?, location?, code?] */
export type J = [T, string, EventSource, EventTone, string?, string?, string?];

type MoveSeed =
  | { facility: string }
  | { d: number; v: number; hold?: number; stops?: number; stationarySince?: T }
  | { delivered: true };

export interface ShipmentSeed {
  id: string;
  orderRef: string;
  merchant: string;
  service: ServiceLevel;
  cod?: number;
  contents: string;
  valueSar: number;
  recipient: [string, string];
  address: [string, string, City, string];
  origin: string;
  corridor: string;
  route: string;
  alt?: string;
  courier?: [string, string, string];
  created: T;
  window: [T, T];
  sla: T;
  health: ShipmentHealth;
  stage: ShipmentStage;
  move: MoveSeed;
  caseType: CaseType;
  headline?: string;
  exception?: [string, string, T, string];
  flags?: ShipmentFlag[];
  attempts?: number;
  incident?: { id: string; role: "affected" | "exposed" };
  agent?: [AgentState, string?];
  owner?: Owner;
  closed?: boolean;
  outcome?: [NonNullable<Shipment["outcome"]>["kind"], string, T];
  journey: J[];
  ctx?: DeepPartialContext;
}

type DeepPartialContext = {
  address?: Partial<ShipmentContext["address"]>;
  recipient?: Partial<ShipmentContext["recipient"]>;
  telemetry?: ShipmentContext["telemetry"];
  facility?: ShipmentContext["facility"];
  custody?: ShipmentContext["custody"];
  pickupPoint?: ShipmentContext["pickupPoint"];
};

export const passChecks = (shortCode: string): ShipmentContext["address"]["checks"] => [
  { label: "National Address short code", result: "pass", detail: `${shortCode} resolves to the delivery district` },
  { label: "Building number on street", result: "pass", detail: "Building found on the registered street" },
  { label: "Customer pin vs. National Address", result: "pass", detail: "Pin within 60 m of registered address" },
];

export function buildShipment(seed: ShipmentSeed): { shipment: Shipment; journey: JourneyEvent[]; context: ShipmentContext } {
  const route = getRoute(seed.route);
  const destCoord = route ? route.coords[route.coords.length - 1] : places[seed.origin].coord;
  const created = t(seed.created);

  let movement: Movement;
  if ("facility" in seed.move) {
    movement = { mode: "facility", distanceM: 0, speedMps: 10.2, facilityId: seed.move.facility, updatedAt: created };
  } else if ("delivered" in seed.move) {
    movement = { mode: "delivered", distanceM: route?.lengthM ?? 0, speedMps: 0, updatedAt: created };
  } else {
    movement = {
      mode: "route",
      distanceM: seed.move.d,
      speedMps: seed.move.v,
      holdAtM: seed.move.hold,
      stopsAhead: seed.move.stops,
      stationarySince: seed.move.stationarySince ? t(seed.move.stationarySince) : undefined,
      updatedAt: at("15:10"),
    };
  }

  const journey: JourneyEvent[] = seed.journey
    .map(([time, title, source, tone, detail, location, code], i) => ({
      id: `${seed.id}-j${i}`,
      shipmentId: seed.id,
      at: t(time),
      title,
      source,
      tone,
      detail,
      location,
      code,
    }))
    .sort((a, b) => a.at - b.at);

  const [line, district, city, shortCode] = seed.address;
  const flags = new Set<ShipmentFlag>(seed.flags ?? []);
  if (seed.cod) flags.add("cod");
  if (seed.valueSar >= 1000) flags.add("high_value");

  const shipment: Shipment = {
    id: seed.id,
    orderRef: seed.orderRef,
    merchant: seed.merchant,
    service: seed.service,
    payment: seed.cod ? { type: "COD", amountSar: seed.cod } : { type: "Prepaid" },
    contents: seed.contents,
    valueSar: seed.valueSar,
    recipient: { name: seed.recipient[0], phone: seed.recipient[1] },
    address: { line, district, city, shortCode },
    originId: seed.origin,
    destination: { label: `${district}, ${city}`, district, city, coord: destCoord },
    corridorId: seed.corridor,
    routeKey: seed.route,
    altRouteKey: seed.alt,
    courier: seed.courier ? { id: seed.courier[0], name: seed.courier[1], vehicle: seed.courier[2] } : undefined,
    createdAt: created,
    window: { start: t(seed.window[0]), end: t(seed.window[1]) },
    slaDeadline: t(seed.sla),
    health: seed.health,
    stage: seed.stage,
    movement,
    risk: { score: 0, level: "low", drivers: [], updatedAt: at("15:10"), method: "prototype-heuristic" },
    exception: seed.exception
      ? { code: seed.exception[0], label: seed.exception[1], recordedAt: t(seed.exception[2]), recordedBy: seed.exception[3] }
      : undefined,
    caseType: seed.caseType,
    headline: seed.headline,
    agent: { state: seed.agent?.[0] ?? "monitoring", headline: seed.agent?.[1], updatedAt: at("15:10") },
    owner: seed.owner ?? { kind: "agent", name: "Dallal Agent" },
    priority: "P3",
    incident: seed.incident,
    flags: [...flags],
    attempts: seed.attempts ?? 0,
    outcome: seed.outcome ? { kind: seed.outcome[0], label: seed.outcome[1], at: t(seed.outcome[2]) } : undefined,
    closed: seed.closed ?? false,
    lastEventAt: journey.length ? journey[journey.length - 1].at : created,
  };

  const c = seed.ctx ?? {};
  const context: ShipmentContext = {
    address: {
      confidence: 0.93,
      checks: passChecks(shortCode),
      pastFailuresAtAddress: 0,
      firstDeliveryToAddress: false,
      ...c.address,
    },
    recipient: { preferredChannel: "WhatsApp", responsiveness: "medium", missedWindows: [], ...c.recipient },
    telemetry: c.telemetry ?? {},
    facility: c.facility,
    custody: c.custody,
    pickupPoint: c.pickupPoint,
  };

  return { shipment, journey, context };
}

/** Standard first-mile events shared by most shipments. */
export function firstMile(opts: { created: T; merchant: string; service: string; received: T; facility: string; sorted?: T; corridor?: string; loaded?: T; vehicle?: string; ofd?: T }): J[] {
  const place = places[opts.facility];
  const out: J[] = [
    [opts.created, "Order created", "system", "neutral", `${opts.merchant} · ${opts.service}`],
    [opts.received, `Received at ${place.name}`, "scan", "neutral", undefined, place.short],
  ];
  if (opts.sorted) out.push([opts.sorted, `Sorted to ${opts.corridor}`, "scan", "neutral", undefined, place.short]);
  if (opts.loaded) out.push([opts.loaded, `Loaded on van ${opts.vehicle}`, "scan", "neutral", undefined, place.short]);
  if (opts.ofd) out.push([opts.ofd, "Out for delivery", "scan", "info", `Van ${opts.vehicle}`, place.short]);
  return out;
}
