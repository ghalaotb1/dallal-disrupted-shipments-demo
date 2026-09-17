import { corridors, getRoute, places } from "@/data/network";
import { people } from "@/data/people";
import { fmtKm, plural } from "@/lib/format";
import { at, fmtDuration, fmtTime, fmtWindow, sameDay } from "@/lib/time";
import { analyzeDisruption } from "@/services/logic/diagnosis";
import { remainingM } from "@/services/logic/movement";
import { compareByPriority } from "@/services/logic/priority";
import { completeStep } from "@/services/demo/mutations";
import { demoNow, getWorld, updateWorld, type WorldState } from "@/store/world";
import type { AssistantService } from "@/services/contracts";
import type { AssistantBlock, AssistantResponse } from "@/types/assistant";
import type { CaseType, Shipment } from "@/types/domain";

/**
 * PROTOTYPE ASSISTANT — intent routing over the live demo world.
 * Every answer is computed from current state (nothing is canned), and the
 * response format is the same one an LLM + tool-calling backend would return.
 */

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

const CASE_LABEL: Record<CaseType, string> = {
  normal: "Normal",
  address_quality: "Address quality",
  recipient_unavailable: "Recipient unavailable",
  repeated_missed_window: "Missed delivery windows",
  multiple_failed_attempts: "Multiple failed attempts",
  stalled_no_scan: "Stalled · no scan",
  route_delay: "Route delay",
  route_blocked: "Route blocked",
  branch_backlog: "Branch backlog",
  pickup_unavailable: "Pickup point unavailable",
  sla_at_risk: "SLA at risk",
  code_conflict: "Exception code conflict",
  unknown_pattern: "Unknown pattern",
  high_impact_action: "High-impact action",
};

const CITY_WORDS: Record<string, Shipment["destination"]["city"]> = { dammam: "Dammam", khobar: "Al Khobar", dhahran: "Dhahran", saihat: "Saihat" };

const isAttention = (s: Shipment) => !s.closed && (s.health === "review" || s.health === "disrupted" || s.health === "at_risk");

function locationSentence(s: Shipment, w: WorldState, now: number) {
  if (s.closed || s.movement.mode === "delivered") return s.outcome ? `${s.outcome.label.toLowerCase()} at ${fmtTime(s.outcome.at)}` : "delivered";
  if (s.movement.mode === "facility") return `at ${places[s.movement.facilityId!].name}`;
  const corridor = corridors[s.corridorId];
  const rem = remainingM(s, now);
  const held = s.movement.stationarySince || (s.movement.holdAtM !== undefined && s.health !== "on_track");
  if (s.incident && w.incidents[s.incident.id]?.sharedFactor.corridorId === s.corridorId && held) {
    return `held on ${corridor.name} (${w.incidents[s.incident.id].sharedFactor.label.split("·")[1]?.trim() ?? corridor.code}), ${fmtKm(rem)} from ${s.destination.district}`;
  }
  return `on the road via ${corridor.name} (${corridor.code}), ${fmtKm(rem)} from ${s.destination.district}`;
}

const HEALTH_WORD: Record<Shipment["health"], string> = {
  on_track: "on track",
  at_risk: "at risk",
  disrupted: "disrupted",
  review: "waiting for human review",
  recovering: "recovering",
  recovered: "recovered",
  prevented: "on track after a prevented failure",
  delivered: "delivered",
};

function shipmentWhere(s: Shipment, w: WorldState, now: number): AssistantResponse {
  const parts = [`**${s.id}** is ${locationSentence(s, w, now)}. It is ${HEALTH_WORD[s.health]}`];
  if (s.health === "disrupted" && s.flags.includes("code_conflict")) parts[0] += ", and the recorded exception conflicts with GPS evidence";
  parts[0] += ".";
  if (s.incident) parts.push(`It is part of incident **${s.incident.id}** (${s.incident.role}).`);
  if (s.agent.state === "awaiting_supervisor") parts.push(`Awaiting approval from ${people.supervisor.name}.`);
  const actions: AssistantBlock = {
    type: "actions",
    actions: [
      ...(s.closed ? [] : [{ kind: "focus_shipment" as const, id: s.id, label: "Show on map" }]),
      { kind: "open_shipment", id: s.id, label: "Open Shipment Intelligence" },
      ...(s.incident ? [{ kind: "open_incident" as const, id: s.incident.id, label: `Open ${s.incident.id}` }] : []),
    ],
  };
  return {
    intent: "shipment_location",
    text: parts.join(" "),
    blocks: [{ type: "shipment", id: s.id }, actions],
    sources: ["get_shipment", "get_journey", "route geometry"],
    followUps: [`Why is ${s.id} ${s.health === "on_track" ? "on track" : "disrupted"}?`, `What did the Agent do for ${s.id}?`],
  };
}

