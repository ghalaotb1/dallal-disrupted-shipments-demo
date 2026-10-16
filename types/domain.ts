/**
 * Dallal domain model.
 *
 * These types describe the contract between the UI and the service layer.
 * Today the services are backed by a deterministic demo world; later the same
 * shapes come from real APIs (shipment events, risk model, incident detector,
 * agent orchestration, notification delivery).
 */

export type LngLat = [number, number];
export type DemoTime = number; // epoch milliseconds on the simulated operations clock

export type City = "Dammam" | "Al Khobar" | "Dhahran" | "Saihat";

// ─── Network ────────────────────────────────────────────────────────────────

export type PlaceKind = "hub" | "branch" | "pickup" | "locker";

export interface Place {
  id: string;
  kind: PlaceKind;
  name: string;
  short: string;
  district: string;
  city: City;
  coord: LngLat;
}

export interface Corridor {
  id: string;
  code: string;
  name: string;
  description: string;
}

export interface RoutePath {
  key: string;
  coords: LngLat[];
  /** cumulative distance in metres at each vertex */
  cumulative: number[];
  lengthM: number;
  roads: string[];
}

// ─── Shipment ───────────────────────────────────────────────────────────────

/** Operational health drives color, icon and route styling everywhere. */
export type ShipmentHealth =
  | "on_track"
  | "at_risk"
  | "disrupted"
  | "review"
  | "recovering"
  | "recovered"
  | "prevented"
  | "delivered";

export type ShipmentStage =
  | "at_facility"
  | "out_for_delivery"
  | "attempt_failed"
  | "held"
  | "delivered"
  | "at_pickup_point";

export type Priority = "P1" | "P2" | "P3";
export type RiskLevel = "low" | "elevated" | "high" | "critical";
export type ServiceLevel = "Standard" | "Express" | "Same-day";

export type CaseType =
  | "normal"
  | "address_quality"
  | "recipient_unavailable"
  | "repeated_missed_window"
  | "multiple_failed_attempts"
  | "stalled_no_scan"
  | "route_delay"
  | "route_blocked"
  | "branch_backlog"
  | "pickup_unavailable"
  | "sla_at_risk"
  | "code_conflict"
  | "unknown_pattern"
  | "high_impact_action";

export interface Movement {
  /** moving along route, parked at a facility, or finished */
  mode: "route" | "facility" | "delivered";
  /** metres travelled along the route at `updatedAt` */
  distanceM: number;
  /** demo metres per demo second */
  speedMps: number;
  /** traffic queue / next-stop limit the vehicle cannot pass (approached smoothly) */
  holdAtM?: number;
  facilityId?: string;
  stopsAhead?: number;
  updatedAt: DemoTime;
  stationarySince?: DemoTime;
}

export interface RecordedException {
  code: string;
  label: string;
  recordedAt: DemoTime;
  recordedBy: string;
}

export interface RiskDriver {
  label: string;
  effect: "raises" | "lowers";
  weight: "strong" | "moderate" | "weak";
  source: string;
}

export interface RiskAssessment {
  score: number; // 0–100 (simulated)
  level: RiskLevel;
  drivers: RiskDriver[];
  updatedAt: DemoTime;
  method: "prototype-heuristic";
}

export type AgentState =
  | "monitoring"
  | "investigating"
  | "awaiting_reply"
  | "recommendation"
  | "auto_eligible"
  | "acting"
  | "awaiting_supervisor"
  | "incident"
  | "resolved";

export interface AgentStatus {
  state: AgentState;
  headline?: string;
  lastRunId?: string;
  updatedAt: DemoTime;
}

export interface Owner {
  kind: "agent" | "analyst" | "supervisor" | "branch";
  name: string;
}

export interface ShipmentOutcome {
  kind: "prevented" | "recovered" | "delivered" | "returned";
  label: string;
  at: DemoTime;
}

export interface Shipment {
  id: string;
  orderRef: string;
  merchant: string;
  service: ServiceLevel;
  payment: { type: "Prepaid" } | { type: "COD"; amountSar: number };
  contents: string;
  valueSar: number;
  recipient: { name: string; phone: string };
  address: { line: string; district: string; city: City; shortCode: string };
  originId: string;
  destination: { label: string; district: string; city: City; coord: LngLat };
  corridorId: string;
  routeKey: string;
  altRouteKey?: string;
  courier?: { id: string; name: string; vehicle: string };
  createdAt: DemoTime;
  window: { start: DemoTime; end: DemoTime };
  slaDeadline: DemoTime;
  health: ShipmentHealth;
  stage: ShipmentStage;
  movement: Movement;
  risk: RiskAssessment;
  exception?: RecordedException;
  caseType: CaseType;
  headline?: string;
  agent: AgentStatus;
  owner: Owner;
  priority: Priority;
  incident?: { id: string; role: "affected" | "exposed" };
  flags: ShipmentFlag[];
  attempts: number;
  outcome?: ShipmentOutcome;
  closed: boolean;
  lastEventAt: DemoTime;
  generated?: boolean;
}

