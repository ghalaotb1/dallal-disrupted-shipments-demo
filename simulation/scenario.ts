import { getRoute } from "@/data/network";
import { haversine } from "@/lib/geo";
import { fmtKm } from "@/lib/format";
import { SCENARIO_START } from "@/lib/time";
import { incidentService } from "@/services";
import { escalateIncidentSeverity } from "@/services/demo/incidentService";
import { addEvent, completeStep, notify, rescore, setHealth } from "@/services/demo/mutations";
import { anchorMovement, shipmentPosition } from "@/services/logic/movement";
import { demoNow, getWorld, updateWorld, type WorldState } from "@/store/world";
import { pushToast } from "@/store/ui";

/**
 * SIMULATED STORY BEATS. The operations world changes on a schedule (or when the
 * presenter presses "Next event"). Everything that follows — risk scores,
 * diagnoses, incident detection, agent tool paths — is computed by Dallal's logic.
 */

export interface Beat {
  id: string;
  /** demo-clock seconds after 15:10 when autoplay fires the beat */
  at: number;
  title: string;
  run: () => void;
}

export interface StoryStep {
  id: string;
  title: string;
  hint: string;
}

export const STORY_STEPS: StoryStep[] = [
  { id: "overview", title: "Live network overview", hint: "Parcels move across Dammam & Khobar" },
  { id: "at-risk", title: "A shipment is flagged before failure", hint: "DL-20417 turns amber" },
  { id: "prevented", title: "Agent investigates and prevents it", hint: "Open DL-20417 → Investigate → Run action" },
  { id: "disrupted", title: "A failure contradicts its exception code", hint: "DL-20481 turns red" },
  { id: "escalated", title: "High-impact decision goes to a human", hint: "Investigate DL-20481 → Escalate" },
  { id: "incident", title: "Many failures become one incident", hint: "Route DK-04 · King Fahd Rd" },
  { id: "ask-today", title: "Ask: “What happened today?”", hint: "Open the assistant" },
  { id: "ask-where", title: "Ask: “Where is DL-20481?”", hint: "Show it on the live map" },
];

function withShipment(d: WorldState, id: string, fn: (s: WorldState["shipments"][string]) => void) {
  const s = d.shipments[id];
  if (s) fn(s);
}

function corridorSlow(d: WorldState, ids: string[]) {
  for (const id of ids) d.contexts[id] && (d.contexts[id].telemetry = { ...d.contexts[id].telemetry, corridorSpeedKmh: 7, corridorTypicalKmh: 52 });
}

function failOnCorridor(
  d: WorldState,
  id: string,
  opts: { code: string; label: string; by: string; headline: string; attempt?: boolean; stalledMin: number; events: { title: string; detail?: string; source: "gps" | "courier" | "system"; tone: "warn" | "crit" }[] },
) {
  const now = demoNow();
  withShipment(d, id, (s) => {
    s.movement = anchorMovement(s, now);
    // If the van is still rolling toward its queue position, let it crawl to a stop here.
    if (s.movement.mode === "route" && s.movement.holdAtM !== undefined && s.movement.holdAtM - s.movement.distanceM > 80) {
      s.movement.holdAtM = s.movement.distanceM + 120;
    }
    s.movement.stationarySince ??= now - opts.stalledMin * 60_000;
    corridorSlow(d, [id]);
    if (opts.attempt) {
      const pos = shipmentPosition(s, now);
      d.contexts[id].telemetry.attempt = { at: now, distanceToAddressM: Math.round(haversine(pos, s.destination.coord)), dwellSec: 0, callAttempts: 0 };
      s.attempts += 1;
      if (!s.flags.includes("code_conflict")) s.flags.push("code_conflict");
      s.stage = "attempt_failed";
    }
    if (!s.flags.includes("stalled")) s.flags.push("stalled");
    s.exception = { code: opts.code, label: opts.label, recordedAt: now, recordedBy: opts.by };
    s.headline = opts.headline;
    setHealth(d, id, "disrupted");
    opts.events.forEach((e, i) => addEvent(d, id, { at: now - (opts.events.length - 1 - i) * 30_000, ...e, code: e.source === "courier" ? opts.code : undefined }));
    rescore(d, id, now);
  });
}