function shipmentWhy(s: Shipment, w: WorldState, now: number): AssistantResponse {
  const d = analyzeDisruption({ shipment: s, context: w.contexts[s.id], now, corridorPeers: Object.values(w.shipments).filter((p) => p.corridorId === s.corridorId && !p.closed) });
  const conflict = d.agreement === "conflicts" ? ` The recorded code **${d.recorded?.code}** (“${d.recorded?.label}”) is not supported by the evidence.` : "";
  const text =
    d.cause === "none"
      ? `**${s.id}** has no active disruption — ${d.summary.toLowerCase()}`
      : `**${d.headline}.** ${d.summary}${conflict} Likely cause: ${d.causeLabel.toLowerCase()} (confidence ${d.confidence}).`;
  return {
    intent: "shipment_why",
    text,
    blocks: [
      { type: "evidence", id: s.id },
      { type: "timeline", id: s.id, limit: 4 },
      { type: "actions", actions: [{ kind: "open_shipment", id: s.id, label: "Open Shipment Intelligence" }, ...(s.incident ? [{ kind: "open_incident" as const, id: s.incident.id }] : [])] },
    ],
    sources: ["get_journey", "analyze_disruption"],
    followUps: [`What did the Agent do for ${s.id}?`, `Where is ${s.id}?`],
  };
}

function shipmentAgent(s: Shipment, w: WorldState): AssistantResponse {
  const runs = Object.values(w.agentRuns)
    .filter((r) => r.shipmentId === s.id)
    .sort((a, b) => b.startedAt - a.startedAt);
  const inv = runs.find((r) => r.mode === "investigation");
  const exec = runs.find((r) => r.mode === "execution");
  if (!inv) {
    return {
      intent: "shipment_agent",
      text: `The agent is **monitoring** ${s.id} but has not investigated it yet${s.incident ? ` — it is handled at incident level under ${s.incident.id}` : ""}. You can start an investigation from Shipment Intelligence.`,
      blocks: [{ type: "shipment", id: s.id }, { type: "actions", actions: [{ kind: "open_shipment", id: s.id, label: "Open & investigate" }] }],
      sources: ["agent run log"],
      followUps: [`Why is ${s.id} ${s.health === "on_track" ? "on track" : "disrupted"}?`],
    };
  }
  const tools = inv.steps.map((x) => x.tool);
  let text = `At **${fmtTime(inv.startedAt)}** the agent investigated ${s.id} with ${plural(tools.length, "tool call")} and concluded: *${inv.outcome?.headline ?? "in progress"}*.`;
  if (exec?.outcome) text += ` At ${fmtTime(exec.startedAt)} it executed the action — ${exec.outcome.headline.toLowerCase()}.`;
  else if (s.agent.state === "awaiting_supervisor") text += ` Because the action needed approval, the case went to ${people.supervisor.name}.`;
  return {
    intent: "shipment_agent",
    text,
    blocks: [{ type: "agent_trace", shipmentId: s.id, runId: inv.id }, ...(exec ? [{ type: "agent_trace" as const, shipmentId: s.id, runId: exec.id }] : []), { type: "actions", actions: [{ kind: "open_shipment", id: s.id, label: "Open Shipment Intelligence" }] }],
    sources: ["agent run log"],
    followUps: [`Why is ${s.id} ${s.health === "on_track" ? "on track" : "disrupted"}?`, "Which shipments are waiting for supervisor approval?"],
  };
}

