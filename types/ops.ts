import type { AgentRun, DemoTime, JourneyEvent, LngLat, ShipmentContext, ShipmentHealth } from "@/types/domain";
import type { LiveInquiry, LivePlan } from "@/types/live";

/**
 * Route-centric operations model. A driver carries one route and many parcels; everything the operator sees is grouped that way.
 * ALL of it is a simulated operation (fictional drivers, parcels and recipients on real Eastern Province roads).
 */

export type ScenarioId = "A" | "B" | "C";

/** What happened to a parcel, independent of where the van is. "scheduled" parcels are delivered on the way (derived from the van position). */
export type ParcelState =
  | "scheduled"
  | "attempt_failed"
  | "at_risk"
  | "recovering"
  | "prevented"
  | "recovered"
  | "awaiting_manager"
  | "reassigned";

export type RecoveryKind = "spare" | "pickup" | "wait" | "reroute" | "defer" | "contact";

export interface Driver {
  id: string;
  name: string;
  nameAr: string;
  vehicle: string;
  routeKey: string;
  corridorId: string;
  originId: string;
  /** Position along the route: metres at `updatedAt`, advancing at `speedMps` per demo second until `holdAtM` (traffic, a breakdown). */
  nav: { distanceM: number; speedMps: number; updatedAt: DemoTime; holdAtM?: number };
  /** Short note shown on the route card while something is wrong ("Slow traffic on King Fahd Rd"). */
  note?: string;
}

export interface Parcel {
  id: string;
  driverId: string;
  /** The facility that sorted this parcel (parcels on one van can come from different facilities). */
  originId: string;
  seq: number;
  stopAtM: number;
  merchant: string;
  contents: string;
  service: "Standard" | "Express" | "Same-day";
  payment: { type: "Prepaid" } | { type: "COD"; amountSar: number };
  valueSar: number;
  recipient: { name: string };
  address: { line: string; district: string; city: string };
  dest: LngLat;
  window: { start: DemoTime; end: DemoTime };
  state: ParcelState;
  /** One-line plain-language status for the current state ("Address not found at the door"). */
  headline?: string;
  /** When the parcel left its route because of a coordinated plan (spare courier, pickup point...). */
  recovery?: { kind: RecoveryKind; label: string; etaAt?: DemoTime; fromPlan?: boolean };
  /** Result observed in the SIMULATED world after an action; never claimed before it happens. */
  simOutcome?: { kind: "prevented" | "recovered"; label: string; at: DemoTime };
  exception?: { code: string; label: string; recordedAt: DemoTime };
  attempts: number;
  incident?: boolean;
}

export interface ScenarioCase {
  scenario: ScenarioId;
  /** Short product label, e.g. "Address not found". */
  label: string;
  /** The parcel whose problem Dallal investigates (the one that shows the problem first). */
  parcelId: string;
  driverId: string;
  /** Other drivers touched by the same disruption (scenario C). */
  affectedDriverIds: string[];
  /** Parcels exposed to the same disruption but not failed yet (scenario C). */
  exposedParcelIds: string[];
  runId?: string;
  planId?: string;
  startedAt?: number;
  /** One-line problem statement. */
  problem: { title: string; detail: string };
  /** The sandbox dispatcher's automatic reply to the plan question: typing, delivered through the real inbound path, or failed (manual fallback). */
  reply?: "typing" | "sent" | "failed";
  /** True while the agent run for this case is in flight. */
  running?: boolean;
  error?: string;
}

/** A backend run as the screens need it: the UI-shaped trace plus the raw decision (gates, rationale) and its WhatsApp inquiries. */
export interface RunRecord {
  ui: AgentRun;
  decision: Record<string, unknown>;
  status: string;
  inquiries: LiveInquiry[];
  /** Belief trajectory (top cause + probability after each step), from the backend trace. */
  trajectory: { after: string; top: [string, number][] }[];
}

export interface OpsEvent {
  id: string;
  at: DemoTime;
  text: string;
  tone: "info" | "ok" | "warn" | "review";
  parcelId?: string;
}

export interface OpsWorld {
  generation: number;
  clock: { baseDemo: DemoTime; baseReal: number; scale: number; running: boolean };
  drivers: Record<string, Driver>;
  parcels: Record<string, Parcel>;
  contexts: Record<string, ShipmentContext>;
  journeys: Record<string, JourneyEvent[]>;
  runs: Record<string, RunRecord>;
  plans: Record<string, LivePlan>;
  /** Parcel states before a plan was applied, to show what the single dispatcher answer changed. */
  planBefore: Record<string, Record<string, string>>;
  events: OpsEvent[];
  /** The open cases of the operation (one per situation Dallal is handling). */
  cases: ScenarioCase[];
  /** The blocked road section (scenario C), shown on the map. */
  blockage: { coord: LngLat; radiusM: number; label: string } | null;
}

export type { ShipmentHealth };

export interface AssistantMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  /** Answer lifecycle: reading data / loading the model → streaming tokens → done. */
  status?: "thinking" | "streaming" | "done";
  phase?: string;
  /** "qwen" = the local model answered from live data; "basic" = deterministic fallback. */
  mode?: "qwen" | "basic";
  note?: string;
  meta?: { model: string; latencyS: number; firstTokenS?: number | null };
  sources?: { type: "parcel" | "driver" | "run" | "plan" | "overview"; id: string; label: string }[];
  /** Things the operator can open from the answer (a case, a parcel, a driver). */
  links?: { label: string; sub?: string; target: { kind: "case"; id: ScenarioId } | { kind: "parcel"; id: string } | { kind: "driver"; id: string } }[];
}
