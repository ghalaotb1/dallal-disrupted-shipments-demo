import { people } from "@/data/people";
import { agentService } from "@/services";
import { addEvent, addLedger, notify, setHealth } from "@/services/demo/mutations";
import { demoNow, getWorld, updateWorld } from "@/store/world";
import { pushToast } from "@/store/ui";

/**
 * DEMO ONLY — stands in for the shift supervisor answering an escalation from
 * their own device. In production this arrives as a decision event from the
 * supervisor's inbox or mobile approval flow.
 */
export async function simulateSupervisorApproval(escalationId: string) {
  const esc = getWorld().escalations.find((e) => e.id === escalationId);
  if (!esc || esc.status !== "awaiting") return;
  await new Promise((r) => setTimeout(r, 1200));
  const now = demoNow();
  const option = esc.options[0] ?? "Approved";

  updateWorld((d) => {
    const e = d.escalations.find((x) => x.id === escalationId);
    if (e) e.status = "approved";
    notify(d, {
      at: now,
      kind: "approval",
      tone: "ok",
      title: `${people.supervisor.name} approved · ${esc.target.id}`,
      body: option.replace(" (needs your approval)", ""),
      target: esc.target,
      actor: people.supervisor.name,
    });
    if (esc.target.type === "shipment") {
      addEvent(d, esc.target.id, { at: now, title: `Supervisor approved: ${option.replace(" (needs your approval)", "")}`, detail: "Decision received (simulated supervisor response)", source: "supervisor", tone: "ok" });
    }
    for (const l of d.ledger) if (l.shipmentId === esc.target.id && l.outcome === "escalated") Object.assign(l, { outcome: "pending" });
  });
  pushToast({ tone: "ok", title: `${people.supervisor.name} approved`, body: `${esc.target.id} · ${option.replace(" (needs your approval)", "")}`, href: esc.target.type === "shipment" ? `/shipments/${esc.target.id}` : `/incidents/${esc.target.id}` });

  if (esc.target.type !== "shipment") return;
  const w = getWorld();
  const s = w.shipments[esc.target.id];
  const run = Object.values(w.agentRuns)
    .filter((r) => r.shipmentId === s.id && r.mode === "investigation" && r.actions?.length)
    .sort((a, b) => b.startedAt - a.startedAt)[0];
  const action = run?.actions?.find((a) => a.approval === "supervisor") ?? run?.actions?.[0];
  if (action && !s.incident) {
    await agentService.execute(s.id, action.id, { approvedBy: people.supervisor.name });
    updateWorld((d) => {
      const e = d.escalations.find((x) => x.id === escalationId);
      if (e) e.status = "resolved";
    });
    return;
  }
  // No executable action (e.g. custody review) or handled by an incident: record the decision.
  updateWorld((d) => {
    const ship = d.shipments[s.id];
    setHealth(d, s.id, "recovering");
    ship.agent = { ...ship.agent, state: "acting", headline: "Supervisor decision in progress", updatedAt: now };
    ship.owner = { kind: "supervisor", name: people.supervisor.name };
    ship.headline = option.replace(" (needs your approval)", "");
    addLedger(d, { at: now, shipmentId: s.id, decision: option.replace(" (needs your approval)", ""), decidedBy: "Shift supervisor", basis: esc.reason, outcome: "pending" });
    const e = d.escalations.find((x) => x.id === escalationId);
    if (e) e.status = "resolved";
  });
}