function dailySummary(w: WorldState, now: number): AssistantResponse {
  const all = Object.values(w.shipments);
  const active = all.filter((s) => !s.closed);
  const today = (t?: number) => t !== undefined && sameDay(t, now) && t <= now;
  const exceptions = all.filter((s) => today(s.exception?.recordedAt));
  const prevented = all.filter((s) => s.outcome?.kind === "prevented" && today(s.outcome.at));
  const recovered = all.filter((s) => s.outcome?.kind === "recovered" && today(s.outcome.at));
  const openIncidents = Object.values(w.incidents).filter((i) => i.status !== "resolved");
  const awaiting = w.escalations.filter((e) => e.status === "awaiting");

  const startHour = 8;
  const endHour = Number(fmtTime(now).slice(0, 2));
  const hourly: { hour: string; exceptions: number; recovered: number }[] = [];
  for (let h = startHour; h <= endHour; h++) {
    const from = at(`${String(h).padStart(2, "0")}:00`);
    const to = from + 3_600_000;
    const inHour = (t?: number) => t !== undefined && t >= from && t < to && t <= now;
    const riskFlags = Object.values(w.journeys)
      .flat()
      .filter((e) => e.source === "model" && e.tone === "warn" && inHour(e.at)).length;
    hourly.push({
      hour: `${String(h).padStart(2, "0")}:00`,
      exceptions: all.filter((s) => inHour(s.exception?.recordedAt)).length + riskFlags,
      recovered: all.filter((s) => (s.outcome?.kind === "recovered" || s.outcome?.kind === "prevented") && inHour(s.outcome.at)).length,
    });
  }

  const causeCounts = new Map<string, number>();
  for (const s of all) {
    if (s.caseType === "normal" || !(today(s.exception?.recordedAt) || s.health !== "on_track" || s.outcome)) continue;
    if (s.health === "delivered" && !s.exception) continue;
    const label = CASE_LABEL[s.caseType];
    causeCounts.set(label, (causeCounts.get(label) ?? 0) + 1);
  }
  const causes = [...causeCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([label, value], i) => ({ label, value, tone: (i === 0 ? "brand" : "neutral") as "brand" | "neutral" }));

  const headline = openIncidents.find((i) => i.kind === "route") ?? openIncidents[0];
  let text = `Since 08:00 the Dammam–Khobar network recorded **${plural(exceptions.length, "exception")}**. Dallal **prevented ${plural(prevented.length, "failure")}** before they happened and **recovered ${plural(recovered.length, "shipment")}**.`;
  if (headline) {
    text += ` The biggest issue right now is **${headline.id} · ${headline.title}**: ${plural(headline.affected.length, "failure")} grouped into one incident${headline.exposed.length ? `, with ${headline.exposed.length} more shipments exposed` : ""}.`;
  }
  if (awaiting.length) text += ` ${plural(awaiting.length, "case")} ${awaiting.length === 1 ? "is" : "are"} waiting for ${people.supervisor.name}.`;

  updateWorld((d) => completeStep(d, "ask-today"));
  return {
    intent: "daily_summary",
    text,
    blocks: [
      {
        type: "kpis",
        items: [
          { label: "Active", value: String(active.length) },
          { label: "At risk", value: String(active.filter((s) => s.health === "at_risk").length), tone: "warn" },
          { label: "Disrupted", value: String(active.filter((s) => s.health === "disrupted").length), tone: "crit" },
          { label: "Incidents", value: String(openIncidents.length), tone: openIncidents.length ? "crit" : "neutral" },
          { label: "Prevented", value: String(prevented.length), tone: "ok" },
          { label: "Recovered", value: String(recovered.length), tone: "ok" },
        ],
      },
      { type: "hourly_chart", title: "Exceptions & risk flags vs. recoveries, by hour", data: hourly },
      { type: "bar_chart", title: "Top exception causes today", unit: "shipments", data: causes },
      ...(headline ? [{ type: "incident" as const, id: headline.id }] : []),
      { type: "actions", actions: [{ kind: "open_page", href: "/incidents", label: "Open incidents" }, { kind: "open_page", href: "/shipments?tab=ledger", label: "Outcome ledger" }] },
    ],
    sources: ["shipments", "journey events", "incidents", "outcome ledger"],
    followUps: ["Which route has the most issues today?", "Which shipments need attention right now?", "Where is DL-20481?"],
  };
}

