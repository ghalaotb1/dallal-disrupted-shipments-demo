import { people } from "@/data/people";
import { at } from "@/lib/time";
import type { AppNotification, Escalation, LedgerEntry, SimulatedEmail } from "@/types/domain";

export const seedEmails: SimulatedEmail[] = [
  {
    id: "EM-1042",
    at: at("14:42"),
    from: "Dallal Alerts <alerts@dallal.example>",
    to: `${people.supervisor.name} <${people.supervisor.email}>`,
    cc: `${people.analyst.name} <${people.analyst.email}>`,
    subject: "Action required: Shipment DL-20598 requires supervisor review",
    preheader: "Custody scans conflict and no known cause fits the evidence.",
    greeting: `Hi ${people.supervisor.name.split(" ")[0]},`,
    summary: [
      { label: "Shipment", value: "DL-20598 · Ward Beauty · Standard" },
      { label: "Destination", value: "Ad Dawhah Al Janubiyah, Dhahran" },
      { label: "Priority", value: "P1 · SLA passed at 15:00" },
      { label: "Status", value: "Human review" },
    ],
    reason: "Dallal Agent could not attribute a cause with confidence and will not act on an unexplained custody pattern.",
    checks: ["Shipment record", "Journey scans", "Disruption evidence", "Route context", "Incident context"],
    evidence: [
      "Delivered scan by van DMM-221 at 13:05 (photo proof, no OTP)",
      "Recipient reported parcel not received at 13:48",
      "Out-for-delivery scan by a different van (DMM-236) at 14:20",
    ],
    question: "Was the parcel handed to the wrong recipient, or was the delivered scan made in error?",
    recommendation: "Hold the parcel on DMM-236, contact courier C-221, and confirm custody before any re-attempt.",
    link: { label: "Review case in Dallal", href: "/shipments/DL-20598" },
  },
];

export const seedEscalations: Escalation[] = [
  {
    id: "ESC-311",
    at: at("14:42"),
    target: { type: "shipment", id: "DL-20598" },
    to: { name: people.supervisor.name, role: people.supervisor.role },
    priority: "P1",
    reason: "Unknown pattern · conflicting custody scans",
    question: "Was the parcel handed to the wrong recipient, or was the delivered scan made in error?",
    options: ["Hold parcel and verify custody with courier C-221", "Open a lost-parcel claim", "Re-attempt delivery with OTP"],
    status: "awaiting",
    emailId: "EM-1042",
  },
];

export const seedNotifications: AppNotification[] = [
  { id: "N-101", at: at("11:20"), kind: "incident", tone: "warn", title: "Pickup point incident detected", body: "Al Aqrabiyah lockers offline · 3 failed deposits grouped as INC-2415", read: true, target: { type: "incident", id: "INC-2415" }, actor: "Incident detector" },
  { id: "N-102", at: at("11:35"), kind: "approval", tone: "ok", title: "Supervisor approved group redirect", body: "INC-2415 · 3 parcels to Ar Rawabi Pickup Point", read: true, target: { type: "incident", id: "INC-2415" }, actor: people.supervisor.name },
  { id: "N-103", at: at("13:02"), kind: "outcome", tone: "ok", title: "Failure prevented · DL-20289", body: "Delivered after the recipient confirmed the address pin", read: true, target: { type: "shipment", id: "DL-20289" }, actor: "Dallal Agent" },
  { id: "N-104", at: at("13:10"), kind: "outcome", tone: "ok", title: "Incident resolved · INC-2415", body: "Locker bank back online · 3 of 3 parcels recovered", read: true, target: { type: "incident", id: "INC-2415" }, actor: people.supervisor.name },
  { id: "N-105", at: at("13:37"), kind: "agent", tone: "ok", title: "Agent rescheduled DL-20910", body: "Recipient chose 18:00–20:00 · automated, reversible action", read: true, target: { type: "shipment", id: "DL-20910" }, actor: "Dallal Agent" },
  { id: "N-106", at: at("13:40"), kind: "incident", tone: "warn", title: "Branch incident detected", body: "Dammam Central sorting backlog · 3 stalled, 2 exposed (INC-2416)", read: true, target: { type: "incident", id: "INC-2416" }, actor: "Incident detector" },
  { id: "N-107", at: at("14:15"), kind: "approval", tone: "info", title: "Extra sorting team assigned", body: "INC-2416 · approved by Faisal Al-Dosari", read: true, target: { type: "incident", id: "INC-2416" }, actor: people.supervisor.name },
  { id: "N-108", at: at("14:42"), kind: "escalation", tone: "review", title: "Agent escalated DL-20598 to shift supervisor", body: "Conflicting custody scans · no known cause fits", read: false, target: { type: "shipment", id: "DL-20598" }, actor: "Dallal Agent", emailId: "EM-1042" },
  { id: "N-109", at: at("14:55"), kind: "agent", tone: "info", title: "Recommendation ready · DL-20776", body: "Move parcel forward in stop sequence to meet same-day promise", read: false, target: { type: "shipment", id: "DL-20776" }, actor: "Dallal Agent" },
];

