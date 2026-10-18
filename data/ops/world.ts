import { places, routes } from "@/data/network";
import { pointAt } from "@/lib/geo";
import { at, SCENARIO_START } from "@/lib/time";
import type { JourneyEvent, LngLat, ShipmentContext } from "@/types/domain";
import type { Driver, Parcel } from "@/types/ops";

/**
 * The simulated operation: seven drivers, each on one real road route, carrying their parcels in delivery order.
 * Everything here is fictional (drivers, merchants, recipients, addresses) - only the roads are real (OpenStreetMap via OSRM).
 */

const SPEED_MPS = 9; // ~32 km/h urban average
const MIN = 60_000;

interface StopSpec {
  /** metres along the route */
  d: number;
  merchant: string;
  contents: string;
  value: number;
  service?: "Standard" | "Express" | "Same-day";
  cod?: number;
  recipient: string;
  district: string;
  city: string;
  line: string;
  id?: string;
}

interface DriverSpec {
  id: string;
  name: string;
  vehicle: string;
  courierId: string;
  routeKey: string;
  corridorId: string;
  originId: string;
  /** Facility that sorted this driver's parcels when it differs from the van's start (loaded at the hub, sorted elsewhere). */
  parcelOrigin?: string;
  /** Where the van is at the start of the shift snapshot (metres) */
  startM: number;
  stops: StopSpec[];
}

const S = (d: number, merchant: string, contents: string, value: number, recipient: string, district: string, city: string, line: string, extra: Partial<StopSpec> = {}): StopSpec => ({
  d, merchant, contents, value, recipient, district, city, line, ...extra,
});