function attention(w: WorldState): AssistantResponse {
  const list = Object.values(w.shipments).filter(isAttention).sort(compareByPriority);
  const grouped = list.filter((s) => s.incident);
  const individual = list.filter((s) => !s.incident);
  const top = individual[0] ?? list[0];
  const incidents = Object.values(w.incidents).filter((i) => i.status === "active");
  let text = `**${plural(list.length, "shipment")}** need attention.`;
  if (grouped.length) text += ` ${grouped.length} of them are covered by ${plural(new Set(grouped.map((s) => s.incident!.id)).size, "incident")}, so you can resolve them as groups.`;
  if (top) text += ` Most urgent individual case: **${top.id}** (${top.priority} · ${HEALTH_WORD[top.health]}) — ${top.headline ?? top.caseType.replace(/_/g, " ")}.`;
  return {
    intent: "attention",
    text,
    blocks: [
      ...incidents.map((i) => ({ type: "incident" as const, id: i.id })),
      { type: "shipment_list", title: "Individual cases by priority", ids: individual.slice(0, 6).map((s) => s.id), empty: "No individual cases" },
    ],
    sources: ["shipments", "incidents"],
    followUps: ["Which shipments are waiting for supervisor approval?", "Show me high-risk shipments in Dammam."],
  };
}

function highRisk(w: WorldState, city?: Shipment["destination"]["city"]): AssistantResponse {
  const list = Object.values(w.shipments)
    .filter((s) => !s.closed && (s.risk.level === "high" || s.risk.level === "critical") && (!city || s.destination.city === city))
    .sort((a, b) => b.risk.score - a.risk.score);
  return {
    intent: "high_risk",
    text: list.length
      ? `**${plural(list.length, "high-risk shipment")}**${city ? ` in ${city}` : ""}. Scores are from the prototype risk heuristic (simulated inputs), not a trained model.`
      : `No high-risk shipments${city ? ` in ${city}` : ""} right now.`,
    blocks: [
      { type: "shipment_list", title: `High risk${city ? ` · ${city}` : ""}`, ids: list.slice(0, 8).map((s) => s.id) },
      ...(list[0] ? [{ type: "actions" as const, actions: [{ kind: "focus_shipment" as const, id: list[0].id, label: `Show ${list[0].id} on map` }] }] : []),
    ],
    sources: ["shipments", "predict_risk (prototype)"],
    followUps: ["Why is " + (list[0]?.id ?? "DL-20481") + " at risk?", "What happened today?"],
  };
}

function incidentsAnswer(w: WorldState, now: number): AssistantResponse {
  const all = Object.values(w.incidents).sort((a, b) => b.detectedAt - a.detectedAt);
  const open = all.filter((i) => i.status !== "resolved");
  const resolved = all.filter((i) => i.status === "resolved" && sameDay(i.detectedAt, now));
  const text = open.length
    ? `**${plural(open.length, "operational incident")}** open. ${open
        .map((i) => `**${i.id}** — ${i.title} (${i.severity}, ${i.status}): ${plural(i.affected.length, "affected shipment")}, ${i.exposed.length} exposed.`)
        .join(" ")}${resolved.length ? ` ${resolved.length} resolved earlier today.` : ""}`
    : "No open operational incidents.";
  return {
    intent: "incidents",
    text,
    blocks: [...open.map((i) => ({ type: "incident" as const, id: i.id })), { type: "actions", actions: [{ kind: "open_page", href: "/incidents", label: "All incidents" }] }],
    sources: ["incident detector"],
    followUps: ["Which route has the most issues today?", "Summarize today's disruptions."],
  };
}

