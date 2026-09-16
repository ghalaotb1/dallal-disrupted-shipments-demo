import { getRoute, places } from "@/data/network";
import type { City, JourneyEvent, Shipment } from "@/types/domain";

/**
 * Deterministic "lane traffic": ordinary shipments dispatched on healthy
 * corridors as earlier ones are delivered, so the live map keeps moving.
 */
const templates: { route: string; origin: string; corridor: string; district: string; city: City }[] = [
  { route: "lane-01", origin: "br-dmm-central", corridor: "DM-02", district: "Al Badi", city: "Dammam" },
  { route: "lane-05", origin: "br-khobar", corridor: "KH-01", district: "Al Khobar Al Janubiyah", city: "Al Khobar" },
  { route: "lane-02", origin: "br-dmm-central", corridor: "DM-05", district: "Al Faisaliyah", city: "Dammam" },
  { route: "lane-06", origin: "hub-dmm", corridor: "DK-07", district: "Ad Dawhah Ash Shamaliyah", city: "Dhahran" },
  { route: "lane-03", origin: "br-dmm-central", corridor: "SH-03", district: "Saihat", city: "Saihat" },
  { route: "lane-08", origin: "br-khobar", corridor: "KH-01", district: "Al Jisr", city: "Al Khobar" },
  { route: "lane-04", origin: "hub-dmm", corridor: "DM-05", district: "Al Muraikabat", city: "Dammam" },
  { route: "lane-07", origin: "br-dmm-central", corridor: "DM-02", district: "Ash Shati Ash Sharqi", city: "Dammam" },
  { route: "lane-12", origin: "br-khobar", corridor: "KH-01", district: "Al Aqrabiyah", city: "Al Khobar" },
  { route: "lane-09", origin: "hub-dmm", corridor: "DM-05", district: "An Nuzhah", city: "Dammam" },
  { route: "lane-10", origin: "br-dmm-central", corridor: "DM-05", district: "Al Anud", city: "Dammam" },
  { route: "lane-11", origin: "br-dmm-central", corridor: "DM-02", district: "Al Hamra", city: "Dammam" },
];
const merchants = ["Nabta Toys", "Mahd Home Store", "Ward Beauty", "Waraq Bookstore", "Lamsa Fashion", "Bait Matbakh", "Qamar Electronics"];
const contents = ["Parcel · 1 pc · 1.2 kg", "Apparel · 2 pcs · 0.9 kg", "Homeware · 1 pc · 2.4 kg", "Books · 2 pcs · 1.6 kg", "Cosmetics · 1 pc · 0.5 kg"];
const initials = ["A.", "M.", "S.", "H.", "R.", "N.", "F.", "L."];
const families = ["Al-Dosari", "Al-Qahtani", "Al-Ghamdi", "Al-Shehri", "Al-Zahrani", "Al-Mutairi", "Al-Harbi", "Al-Subaie", "Al-Anazi"];

export const LANE_START_SEQ = 21001;

export function createLaneShipment(seq: number, now: number): { shipment: Shipment; journey: JourneyEvent[] } {
  const n = seq - LANE_START_SEQ;
  const tpl = templates[n % templates.length];
  const route = getRoute(tpl.route)!;
  const id = `DL-${seq}`;
  const vehicle = `${tpl.origin === "br-khobar" ? "KHB" : "DMM"}-${240 + (n % 60)}`;
  const origin = places[tpl.origin];
  const recipient = `${initials[n % initials.length]} ${families[(n * 7) % families.length]}`;
  const created = now - (5 + (n % 3)) * 3_600_000;
  const shipment: Shipment = {
    id,
    orderRef: `ORD-${60000 + seq}`,
    merchant: merchants[n % merchants.length],
    service: "Standard",
    payment: { type: "Prepaid" },
    contents: contents[n % contents.length],
    valueSar: 90 + ((n * 37) % 400),
    recipient: { name: recipient, phone: "+966 5• ••• ••••" },
    address: { line: "Registered address", district: tpl.district, city: tpl.city, shortCode: "—" },
    originId: tpl.origin,
    destination: { label: `${tpl.district}, ${tpl.city}`, district: tpl.district, city: tpl.city, coord: route.coords[route.coords.length - 1] },
    corridorId: tpl.corridor,
    routeKey: tpl.route,
    courier: { id: `C-${240 + (n % 60)}`, name: "Courier", vehicle },
    createdAt: created,
    window: { start: now, end: now + 3 * 3_600_000 },
    slaDeadline: now + 5 * 3_600_000,
    health: "on_track",
    stage: "out_for_delivery",
    movement: { mode: "route", distanceM: 0, speedMps: 9.4 + (n % 5) * 0.35, updatedAt: now },
    risk: { score: 8, level: "low", drivers: [], updatedAt: now, method: "prototype-heuristic" },
    caseType: "normal",
    agent: { state: "monitoring", updatedAt: now },
    owner: { kind: "agent", name: "Dallal Agent" },
    priority: "P3",
    flags: [],
    attempts: 0,
    closed: false,
    lastEventAt: now,
    generated: true,
  };
  const journey: JourneyEvent[] = [
    { id: `${id}-j0`, shipmentId: id, at: created, title: "Order created", detail: `${shipment.merchant} · Standard`, source: "system", tone: "neutral" },
    { id: `${id}-j1`, shipmentId: id, at: created + 2 * 3_600_000, title: `Received at ${origin.name}`, source: "scan", tone: "neutral", location: origin.short },
    { id: `${id}-j2`, shipmentId: id, at: now, title: "Out for delivery", detail: `Van ${vehicle}`, source: "scan", tone: "info", location: origin.short },
  ];
  return { shipment, journey };
}