export const DRIVER_SPECS: DriverSpec[] = [
  {
    id: "salem", name: "Salem", vehicle: "DMM-114", courierId: "C-114", routeKey: "DL-20481", corridorId: "DK-04", originId: "hub-dmm", startM: 6800,
    stops: [
      S(1800, "Nabta Toys", "Toys · 2 pcs", 260, "F. Al-Subaie", "Al Faisaliyah", "Dammam", "Bldg 5520, King Abdullah St"),
      S(3600, "Zahra Beauty", "Skincare set", 310, "R. Al-Anazi", "Al Shula", "Dammam", "Bldg 2204, 15th St"),
      S(5000, "Waraq Office Supplies", "Documents · 1 pc", 90, "L. Al-Rashid", "Ar Rakah", "Dammam", "Bldg 1184, Prince Turki St", { service: "Express" }),
      S(7700, "Bait Matbakh", "Cookware set", 540, "N. Al-Yami", "Ar Rakah", "Al Khobar", "Bldg 3307, 22nd St", { cod: 540, id: "DL-20481" }),
      S(8900, "Qamar Electronics", "Smartphone · 1 pc", 2450, "A. Al-Shammari", "Al Aqrabiyah", "Al Khobar", "Bldg 2915, Prince Faisal bin Fahd St", { service: "Express", cod: 2450 }),
      S(11000, "Sahab Fashion", "Clothing · 3 pcs", 430, "M. Al-Dossari", "Al Bandariyah", "Al Khobar", "Bldg 6120, King Abdullah St"),
    ],
  },
  {
    id: "nawaf", name: "Nawaf", vehicle: "DMM-131", courierId: "C-131", routeKey: "DL-20334", corridorId: "DK-04", originId: "hub-dmm", parcelOrigin: "br-dmm-west", startM: 4000,
    stops: [
      S(1500, "Sahab Fashion", "Clothing · 2 pcs", 290, "T. Al-Mutairi", "Al Faisaliyah", "Dammam", "Bldg 7710, Omar Ibn Al Khattab St"),
      S(3200, "Zahra Beauty", "Perfume · 1 pc", 520, "D. Al-Ghamdi", "Al Nuzha", "Dammam", "Bldg 3302, 18th St"),
      S(6400, "Waraq Office Supplies", "Printer ink", 210, "K. Al-Zahrani", "Ar Rakah", "Al Khobar", "Bldg 1450, Prince Sultan St"),
      S(7100, "Mahd Home Store", "Kettle · 1 pc", 170, "B. Al-Otaibi", "Ar Rakah", "Al Khobar", "Bldg 2208, King Fahd Rd"),
      S(9300, "Qamar Electronics", "Earbuds · 1 pc", 740, "Y. Al-Shehri", "Al Hamra", "Al Khobar", "Bldg 5521, 24th St", { service: "Express" }),
      S(11500, "Bait Matbakh", "Pans · 2 pcs", 260, "W. Al-Jabri", "Al Khobar Ash Shamaliyah", "Al Khobar", "Bldg 1184, Prince Turki St"),
    ],
  },
  {
    id: "majid", name: "Majid", vehicle: "DMM-142", courierId: "C-142", routeKey: "DL-20352", corridorId: "DK-04", originId: "hub-dmm", parcelOrigin: "br-khobar", startM: 1500,
    stops: [
      S(1200, "Nabta Toys", "Toys · 1 pc", 120, "G. Al-Rashidi", "Al Shula", "Dammam", "Bldg 6402, 12th St"),
      S(3000, "Sahab Fashion", "Jacket · 1 pc", 350, "F. Al-Anazi", "Al Faisaliyah", "Dammam", "Bldg 2290, King Khalid St"),
      S(5600, "Zahra Beauty", "Hair dryer", 280, "O. Al-Dosari", "Ar Rakah", "Dammam", "Bldg 880, Prince Mohammed St"),
      S(9100, "Mahd Home Store", "Bedding set", 640, "A. Al-Subaie", "Al Aqrabiyah", "Al Khobar", "Bldg 3150, 20th St", { service: "Express" }),
      S(11700, "Qamar Electronics", "Tablet · 1 pc", 1380, "J. Al-Mansour", "Al Bandariyah", "Al Khobar", "Bldg 7001, King Abdullah St", { service: "Express" }),
    ],
  },
  {
    id: "yousef", name: "Yousef", vehicle: "DMM-207", courierId: "C-207", routeKey: "DL-20417", corridorId: "DM-05", originId: "br-dmm-central", startM: 3000,
    stops: [
      S(700, "Zahra Beauty", "Cosmetics", 240, "H. Al-Mutairi", "Al Faisaliyah", "Dammam", "Bldg 7001, Omar Ibn Al Khattab St"),
      S(1500, "Sahab Fashion", "Dress · 1 pc", 420, "N. Al-Ghamdi", "Al Faisaliyah", "Dammam", "Bldg 7120, Omar Ibn Al Khattab St"),
      S(2300, "Waraq Office Supplies", "Documents", 85, "R. Al-Otaibi", "Al Shula", "Dammam", "Bldg 2150, 14th St", { service: "Express" }),
      S(4400, "Mahd Home Store", "Air fryer · 6.8 kg", 740, "S. Al-Mutairi", "Al Faisaliyah", "Dammam", "Bldg 7342, Omar Ibn Al Khattab St", { service: "Express", id: "DL-20417" }),
      S(5600, "Nabta Toys", "Board game", 140, "L. Al-Zahrani", "Al Nuzha", "Dammam", "Bldg 3050, 16th St"),
      S(6900, "Bait Matbakh", "Cookware", 380, "M. Al-Anazi", "Al Shula", "Dammam", "Bldg 1870, 12th St"),
    ],
  },
  {
    id: "turki", name: "Turki", vehicle: "DMM-212", courierId: "C-212", routeKey: "DL-20507", corridorId: "DM-07", originId: "br-dmm-central", parcelOrigin: "br-dmm-north", startM: 7200,
    stops: [
      S(1400, "Sahab Fashion", "Shoes · 1 pair", 310, "K. Al-Shammari", "Al Badi", "Dammam", "Bldg 4210, 9th St"),
      S(3000, "Zahra Beauty", "Skincare", 190, "A. Al-Dossari", "Al Andalus", "Dammam", "Bldg 1308, 11th St"),
      S(5200, "Bait Matbakh", "Cookware set · 4.2 kg", 520, "N. Al-Rashid", "Al Badi", "Dammam", "Bldg 3307, 22nd St", { id: "DL-20655" }),
      S(7600, "Qamar Electronics", "Speaker", 460, "F. Al-Harbi", "Al Mazruiyah", "Dammam", "Bldg 905, King Saud St"),
      S(10200, "Nabta Toys", "Toys · 3 pcs", 230, "B. Al-Qahtani", "Al Nakheel", "Dammam", "Bldg 2204, 18th St"),
      S(12600, "Mahd Home Store", "Mirror", 410, "T. Al-Subaie", "Al Nakheel", "Dammam", "Bldg 1520, 20th St"),
    ],
  },
  {
    id: "waleed", name: "Waleed", vehicle: "KHB-311", courierId: "C-311", routeKey: "DL-20910", corridorId: "KH-01", originId: "br-khobar", startM: 2200,
    stops: [
      S(900, "Zahra Beauty", "Perfume", 480, "Q. Al-Otaibi", "Al Andalus", "Al Khobar", "Bldg 2206, Makkah St"),
      S(2000, "Waraq Office Supplies", "Documents", 70, "E. Al-Ghamdi", "Al Hizam Al Akhdar", "Al Khobar", "Bldg 305, Prince Faisal bin Fahd St", { service: "Express" }),
      S(3800, "Sahab Fashion", "Clothing", 270, "P. Al-Anazi", "Al Andalus", "Al Khobar", "Bldg 1740, King Saud Rd"),
      S(5400, "Mahd Home Store", "Rug · 1 pc", 590, "U. Al-Dosari", "Al Hizam Al Akhdar", "Al Khobar", "Bldg 880, Prince Faisal bin Fahd St"),
      S(6800, "Nabta Toys", "Toys", 150, "V. Al-Zahrani", "Al Andalus", "Al Khobar", "Bldg 1109, Makkah St"),
    ],
  },
  {
    id: "hamad", name: "Hamad", vehicle: "KHB-305", courierId: "C-305", routeKey: "DL-20533", corridorId: "KH-01", originId: "br-khobar", startM: 4300,
    stops: [
      S(1300, "Bait Matbakh", "Cookware", 360, "X. Al-Mutairi", "Al Hizam Al Akhdar", "Al Khobar", "Bldg 702, 20th St"),
      S(3000, "Qamar Electronics", "Charger", 130, "C. Al-Shehri", "Al Aqrabiyah", "Al Khobar", "Bldg 2810, Khalid St"),
      S(4800, "Zahra Beauty", "Makeup set", 330, "Y. Al-Jabri", "Al Aqrabiyah", "Al Khobar", "Bldg 3320, Khalid St"),
      S(7400, "Mahd Home Store", "Curtains", 450, "O. Al-Rashidi", "Al Thuqbah", "Al Khobar", "Bldg 1005, Southern St"),
      S(9600, "Sahab Fashion", "Abaya", 520, "G. Al-Harbi", "Al Thuqbah", "Al Khobar", "Bldg 1601, Southern St"),
      S(11800, "Nabta Toys", "Scooter", 390, "D. Al-Qahtani", "Al Yarmouk", "Al Khobar", "Bldg 420, King Khalid Rd"),
    ],
  },
];