function approvals(w: WorldState, now: number): AssistantResponse {
  const items: Extract<AssistantBlock, { type: "approvals" }>["items"] = [];
  for (const e of w.escalations.filter((x) => x.status === "awaiting")) {
    items.push({ id: e.id, title: `${e.target.id} · ${e.reason}`, detail: e.question, since: e.at, target: e.target });
  }
  for (const i of Object.values(w.incidents)) {
    if (i.response.state === "proposed" && i.status === "active") items.push({ id: i.id, title: `${i.id} · group response`, detail: i.response.summary, since: i.detectedAt, target: { type: "incident", id: i.id } });
  }
  for (const s of Object.values(w.shipments)) {
    if (s.closed || s.agent.state !== "recommendation" || !s.agent.lastRunId) continue;
    const run = w.agentRuns[s.agent.lastRunId];
    if (run?.outcome?.type === "escalate") items.push({ id: `${s.id}-esc`, title: `${s.id} · escalation recommended`, detail: run.outcome.question, since: run.finishedAt ?? now, target: { type: "shipment", id: s.id } });
  }
  return {
    intent: "approvals",
    text: items.length
      ? `**${plural(items.length, "decision")}** waiting on ${people.supervisor.name} (${people.supervisor.role.toLowerCase()}). The oldest has been waiting ${fmtDuration(now - Math.min(...items.map((i) => i.since)))}.`
      : `Nothing is waiting for ${people.supervisor.name} right now.`,
    blocks: [{ type: "approvals", items }],
    sources: ["escalations", "incident responses", "agent recommendations"],
    followUps: ["Which shipments need attention right now?", "Are there any active operational incidents?"],
  };
}

function routeRanking(w: WorldState, now: number): AssistantResponse {
  const counts = new Map<string, Shipment[]>();
  for (const s of Object.values(w.shipments)) {
    const issue = (s.exception && sameDay(s.exception.recordedAt, now)) || s.health === "disrupted" || s.health === "at_risk" || s.health === "review";
    if (!issue) continue;
    const list = counts.get(s.corridorId) ?? [];
    list.push(s);
    counts.set(s.corridorId, list);
  }
  const ranked = [...counts.entries()].sort((a, b) => b[1].length - a[1].length);
  const [topId, topList] = ranked[0] ?? [];
  const topIncident = topId ? Object.values(w.incidents).find((i) => i.sharedFactor.corridorId === topId && i.status !== "resolved") : undefined;
  return {
    intent: "route_ranking",
    text: topId
      ? `**${topId} · ${corridors[topId].name}** has the most issues today (${plural(topList!.length, "shipment")}).${topIncident ? ` They share one cause, tracked as **${topIncident.id}**.` : ""}`
      : "No corridor has open issues today.",
    blocks: [
      { type: "bar_chart", title: "Shipments with issues by corridor", unit: "shipments", data: ranked.map(([id, list], i) => ({ label: `${id} · ${corridors[id].name}`, value: list.length, tone: i === 0 ? "crit" : "neutral" })) },
      ...(topList ? [{ type: "shipment_list" as const, title: `Top affected on ${topId}`, ids: topList.sort(compareByPriority).slice(0, 5).map((s) => s.id) }] : []),
      ...(topIncident ? [{ type: "actions" as const, actions: [{ kind: "focus_incident" as const, id: topIncident.id, label: "Focus map on corridor" }, { kind: "open_incident" as const, id: topIncident.id }] }] : []),
    ],
    sources: ["shipments", "corridors", "incidents"],
    followUps: ["Are there any active operational incidents?", "What happened today?"],
  };
}

function causeList(w: WorldState, types: CaseType[], label: string): AssistantResponse {
  const list = Object.values(w.shipments)
    .filter((s) => types.includes(s.caseType))
    .sort((a, b) => Number(a.closed) - Number(b.closed) || compareByPriority(a, b));
  const open = list.filter((s) => !s.closed);
  return {
    intent: "cause_list",
    text: `**${plural(list.length, `${label} case`)}** today — ${open.length} open, ${list.length - open.length} closed.`,
    blocks: [{ type: "shipment_list", title: label, ids: list.slice(0, 8).map((s) => s.id) }],
    sources: ["shipments", "analyze_disruption"],
    followUps: ["What did the Agent do for DL-20910?", "What happened today?"],
  };
}