export const seedLedger: LedgerEntry[] = [
  { id: "L-01", at: at("10:12"), shipmentId: "DL-20166", decision: "Offer new delivery window", decidedBy: "Agent (automated)", basis: "Recipient unavailable · evidence agrees with RNA", outcome: "recovered", outcomeAt: at("12:40") },
  { id: "L-02", at: at("10:20"), shipmentId: "DL-20140", decision: "Verify address by phone", decidedBy: "Analyst", basis: "Address incomplete", outcome: "recovered", outcomeAt: at("12:05") },
  { id: "L-03", at: at("11:10"), shipmentId: "DL-20231", decision: "Redirect to Al Faisaliyah Pickup Point", decidedBy: "Analyst", basis: "Recipient unavailable", outcome: "recovered", outcomeAt: at("13:30") },
  { id: "L-04", at: at("11:30"), shipmentId: "DL-20247", decision: "Request location pin before dispatch", decidedBy: "Agent (automated)", basis: "Predicted address risk", outcome: "prevented", outcomeAt: at("12:50") },
  { id: "L-05", at: at("11:35"), incidentId: "INC-2415", decision: "Group redirect · 3 parcels", decidedBy: "Shift supervisor", basis: "Pickup point incident", outcome: "recovered", outcomeAt: at("13:10") },
  { id: "L-06", at: at("11:53"), shipmentId: "DL-20289", decision: "Request location pin via WhatsApp", decidedBy: "Agent (automated)", basis: "Predicted address risk", outcome: "prevented", outcomeAt: at("13:02") },
  { id: "L-07", at: at("12:10"), shipmentId: "DL-20258", decision: "Prioritise in branch sort queue", decidedBy: "Analyst", basis: "Stalled · no scan > 4 h", outcome: "recovered", outcomeAt: at("14:15") },
  { id: "L-08", at: at("12:22"), shipmentId: "DL-20270", decision: "Offer new delivery window", decidedBy: "Agent (automated)", basis: "Recipient unavailable", outcome: "pending" },
  { id: "L-09", at: at("13:37"), shipmentId: "DL-20910", decision: "Reschedule to 18:00–20:00", decidedBy: "Agent (automated)", basis: "Recipient unavailable · evidence agrees with RNA", outcome: "pending" },
  { id: "L-10", at: at("14:15"), incidentId: "INC-2416", decision: "Assign extra sorting team", decidedBy: "Shift supervisor", basis: "Branch backlog incident", outcome: "pending" },
  { id: "L-11", at: at("14:42"), shipmentId: "DL-20598", decision: "Escalate · custody review", decidedBy: "Agent → Supervisor", basis: "Unknown pattern · conflicting scans", outcome: "escalated" },
];
