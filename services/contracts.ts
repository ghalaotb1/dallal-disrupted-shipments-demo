import type { AssistantMessage, AssistantResponse } from "@/types/assistant";
import type {
  AgentRun,
  AppNotification,
  Escalation,
  Incident,
  JourneyEvent,
  Priority,
  RiskAssessment,
  Shipment,
} from "@/types/domain";

/**
 * Service contracts. The prototype binds these to deterministic demo adapters
 * (services/demo/*). Production adapters implement the same interfaces over
 * REST/SSE — the UI does not change.
 */

export interface SearchHit {
  type: "shipment" | "incident" | "place";
  id: string;
  title: string;
  subtitle: string;
  href?: string;
}

export interface ShipmentService {
  list(opts?: { includeClosed?: boolean }): Promise<Shipment[]>;
  get(id: string): Promise<Shipment | undefined>;
  getJourney(id: string): Promise<JourneyEvent[]>;
  search(text: string): SearchHit[];
}

export interface RiskService {
  /** Today: prototype heuristic. Next phase: trained failure-risk model via predict_risk(). */
  assess(shipmentId: string): Promise<RiskAssessment>;
}

export interface IncidentService {
  list(): Promise<Incident[]>;
  get(id: string): Promise<Incident | undefined>;
  detect(corridorId: string): Incident | null;
  applyGroupResponse(id: string, onProgress?: (stage: GroupResponseStage) => void): Promise<void>;
  resolve(id: string): Promise<void>;
}

export type GroupResponseStage =
  | { stage: "approval_requested" }
  | { stage: "approved"; by: string }
  | { stage: "step_started"; stepId: string }
  | { stage: "step_done"; stepId: string }
  | { stage: "done" };

export interface AgentService {
  investigate(shipmentId: string): Promise<AgentRun>;
  execute(shipmentId: string, actionId: string, opts?: { approvedBy?: string }): Promise<AgentRun>;
}

export interface EscalationInput {
  target: { type: "shipment" | "incident"; id: string };
  priority: Priority;
  reason: string;
  question: string;
  options: string[];
  checks: string[];
  evidence: string[];
  recommendation: string;
  summary: { label: string; value: string }[];
  note?: string;
}

export interface NotificationService {
  list(): Promise<AppNotification[]>;
  markRead(id: string): void;
  markAllRead(): void;
  sendEscalation(input: EscalationInput): Promise<Escalation>;
}

export interface AssistantService {
  ask(query: string, history: AssistantMessage[]): Promise<AssistantResponse>;
}