export const BEATS: Beat[] = [
  {
    id: "at-risk",
    at: 200,
    title: "DL-20417 address validation → at risk",
    run: () => {
      updateWorld((d) => {
        const now = demoNow();
        const ctx = d.contexts["DL-20417"];
        ctx.address = {
          ...ctx.address,
          confidence: 0.34,
          pastFailuresAtAddress: 2,
          checks: [
            { label: "National Address short code", result: "warn", detail: "DFSA7342 resolves to Al Faisaliyah North — 1.2 km from customer pin" },
            { label: "Building number on street", result: "fail", detail: "No building 7342 on Omar Ibn Al Khattab St" },
            { label: "Customer pin vs. National Address", result: "fail", detail: "Pin is 1.2 km from the registered address" },
          ],
        };
        addEvent(d, "DL-20417", { at: now, title: "National Address validation flagged a mismatch", detail: "Short code and customer pin disagree by 1.2 km", source: "system", tone: "warn" });
        rescore(d, "DL-20417", now);
        const s = d.shipments["DL-20417"];
        setHealth(d, "DL-20417", "at_risk");
        s.headline = "Address confidence low — failure likely at the door";
        s.agent = { ...s.agent, state: "monitoring", headline: "Risk rose before any failure", updatedAt: now };
        addEvent(d, "DL-20417", { at: now, title: `Risk rose to ${s.risk.level === "critical" ? "Critical" : "High"} · ${s.risk.score}`, detail: s.risk.drivers.slice(0, 2).map((x) => x.label).join(" · "), source: "model", tone: "warn" });
        notify(d, { at: now, kind: "risk", tone: "warn", title: "DL-20417 flagged at risk before failure", body: `Address confidence 0.34 · risk ${s.risk.score} (prototype heuristic)`, target: { type: "shipment", id: "DL-20417" }, actor: "Risk monitor" });
        completeStep(d, "at-risk");
      });
      pushToast({ tone: "warn", title: "DL-20417 flagged at risk", body: "Predicted before any failure · address confidence low", href: "/shipments/DL-20417", actionLabel: "Investigate" });
    },
  },
  {
    id: "disrupted",
    at: 550,
    title: "DL-20481 failed attempt (RNA) while held on King Fahd Rd",
    run: () => {
      updateWorld((d) => {
        const s = d.shipments["DL-20481"];
        const pos = shipmentPosition(s, demoNow());
        const gap = fmtKm(haversine(pos, s.destination.coord));
        failOnCorridor(d, "DL-20481", {
          code: "RNA",
          label: "Recipient not available",
          by: "Courier C-114",
          headline: `RNA recorded while van was ${gap} from the address`,
          attempt: true,
          stalledMin: 14,
          events: [
            { title: "Van stationary on King Fahd Rd", detail: "Held 14 min · corridor speed 7 km/h", source: "gps", tone: "warn" },
            { title: "Delivery attempt failed · RNA", detail: "Recipient not available — logged by courier C-114", source: "courier", tone: "crit" },
          ],
        });
        notify(d, { at: demoNow(), kind: "risk", tone: "crit", title: "DL-20481 disrupted · exception conflicts with evidence", body: `RNA logged while the van was ${gap} away`, target: { type: "shipment", id: "DL-20481" }, actor: "Journey monitor" });
        completeStep(d, "disrupted");
      });
      pushToast({ tone: "crit", title: "DL-20481 disrupted", body: "RNA code conflicts with GPS evidence", href: "/shipments/DL-20481", actionLabel: "Investigate" });
    },
  },
  {
    id: "corridor-degradation",
    at: 950,
    title: "Two more vans held on King Fahd Rd",
    run: () => {
      updateWorld((d) => {
        corridorSlow(d, ["DL-20334", "DL-20352", "DL-20371", "DL-20390", "DL-20368"]);
        failOnCorridor(d, "DL-20334", {
          code: "DLY",
          label: "Delayed in transit",
          by: "System",
          headline: "Held 31 min on King Fahd Rd · ETA beyond window",
          stalledMin: 31,
          events: [
            { title: "Van stationary on King Fahd Rd", detail: "Held 31 min", source: "gps", tone: "warn" },
            { title: "ETA moved beyond delivery window", detail: "Window 16:00–18:00", source: "system", tone: "crit" },
          ],
        });
        failOnCorridor(d, "DL-20352", {
          code: "DLY",
          label: "Delayed in transit",
          by: "System",
          headline: "Express promise at risk · held on King Fahd Rd",
          stalledMin: 26,
          events: [
            { title: "Van stationary on King Fahd Rd", detail: "Held 26 min", source: "gps", tone: "warn" },
            { title: "Express SLA breach projected", detail: "Promise 17:00", source: "system", tone: "crit" },
          ],
        });
        d.shipments["DL-20352"].flags.push("sla_risk");
        for (const id of ["DL-20334", "DL-20352"]) {
          notify(d, { at: demoNow(), kind: "risk", tone: "crit", title: `${id} delayed on King Fahd Rd`, body: d.shipments[id].headline ?? "", target: { type: "shipment", id }, actor: "Journey monitor" });
        }
      });
      pushToast({ tone: "crit", title: "2 more shipments delayed on King Fahd Rd", body: "DL-20334 · DL-20352" });
    },
  },
  {
    id: "corridor-failures",
    at: 1120,
    title: "DL-20371 and DL-20390 fail on the same corridor",
    run: () => {
      updateWorld((d) => {
        const s = d.shipments["DL-20371"];
        const gap = fmtKm(haversine(shipmentPosition(s, demoNow()), s.destination.coord));
        failOnCorridor(d, "DL-20371", {
          code: "RNA",
          label: "Recipient not available",
          by: "Courier C-157",
          headline: `RNA recorded while van was ${gap} from the address`,
          attempt: true,
          stalledMin: 22,
          events: [
            { title: "Van stationary on King Fahd Rd", detail: "Held 22 min", source: "gps", tone: "warn" },
            { title: "Delivery attempt failed · RNA", detail: "Logged by courier C-157", source: "courier", tone: "crit" },
          ],
        });
        failOnCorridor(d, "DL-20390", {
          code: "DLY",
          label: "Delayed in transit",
          by: "System",
          headline: "Delivery window 15:00–17:00 will be missed",
          stalledMin: 19,
          events: [
            { title: "Van stationary on King Fahd Rd", detail: "Held 19 min", source: "gps", tone: "warn" },
            { title: "Delivery window will be missed", detail: "Window 15:00–17:00", source: "system", tone: "crit" },
          ],
        });
        for (const id of ["DL-20371", "DL-20390"]) {
          notify(d, { at: demoNow(), kind: "risk", tone: "crit", title: `${id} failed on King Fahd Rd`, body: d.shipments[id].headline ?? "", target: { type: "shipment", id }, actor: "Journey monitor" });
        }
      });
      pushToast({ tone: "crit", title: "2 more failures on King Fahd Rd", body: "DL-20371 · DL-20390" });
    },
  },
  {
    id: "incident-detected",
    at: 1180,
    title: "Incident detector groups the corridor failures",
    run: () => {
      incidentService.detect("DK-04");
    },
  },
  {
    id: "severity-increase",
    at: 2100,
    title: "Another van fails — severity increases",
    run: () => {
      const inc = getWorld().incidents["INC-2417"];
      if (!inc || inc.response.state !== "proposed") return;
      updateWorld((d) =>
        failOnCorridor(d, "DL-20368", {
          code: "RSC",
          label: "Reschedule requested by courier",
          by: "Courier C-170",
          headline: "Express pharmacy order held · courier requested reschedule",
          stalledMin: 24,
          events: [
            { title: "Van stationary on King Fahd Rd", detail: "Held 24 min", source: "gps", tone: "warn" },
            { title: "Courier requested reschedule", detail: "Cannot reach Ath Thuqbah before 17:30", source: "courier", tone: "crit" },
          ],
        }),
      );
      escalateIncidentSeverity("INC-2417", "DL-20368");
    },
  },
];

export const beatDueAt = (b: Beat) => SCENARIO_START + b.at * 1000;
export const routeLength = (key: string) => getRoute(key)?.lengthM ?? 0;
