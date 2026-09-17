import { people } from "@/data/people";
import { addEvent, addLedger, completeStep, notify, setHealth } from "@/services/demo/mutations";
import { demoNow, getWorld, nextId, updateWorld } from "@/store/world";
import { pushToast } from "@/store/ui";
import type { NotificationService } from "@/services/contracts";
import type { Escalation, SimulatedEmail } from "@/types/domain";

/**
 * In-app notifications + SIMULATED email. Nothing leaves the browser: emails are
 * rendered as previews. A production adapter would call the org's mail/alerting API.
 */
export const demoNotificationService: NotificationService = {
  async list() {
    return getWorld().notifications;
  },
  markRead(id) {
    updateWorld((d) => {
      const n = d.notifications.find((x) => x.id === id);
      if (n) n.read = true;
    });
  },
  markAllRead() {
    updateWorld((d) => d.notifications.forEach((n) => (n.read = true)));
  },
  async sendEscalation(input) {
    await new Promise((r) => setTimeout(r, 900));
    const now = demoNow();
    const escalationId = nextId("ESC");
    const withEmail = input.sendEmail !== false;
    const emailId = withEmail ? nextId("EM") : undefined;
    const isShipment = input.target.type === "shipment";
    const href = isShipment ? `/shipments/${input.target.id}` : `/incidents/${input.target.id}`;
    const subject = isShipment
      ? `Action required: Shipment ${input.target.id} requires supervisor review`
      : `Action required: Incident ${input.target.id} requires supervisor attention`;

    const email: SimulatedEmail = {
      id: emailId ?? "",
      at: now,
      from: "Dallal Alerts <alerts@dallal.example>",
      to: `${people.supervisor.name} <${people.supervisor.email}>`,
      cc: `${people.analyst.name} <${people.analyst.email}>`,
      subject,
      preheader: input.reason,
      greeting: `Hi ${people.supervisor.name.split(" ")[0]},`,
      summary: input.summary,
      reason: input.reason,
      checks: input.checks,
      evidence: input.evidence,
      question: input.question,
      recommendation: input.recommendation,
      operatorNote: input.note,
      link: { label: isShipment ? "Review case in Dallal" : "Open incident in Dallal", href },
    };
    const escalation: Escalation = {
      id: escalationId,
      at: now,
      target: input.target,
      to: { name: people.supervisor.name, role: people.supervisor.role },
      priority: input.priority,
      reason: input.reason,
      question: input.question,
      options: input.options,
      note: input.note,
      status: "awaiting",
      emailId,
    };

    updateWorld((d) => {
      if (emailId) d.emails[emailId] = email;
      d.escalations.unshift(escalation);
      notify(d, {
        at: now,
        kind: "escalation",
        tone: "review",
        title: isShipment ? `${input.target.id} escalated to shift supervisor` : `${input.target.id} sent to shift supervisor`,
        body: input.reason,
        target: input.target,
        actor: people.analyst.name,
        emailId,
      });
      if (isShipment) {
        const s = d.shipments[input.target.id];
        if (s) {
          setHealth(d, s.id, "review");
          s.agent = { ...s.agent, state: "awaiting_supervisor", headline: `Awaiting ${people.supervisor.name}`, updatedAt: now };
          s.owner = { kind: "supervisor", name: people.supervisor.name };
          addEvent(d, s.id, {
            at: now,
            title: `Escalated to ${people.supervisor.role.toLowerCase()} ${people.supervisor.name}`,
            detail: `${input.reason}${input.note ? ` · Note: “${input.note}”` : ""}`,
            source: "analyst",
            tone: "review",
          });
          addEvent(d, s.id, { at: now, title: withEmail ? "Supervisor notified in-app and by email (simulated)" : "Supervisor notified in-app", detail: subject, source: "system", tone: "neutral" });
          addLedger(d, { at: now, shipmentId: s.id, decision: "Escalate for supervisor approval", decidedBy: "Agent → Supervisor", basis: input.reason, outcome: "escalated" });
          if (s.id === "DL-20481") completeStep(d, "escalated");
        }
      } else {
        const inc = d.incidents[input.target.id];
        if (inc) {
          inc.supervisorNotifiedAt = now;
          inc.timeline.push({ id: nextId("IE"), at: now, title: `${people.supervisor.name} notified`, detail: "In-app and email (simulated)", tone: "review", actor: people.analyst.name });
        }
      }
    });
    pushToast({ tone: "review", title: "Escalation sent to shift supervisor", body: `${people.supervisor.name} · in-app${withEmail ? " + email (simulated)" : ""}`, href });
    return escalation;
  },
};
