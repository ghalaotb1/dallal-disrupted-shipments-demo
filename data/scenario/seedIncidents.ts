import { places } from "@/data/network";
import { people } from "@/data/people";
import { at } from "@/lib/time";
import type { Incident } from "@/types/domain";

/**
 * 30-minute failure counts per corridor over the shift so far (simulated history).
 * The incident detector computes mean / std from these at runtime.
 */
export const corridorBaselines: Record<string, number[]> = {
  "DK-04": [0, 1, 0, 0, 1, 0, 0, 2, 0, 1, 0, 0, 1],
  "DM-02": [1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, 0, 0],
  "DM-05": [0, 0, 1, 1, 0, 0, 2, 0, 0, 1, 0, 0, 1],
  "KH-01": [1, 1, 0, 0, 2, 0, 1, 0, 0, 1, 0, 1, 0],
};
export const baselineLabels = ["09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00", "12:30", "13:00", "13:30", "14:00", "14:30", "15:00"];

const supervisor = { name: people.supervisor.name, role: people.supervisor.role };

export const seedIncidents: Incident[] = [
  {
    id: "INC-2416",
    kind: "branch",
    title: "Dammam Central sorting backlog",
    subtitle: "Parcels stalled after sorter line 2 stoppage",
    severity: "medium",
    status: "mitigating",
    detectedAt: at("13:40"),
    sharedFactor: {
      label: "Dammam Central Branch",
      detail: "Sorter line 2 stopped 09:30–13:10 (maintenance) · 412 parcels waiting",
      coord: places["br-dmm-central"].coord,
      radiusM: 420,
      placeId: "br-dmm-central",
    },
    signals: [
      { label: "Parcels without scan > 4 h", value: "3", detail: "Baseline 0.3 per 60 min" },
      { label: "Backlog at facility", value: "412", detail: "Parcels awaiting sort" },
      { label: "Equipment", value: "Line 2", detail: "Stopped 09:30–13:10" },
    ],
    detector: {
      method: "Rolling baseline z-score · stalled parcels per facility",
      window: "60 min",
      baselineMean: 0.3,
      baselineStd: 0.5,
      observed: 3,
      z: 5.4,
      threshold: 3,
      series: [
        { label: "08:00", count: 0 },
        { label: "09:00", count: 1 },
        { label: "10:00", count: 0 },
        { label: "11:00", count: 0 },
        { label: "12:00", count: 1 },
        { label: "13:00", count: 3, current: true },
      ],
    },
    affected: ["DL-20698", "DL-20703", "DL-20711"],
    exposed: ["DL-20722", "DL-20735"],
    owner: supervisor,
    response: {
      state: "applied",
      summary: "Extra sorting team assigned; Express parcels pulled forward",
      approvalRequired: true,
      approvedBy: people.supervisor.name,
      appliedAt: at("14:15"),
      steps: [
        { id: "s1", title: "Assign extra sorting team", detail: "4 staff from Khobar Branch until 18:00", shipments: [], tool: "escalate_case" },
        { id: "s2", title: "Pull Express parcels forward", detail: "Sort and dispatch in 16:30 wave", shipments: ["DL-20703"], tool: "reschedule_delivery" },
        { id: "s3", title: "Notify affected recipients", detail: "Revised delivery estimate", shipments: ["DL-20698", "DL-20711"], tool: "contact_recipient" },
      ],
    },
    supervisorNotifiedAt: at("13:41"),
    timeline: [
      { id: "i6-1", at: at("13:40"), title: "Incident detected", detail: "3 stalled parcels vs baseline 0.3 (z = 5.4)", tone: "warn", actor: "Incident detector" },
      { id: "i6-2", at: at("13:41"), title: "Shift supervisor notified", tone: "review", actor: "Dallal Agent" },
      { id: "i6-3", at: at("14:15"), title: "Extra sorting team assigned", detail: "Approved by Faisal Al-Dosari", tone: "ok", actor: people.supervisor.name },
      { id: "i6-4", at: at("14:50"), title: "Backlog down to 268 parcels", tone: "info", actor: "Branch operations" },
    ],
    simulatedCause: "Planned maintenance overran on sorter line 2 (simulated)",
  },
  {
    id: "INC-2415",
    kind: "pickup_point",
    title: "Al Aqrabiyah lockers offline",
    subtitle: "Failed deposits at one locker bank",
    severity: "medium",
    status: "resolved",
    detectedAt: at("11:20"),
    resolvedAt: at("13:10"),
    sharedFactor: {
      label: "Al Aqrabiyah Parcel Lockers",
      detail: "Locker bank reporting offline since 10:58",
      coord: places["lk-aqrabiyah"].coord,
      radiusM: 260,
      placeId: "lk-aqrabiyah",
    },
    signals: [
      { label: "Failed deposits", value: "3", detail: "Same locker bank within 20 min" },
      { label: "Locker heartbeat", value: "Offline", detail: "Since 10:58" },
    ],
    detector: {
      method: "Rolling baseline z-score · failed deposits per pickup point",
      window: "60 min",
      baselineMean: 0.2,
      baselineStd: 0.45,
      observed: 3,
      z: 6.2,
      threshold: 3,
      series: [
        { label: "07:00", count: 0 },
        { label: "08:00", count: 0 },
        { label: "09:00", count: 1 },
        { label: "10:00", count: 0 },
        { label: "11:00", count: 3, current: true },
      ],
    },
    affected: ["DL-20844", "DL-20851", "DL-20857"],
    exposed: [],
    owner: supervisor,
    response: {
      state: "applied",
      summary: "Redirected 3 parcels to Ar Rawabi Pickup Point; recipients offered home delivery",
      approvalRequired: true,
      approvedBy: people.supervisor.name,
      appliedAt: at("11:35"),
      steps: [
        { id: "s1", title: "Redirect to Ar Rawabi Pickup Point", detail: "Nearest online pickup point", shipments: ["DL-20844", "DL-20851", "DL-20857"], tool: "redirect_to_pickup" },
        { id: "s2", title: "Offer home delivery", detail: "Recipient choice via WhatsApp", shipments: ["DL-20857"], tool: "contact_recipient" },
      ],
    },
    supervisorNotifiedAt: at("11:21"),
    timeline: [
      { id: "i5-1", at: at("11:20"), title: "Incident detected", detail: "3 failed deposits vs baseline 0.2 (z = 6.2)", tone: "warn", actor: "Incident detector" },
      { id: "i5-2", at: at("11:35"), title: "Group redirect approved", tone: "review", actor: people.supervisor.name },
      { id: "i5-3", at: at("12:20"), title: "Parcels deposited at Ar Rawabi Pickup Point", tone: "ok", actor: "Khobar Branch" },
      { id: "i5-4", at: at("13:10"), title: "Locker bank back online · incident resolved", tone: "ok", actor: people.supervisor.name },
    ],
    simulatedCause: "Power fault at locker bank (simulated)",
  },
];