export type ShipmentFlag =
  | "code_conflict"
  | "high_value"
  | "cod"
  | "sla_risk"
  | "stalled"
  | "repeat_failure"
  | "first_delivery"
  | "exposed";

// ─── Journey ────────────────────────────────────────────────────────────────

export type EventSource = "scan" | "gps" | "courier" | "recipient" | "system" | "agent" | "analyst" | "supervisor" | "model";
export type EventTone = "neutral" | "info" | "ok" | "warn" | "crit" | "review" | "agent";

export interface JourneyEvent {
  id: string;
  shipmentId: string;
  at: DemoTime;
  title: string;
  detail?: string;
  location?: string;
  source: EventSource;
  tone: EventTone;
  code?: string;
}

// ─── Context used by agent tools (address, recipient, telemetry, facility) ──

export type CheckResult = "pass" | "warn" | "fail";

export interface ShipmentContext {
  address: {
    confidence: number; // 0–1
    checks: { label: string; result: CheckResult; detail: string }[];
    pastFailuresAtAddress: number;
    firstDeliveryToAddress: boolean;
  };
  recipient: {
    preferredChannel: "WhatsApp" | "SMS" | "Call";
    responsiveness: "high" | "medium" | "low";
    confirmedWindow?: { start: DemoTime; end: DemoTime; at: DemoTime };
    missedWindows: { at: DemoTime; window: string; note: string }[];
  };
  telemetry: {
    attempt?: { at: DemoTime; distanceToAddressM: number; dwellSec: number; callAttempts: number };
    corridorSpeedKmh?: number;
    corridorTypicalKmh?: number;
  };
  facility?: {
    placeId: string;
    lastScanAt: DemoTime;
    backlogParcels?: number;
    note?: string;
  };
  custody?: { conflictingScans: boolean; note: string };
  pickupPoint?: { placeId: string; status: "online" | "offline" };
}

// ─── Diagnosis & recovery ───────────────────────────────────────────────────

export type CauseCode =
  | "address_issue"
  | "recipient_unavailable"
  | "attempt_not_completed"
  | "route_disruption"
  | "facility_backlog"
  | "pickup_point_unavailable"
  | "capacity_sequence"
  | "custody_anomaly"
  | "unknown"
  | "none";

export interface Evidence {
  id: string;
  label: string;
  detail: string;
  stance: "supports" | "contradicts" | "context";
  source: string;
}

export interface Diagnosis {
  headline: string;
  summary: string;
  cause: CauseCode;
  causeLabel: string;
  confidence: "high" | "medium" | "low";
  agreement: "agrees" | "conflicts" | "no_code" | "inconclusive";
  recorded?: { code: string; label: string };
  evidence: Evidence[];
}

export type ActionKind =
  | "verify_address"
  | "contact_recipient"
  | "offer_window"
  | "retry_delivery"
  | "redirect_pickup"
  | "redirect_locker"
  | "reroute"
  | "reassign_courier"
  | "resequence_stops"
  | "branch_escalation"
  | "supervisor_escalation"
  | "correct_exception";

export type Level3 = "high" | "medium" | "low";

export interface RecoveryAction {
  id: string;
  kind: ActionKind;
  title: string;
  reason: string;
  tool: string;
  rank: number;
  fit: "strong" | "moderate" | "weak";
  urgency: Level3;
  impact: Level3;
  reversible: boolean;
  approval: "none" | "analyst" | "supervisor";
  approvalReason?: string;
  automatable: boolean;
  factors: { label: string; value: string; basis: "rule" | "assumption" | "simulated" }[];
  score: number;
}

// ─── Agent ──────────────────────────────────────────────────────────────────

export type ToolName =
  | "get_shipment"
  | "get_journey"
  | "get_address_context"
  | "get_route_context"
  | "predict_risk"
  | "analyze_disruption"
  | "check_incident_context"
  | "rank_recovery_actions"
  | "retrieve_policy_constraints"
  | "contact_recipient"
  | "reschedule_delivery"
  | "redirect_to_pickup"
  | "escalate_case"
  | "ask_inquiry"
  | "get_recipient_context"
  | "get_facility_context"
  | "get_pickup_context";

