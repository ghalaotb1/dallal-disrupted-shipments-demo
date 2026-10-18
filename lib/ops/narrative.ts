import type { AgentStep } from "@/types/domain";
import type { LiveInquiry } from "@/types/live";
import type { RunRecord } from "@/types/ops";

export const CAUSE: Record<string, string> = {
  address_issue: "Address problem",
  recipient_unavailable: "Customer not available",
  attempt_not_completed: "Attempt not completed",
  route_disruption: "Road disruption",
  facility_backlog: "Facility backlog",
  pickup_point_unavailable: "Pickup point closed",
  custody_anomaly: "Parcel custody mismatch",
  none: "No real problem",
  unknown: "Unknown pattern",
};

const SOURCE: Record<string, { label: string; area: string }> = {
  get_address_context: { label: "Address", area: "address" },
  get_journey: { label: "Delivery history", area: "journey" },
  get_recipient_context: { label: "Customer", area: "recipient" },
  get_route_context: { label: "Route and van", area: "route" },
  get_facility_context: { label: "Facility", area: "facility" },
  get_pickup_context: { label: "Pickup point", area: "pickup" },
  check_incident_context: { label: "Other deliveries nearby", area: "incident" },
  predict_risk: { label: "Risk model", area: "risk" },
};
const CLOSERS = new Set(["get_shipment", "analyze_disruption", "rank_recovery_actions", "retrieve_policy_constraints"]);

export interface Finding {
  id: string;
  label: string;
  text: string;
  detail?: string;
  tone: "ok" | "warn" | "alert";
  tool: string;
}

export function findings(run: RunRecord): Finding[] {
  return run.ui.steps
    .filter((s) => s.kind !== "inquiry" && !CLOSERS.has(s.backendTool ?? s.tool) && SOURCE[s.backendTool ?? s.tool])
    .map((s) => {
      const tool = s.backendTool ?? s.tool;
      const facts = s.facts ?? [];
      const tone: Finding["tone"] = s.status === "alert" ? "alert" : s.status === "warn" ? "warn" : "ok";
      if (tool === "predict_risk") {
        // Keep the model-vs-heuristic distinction visible: trained models only score the real data they were validated on.
        const heuristic = (facts[0] ?? "").startsWith("HEURISTIC");
        return { id: s.id, label: SOURCE[tool].label, tone, tool, text: heuristic ? `No trained model applies to this simulated parcel, so a hand-written heuristic reads ${/\((\w+)\)/.exec(s.summary ?? "")?.[1] ?? "low"} risk` : (s.summary ?? ""), detail: heuristic ? "The trained risk models abstained: this parcel is outside the real data they were validated on." : facts.slice(0, 2).join(" · ") };
      }
      return { id: s.id, label: SOURCE[tool].label, text: s.summary ?? "", detail: facts.slice(0, 2).join(" · "), tone, tool };
    });
}

export interface BeliefPoint {
  top: [string, number][];
}

/** Belief after the last record check (before any question) and at the end. */
export function beliefStory(run: RunRecord): { before?: BeliefPoint; after?: BeliefPoint; asked: boolean } {
  const t = run.trajectory;
  if (!t.length) return { asked: false };
  const askIdx = t.findIndex((e) => e.after.startsWith("ask:"));
  const asked = askIdx >= 0;
  const before = asked ? t[Math.max(0, askIdx - 1)] : t[0];
  const after = t[t.length - 1];
  return { before: { top: before.top }, after: { top: after.top }, asked };
}

export function askStep(run: RunRecord): AgentStep | undefined {
  return run.ui.steps.find((s) => s.kind === "inquiry");
}

export function inquiryFor(run: RunRecord): LiveInquiry | undefined {
  return run.inquiries[0];
}

export const WHO: Record<string, string> = { recipient: "the customer", courier: "the driver", dispatcher: "the dispatcher", branch_supervisor: "the branch supervisor" };

/** Net value of the best question that was NOT asked (for the "why no question" line). */
export function bestUnaskedQuestion(decision: Record<string, unknown>): { spec: string; net: number } | undefined {
  const rows = (decision.last_candidate_table as { kind: string; source: string; net_voi: number }[] | undefined) ?? [];
  const q = rows.filter((r) => r.kind === "inquiry").sort((a, b) => b.net_voi - a.net_voi)[0];
  return q ? { spec: q.source, net: q.net_voi } : undefined;
}

export interface SafetyCheck {
  label: string;
  pass: boolean;
}

/** The autonomy gates, in plain words, marked pass/fail from the backend's own list of failed gates. */
export function safetyChecks(decision: Record<string, unknown>, valueSar: number): SafetyCheck[] {
  const failed = ((decision.gates as string[] | undefined) ?? []).join(" | ");
  const has = (k: string) => failed.includes(k);
  const rob = typeof decision.robust_effectiveness === "number" ? Math.round(decision.robust_effectiveness * 100) : undefined;
  const post = typeof decision.posterior === "number" ? Math.round(decision.posterior * 100) : undefined;
  return [
    { label: "Reversible, low-impact action", pass: !has("reversible") && !has("automatable") },
    { label: `Parcel value SAR ${valueSar.toLocaleString("en-US")} is within the SAR 1,500 limit`, pass: !has("parcel value") },
    { label: "No more than 2 earlier failed attempts", pass: !has("prior failed") },
    { label: `Confident in the cause${post ? ` (${post}%)` : ""} and nothing unexplained`, pass: !has("outside the known") },
    { label: `Works even in the pessimistic case${rob ? ` (${rob}%)` : ""}`, pass: !has("robust effectiveness") },
    { label: "Evidence agrees with the recorded reason", pass: !has("conflict") },
  ];
}

export function pct(n: number) {
  return `${Math.round(n * 100)}%`;
}

/** The detector's numbers are the backend's; the counts of parcels and drivers are the simulated operation's own (the backend also counts delivered peers). */
export function incidentSentence(rationale: string, affected: number, drivers: number, exposed: number): string {
  const m = /(\d+) related failures in (\d+) min vs baseline ([\d.]+) \(z=([\d.]+)\)/.exec(rationale);
  const head = m ? `${m[1]} related failures in ${m[2]} minutes against a normal ${m[3]} (z=${m[4]}) on the same corridor.` : "Several deliveries on the same corridor failed at once.";
  return `${head} ${affected} deliveries on ${drivers} drivers are delayed and ${exposed} more are heading into the same stretch.`;
}