function agentRecent(w: WorldState): AssistantResponse {
  const runs = Object.values(w.agentRuns)
    .filter((r) => r.status === "completed")
    .sort((a, b) => (b.finishedAt ?? 0) - (a.finishedAt ?? 0));
  const automated = w.ledger.filter((l) => l.decidedBy === "Agent (automated)").length;
  const escalated = w.ledger.filter((l) => l.decidedBy === "Agent → Supervisor").length;
  return {
    intent: "agent_recent",
    text: `Today the agent ran **${plural(runs.length, "investigation")}** on this desk. It executed **${automated}** low-impact, reversible actions automatically and sent **${escalated}** decisions to the shift supervisor.`,
    blocks: [{ type: "shipment_list", title: "Recently investigated", ids: [...new Set(runs.map((r) => r.shipmentId))].slice(0, 6) }],
    sources: ["agent run log", "outcome ledger"],
    followUps: ["What did the Agent do for DL-20910?", "Which shipments are waiting for supervisor approval?"],
  };
}

export const SUGGESTED_PROMPTS = [
  "What happened today?",
  "Which shipments need attention right now?",
  "Where is DL-20481?",
  "Are there any active operational incidents?",
  "Which shipments are waiting for supervisor approval?",
  "Show me high-risk shipments in Dammam.",
  "Why is DL-20334 delayed?",
  "What did the Agent do for DL-20910?",
  "Which route has the most issues today?",
  "Show recipient-unavailable cases.",
];

export const demoAssistantService: AssistantService = {
  async ask(query) {
    await sleep(650 + Math.min(900, query.length * 12));
    const w = getWorld();
    const now = demoNow();
    const q = query.toLowerCase();
    const idMatch = q.match(/dl[-\s]?(\d{5})/) ?? q.match(/\b(2\d{4})\b/);
    const id = idMatch ? `DL-${idMatch[1]}` : null;

    if (id) {
      const s = w.shipments[id];
      if (!s) {
        return { intent: "not_found", text: `I couldn't find **${id}** in today's operations data.`, blocks: [], sources: ["shipments"], followUps: ["Which shipments need attention right now?"] };
      }
      if (/agent|did .* do|investigat|action/.test(q)) return shipmentAgent(s, w);
      if (/why|delay|cause|reason|what happened|wrong|risk/.test(q)) return shipmentWhy(s, w, now);
      if (id === "DL-20481") updateWorld((d) => completeStep(d, "ask-where"));
      return shipmentWhere(s, w, now);
    }
    if (/what happened|today|summar|overview|shift|so far|disruptions/.test(q)) return dailySummary(w, now);
    if (/supervisor|approv|waiting|escalat|pending decision/.test(q)) return approvals(w, now);
    if (/route|corridor|road/.test(q)) return routeRanking(w, now);
    if (/incident/.test(q)) return incidentsAnswer(w, now);
    if (/recipient|unavailable|not available|\brna\b|missed window/.test(q)) return causeList(w, ["recipient_unavailable", "repeated_missed_window", "multiple_failed_attempts"], "Recipient unavailable");
    if (/address/.test(q)) return causeList(w, ["address_quality"], "Address quality");
    if (/stall|no scan|backlog|branch/.test(q)) return causeList(w, ["stalled_no_scan", "branch_backlog"], "Stalled / branch backlog");
    if (/conflict|mismatch|wrong code/.test(q)) return causeList(w, ["code_conflict", "route_blocked"], "Code conflict");
    if (/high.?risk|at risk|risky|likely to fail/.test(q)) {
      const cityKey = Object.keys(CITY_WORDS).find((c) => q.includes(c));
      return highRisk(w, cityKey ? CITY_WORDS[cityKey] : undefined);
    }
    if (/attention|priority|urgent|need|queue|focus/.test(q)) return attention(w);
    if (/agent/.test(q)) return agentRecent(w);

    return {
      intent: "fallback",
      text: "I can answer questions about shipment locations and status, why a shipment is disrupted, what the agent did, incidents, supervisor approvals and today's operations. Try one of these:",
      blocks: [],
      sources: [],
      followUps: SUGGESTED_PROMPTS.slice(0, 4),
    };
  },
};

export const locationOf = (s: Shipment) => getRoute(s.routeKey);
export const windowText = (s: Shipment) => fmtWindow(s.window);
