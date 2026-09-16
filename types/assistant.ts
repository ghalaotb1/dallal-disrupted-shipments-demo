/**
 * Assistant response contract. The chat UI renders these blocks; today they are
 * produced by a rule-based intent layer over live demo data, later by an LLM
 * with tool calling that returns the same block types.
 */

export type AssistantAction =
  | { kind: "open_shipment"; id: string; label?: string }
  | { kind: "focus_shipment"; id: string; label?: string }
  | { kind: "open_incident"; id: string; label?: string }
  | { kind: "focus_incident"; id: string; label?: string }
  | { kind: "open_page"; href: string; label: string }
  | { kind: "ask"; prompt: string; label?: string };

export type AssistantBlock =
  | { type: "kpis"; items: { label: string; value: string; tone?: "neutral" | "ok" | "warn" | "crit" | "review"; hint?: string }[] }
  | { type: "shipment"; id: string }
  | { type: "shipment_list"; title: string; ids: string[]; empty?: string }
  | { type: "timeline"; id: string; limit?: number }
  | { type: "evidence"; id: string }
  | { type: "incident"; id: string }
  | { type: "hourly_chart"; title: string; data: { hour: string; disruptions: number; atRisk: number; recovered: number }[] }
  | { type: "bar_chart"; title: string; unit: string; data: { label: string; value: number; tone?: "neutral" | "warn" | "crit" | "ok" | "brand" }[] }
  | { type: "agent_trace"; shipmentId: string; runId: string }
  | { type: "approvals"; items: { id: string; title: string; detail: string; since: number; target: { type: "shipment" | "incident"; id: string } }[] }
  | { type: "actions"; actions: AssistantAction[] }
  | { type: "note"; text: string };

export interface AssistantResponse {
  intent: string;
  text: string;
  blocks: AssistantBlock[];
  sources: string[];
  followUps: string[];
}

export interface AssistantMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  at: number;
  response?: AssistantResponse;
}