const DISTRICT_FALLBACK: LngLat = [50.1, 26.4];

/** ~35 m sideways so the stop sits beside the road rather than on the line. */
function offset(p: LngLat, side: number): LngLat {
  return [p[0] + side * 0.00032, p[1] + side * -0.00012];
}

let counter = 0;
function nextPlainId() {
  counter += 1;
  return `DL-${20700 + counter * 7}`;
}

function journeyFor(parcelId: string, merchant: string, service: string, now: number, origin: string, vehicle: string): JourneyEvent[] {
  const mk = (t: number, title: string, source: JourneyEvent["source"], tone: JourneyEvent["tone"], detail?: string): JourneyEvent => ({ id: `${parcelId}-${t}`, shipmentId: parcelId, at: t, title, detail, source, tone });
  const place = places[origin]?.name ?? "Dammam Distribution Hub";
  return [
    mk(at("08:40"), "Order created", "system", "neutral", `${merchant} · ${service}`),
    mk(at("10:20"), `Received at ${place}`, "scan", "neutral"),
    mk(at("11:05"), `Sorted at ${place}`, "scan", "neutral"),
    mk(Math.min(now - 40 * MIN, at("14:30")), "Out for delivery", "scan", "info", `Van ${vehicle}`),
  ];
}

function baseContext(i: number, address: string): ShipmentContext {
  void address;
  return {
    address: { confidence: 0.88 + (i % 5) * 0.02, checks: [{ label: "National Address short code", result: "pass", detail: "Valid code" }], pastFailuresAtAddress: 0, firstDeliveryToAddress: false },
    recipient: { preferredChannel: "WhatsApp", responsiveness: i % 4 === 0 ? "medium" : "high", missedWindows: [] },
    telemetry: {},
  };
}

