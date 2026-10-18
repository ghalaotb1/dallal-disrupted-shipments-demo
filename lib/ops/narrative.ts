import type { AgentStep } from "@/types/domain";
import type { LiveInquiry } from "@/types/live";
import type { OpsWorld, RunRecord, ScenarioCase } from "@/types/ops";

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
  const rob = typeof decision.robust_effectiveness === "number" ? ` · ${Math.round(decision.robust_effectiveness * 100)}%` : "";
  const post = typeof decision.posterior === "number" ? ` · ${Math.round(decision.posterior * 100)}%` : "";
  return [
    { label: "Reversible, low impact", pass: !has("reversible") && !has("automatable") },
    { label: `Value SAR ${valueSar.toLocaleString("en-US")} within SAR 1,500`, pass: !has("parcel value") },
    { label: "At most 2 earlier failures", pass: !has("prior failed") },
    { label: `Confident in the cause${post}`, pass: !has("outside the known") },
    { label: `Safe in the worst case${rob}`, pass: !has("robust effectiveness") },
    { label: "Matches the recorded reason", pass: !has("conflict") },
  ];
}

export function pct(n: number) {
  return `${Math.round(n * 100)}%`;
}

/** The detector's numbers are the backend's; the counts of parcels and drivers are the operation's own (the backend also counts delivered peers). */
export function incidentSentence(rationale: string, affected: number, drivers: number, exposed: number): string {
  const m = /(\d+) related failures in (\d+) min vs baseline ([\d.]+)/.exec(rationale);
  const head = m ? `${m[1]} failures in ${m[2]} min (normal ${m[3]}).` : "Several failures on one corridor.";
  return `${head} ${affected} delayed on ${drivers} drivers · ${exposed} more exposed.`;
}

export interface CaseStatus {
  label: string;
  tone: "new" | "work" | "wait" | "ok" | "manager";
}

/** One-word state of a case for lists and headers, from the real run and plan. */
export function caseStatus(w: OpsWorld, c: ScenarioCase): CaseStatus {
  if (c.running) return { label: "Investigating", tone: "work" };
  const run = c.runId ? w.runs[c.runId] : undefined;
  if (!run) return { label: "New", tone: "new" };
  const hero = w.parcels[c.parcelId];
  const type = String(run.decision.type ?? "");
  if (run.status === "awaiting_response") return { label: "Waiting for a reply", tone: "wait" };
  if (type === "incident") {
    const plan = c.planId ? w.plans[c.planId] : undefined;
    if (!plan || plan.status === "awaiting_evidence") return { label: "Asking the dispatcher", tone: "wait" };
    if (plan.status === "ready") return { label: "Needs manager", tone: "manager" };
    if (plan.status === "executed_simulated") return { label: "Plan executed", tone: "ok" };
    return { label: "Rejected", tone: "new" };
  }
  if (type === "escalate") return { label: hero.state === "recovering" ? "Manager took over" : "Needs manager", tone: hero.state === "recovering" ? "ok" : "manager" };
  if (type === "recommend") return hero.state === "scheduled" || hero.state === "attempt_failed" ? { label: "Needs confirmation", tone: "wait" } : { label: "Resolved", tone: "ok" };
  if (type === "auto_eligible") return hero.state === "prevented" || hero.state === "recovered" ? { label: "Resolved by Dallal", tone: "ok" } : { label: "Resolving", tone: "work" };
  return { label: "Checked", tone: "ok" };
}

/** How many story items a run reveals (findings, the question, the conclusion and the decision); the story shows them one by one. */
export function revealTotal(run: RunRecord): number {
  return findings(run).length + (askStep(run) ? 1 : 0) + (run.status === "awaiting_response" ? 0 : 2);
}