export interface AgentStep {
  id: string;
  tool: ToolName;
  args: string;
  checking: string;
  kind: "read" | "analysis" | "action" | "inquiry";
  /** Live backend only: the question asked to a person, its status, and the belief after this step. */
  inquiryId?: string;
  target?: string;
  inquiryStatus?: string;
  backendTool?: string;
  belief?: { top: [string, number][]; p_systemic: number; entropy_bits: number };
  status: "running" | "ok" | "warn" | "alert";
  summary?: string;
  facts?: string[];
  startedAt: DemoTime;
  durationMs?: number;
}

export type AgentOutcome =
  | { type: "recommend"; actionId: string; headline: string; rationale: string }
  | { type: "auto_eligible"; actionId: string; headline: string; rationale: string }
  | {
      type: "escalate";
      reason: "high_impact" | "conflicting_evidence" | "unknown_pattern";
      headline: string;
      rationale: string;
      question: string;
      actionId?: string;
    }
  | { type: "incident"; incidentId: string; headline: string; rationale: string }
  | { type: "resolved"; headline: string; rationale: string };

export interface AgentRun {
  id: string;
  /** "live" = produced by the real backend; absent/"demo" = the in-browser prototype planner. */
  source?: "live" | "demo";
  backendStatus?: string;
  backend?: import("@/types/live").LiveRunMeta;
  shipmentId: string;
  mode: "investigation" | "execution";
  trigger: "analyst" | "scheduled" | "auto";
  status: "running" | "completed";
  startedAt: DemoTime;
  finishedAt?: DemoTime;
  steps: AgentStep[];
  outcome?: AgentOutcome;
  diagnosis?: Diagnosis;
  actions?: RecoveryAction[];
}

// ─── Incidents ──────────────────────────────────────────────────────────────

export type Severity = "low" | "medium" | "high" | "critical";

export interface IncidentEvent {
  id: string;
  at: DemoTime;
  title: string;
  detail?: string;
  tone: EventTone;
  actor: string;
}

export interface ResponseStep {
  id: string;
  title: string;
  detail: string;
  shipments: string[];
  tool: string;
}

export interface Incident {
  id: string;
  kind: "route" | "branch" | "pickup_point";
  title: string;
  subtitle: string;
  severity: Severity;
  status: "active" | "mitigating" | "resolved";
  detectedAt: DemoTime;
  resolvedAt?: DemoTime;
  sharedFactor: {
    label: string;
    detail: string;
    coord: LngLat;
    radiusM: number;
    corridorId?: string;
    placeId?: string;
    segment?: { routeKey: string; fromM: number; toM: number };
  };
  signals: { label: string; value: string; detail: string }[];
  detector: {
    method: string;
    window: string;
    baselineMean: number;
    baselineStd: number;
    observed: number;
    z: number;
    threshold: number;
    series: { label: string; count: number; current?: boolean }[];
  };
  affected: string[];
  exposed: string[];
  owner: { name: string; role: string };
  response: {
    state: "proposed" | "awaiting_approval" | "approved" | "applied";
    summary: string;
    steps: ResponseStep[];
    approvalRequired: boolean;
    approvedBy?: string;
    appliedAt?: DemoTime;
  };
  supervisorNotifiedAt?: DemoTime;
  timeline: IncidentEvent[];
  simulatedCause: string;
}

// ─── Notifications & outcome ledger ─────────────────────────────────────────

export type NotificationKind = "escalation" | "incident" | "agent" | "outcome" | "risk" | "approval";

export interface AppNotification {
  id: string;
  at: DemoTime;
  kind: NotificationKind;
  tone: "info" | "ok" | "warn" | "crit" | "review";
  title: string;
  body: string;
  read: boolean;
  target: { type: "shipment" | "incident"; id: string };
  actor: string;
  emailId?: string;
}

export interface SimulatedEmail {
  id: string;
  at: DemoTime;
  from: string;
  to: string;
  cc?: string;
  subject: string;
  preheader: string;
  greeting: string;
  summary: { label: string; value: string }[];
  reason: string;
  checks: string[];
  evidence: string[];
  question?: string;
  recommendation: string;
  operatorNote?: string;
  link: { label: string; href: string };
}

export interface Escalation {
  id: string;
  at: DemoTime;
  target: { type: "shipment" | "incident"; id: string };
  to: { name: string; role: string };
  priority: Priority;
  reason: string;
  question: string;
  options: string[];
  note?: string;
  status: "awaiting" | "approved" | "resolved";
  emailId?: string;
}

export interface LedgerEntry {
  id: string;
  at: DemoTime;
  shipmentId?: string;
  incidentId?: string;
  decision: string;
  decidedBy: "Agent (automated)" | "Analyst" | "Shift supervisor" | "Agent → Supervisor";
  basis: string;
  outcome: "pending" | "prevented" | "recovered" | "resolved" | "escalated";
  outcomeAt?: DemoTime;
}