export interface BuiltWorld {
  drivers: Record<string, Driver>;
  parcels: Record<string, Parcel>;
  contexts: Record<string, ShipmentContext>;
  journeys: Record<string, JourneyEvent[]>;
}

/** Healthy starting state at 15:10: every van moving, nothing wrong. Scenarios then change a few records. */
export function buildWorld(now: number = SCENARIO_START): BuiltWorld {
  counter = 0;
  const drivers: Record<string, Driver> = {};
  const parcels: Record<string, Parcel> = {};
  const contexts: Record<string, ShipmentContext> = {};
  const journeys: Record<string, JourneyEvent[]> = {};
  let n = 0;
  for (const spec of DRIVER_SPECS) {
    const route = routes[spec.routeKey];
    drivers[spec.id] = { id: spec.id, name: spec.name, vehicle: spec.vehicle, routeKey: spec.routeKey, corridorId: spec.corridorId, originId: spec.originId, nav: { distanceM: spec.startM, speedMps: SPEED_MPS, updatedAt: now } };
    spec.stops.forEach((st, idx) => {
      n += 1;
      const id = st.id ?? nextPlainId();
      const p = route ? pointAt(route, st.d) : DISTRICT_FALLBACK;
      const etaMin = Math.max(0, (st.d - spec.startM) / SPEED_MPS / 60);
      const service = st.service ?? "Standard";
      parcels[id] = {
        id,
        driverId: spec.id,
        originId: spec.parcelOrigin ?? spec.originId,
        seq: idx + 1,
        stopAtM: st.d,
        merchant: st.merchant,
        contents: st.contents,
        service,
        payment: st.cod ? { type: "COD", amountSar: st.cod } : { type: "Prepaid" },
        valueSar: st.value,
        recipient: { name: st.recipient },
        address: { line: st.line, district: st.district, city: st.city },
        dest: offset(p, idx % 2 === 0 ? 1 : -1),
        window: { start: now + (etaMin - 40) * MIN, end: now + (etaMin + 90 + (n % 4) * 20) * MIN },
        state: "scheduled",
        attempts: 0,
      };
      contexts[id] = baseContext(n, st.line);
      journeys[id] = journeyFor(id, st.merchant, service, now, spec.parcelOrigin ?? spec.originId, spec.vehicle);
    });
  }
  return { drivers, parcels, contexts, journeys };
}

export const COURIER_ID: Record<string, string> = Object.fromEntries(DRIVER_SPECS.map((d) => [d.id, d.courierId]));
