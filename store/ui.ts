"use client";

import { create } from "zustand";
import type { AssistantMessage } from "@/types/assistant";

export type StatusFilter = "all" | "at_risk" | "disrupted" | "review" | "incidents";

export type MapFocus =
  | { kind: "shipment"; id: string; nonce: number }
  | { kind: "incident"; id: string; nonce: number }
  | { kind: "network"; nonce: number };

export interface Toast {
  id: string;
  tone: "info" | "ok" | "warn" | "crit" | "review";
  title: string;
  body?: string;
  href?: string;
  actionLabel?: string;
}

export interface EscalationDraft {
  target: { type: "shipment" | "incident"; id: string };
  runId?: string;
}

interface UiState {
  sidebarCollapsed: boolean;
  statusFilter: StatusFilter;
  selectedShipmentId: string | null;
  selectedFacilityId: string | null;
  mapFocus: MapFocus | null;
  assistantOpen: boolean;
  commandOpen: boolean;
  notificationsOpen: boolean;
  escalation: EscalationDraft | null;
  emailPreviewId: string | null;
  groupResponseIncidentId: string | null;
  toasts: Toast[];
  assistantMessages: AssistantMessage[];
  assistantPending: boolean;
  set: (patch: Partial<Omit<UiState, "set">>) => void;
}

export const useUi = create<UiState>()((set) => ({
  sidebarCollapsed: false,
  statusFilter: "all",
  selectedShipmentId: null,
  selectedFacilityId: null,
  mapFocus: null,
  assistantOpen: false,
  commandOpen: false,
  notificationsOpen: false,
  escalation: null,
  emailPreviewId: null,
  groupResponseIncidentId: null,
  toasts: [],
  assistantMessages: [],
  assistantPending: false,
  set: (patch) => set(patch),
}));

let toastSeq = 0;
export function pushToast(t: Omit<Toast, "id">) {
  const id = `t${toastSeq++}`;
  useUi.setState((s) => ({ toasts: [...s.toasts.slice(-2), { ...t, id }] }));
  setTimeout(() => dismissToast(id), 7000);
}
export function dismissToast(id: string) {
  useUi.setState((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) }));
}

let focusNonce = 0;
export function focusMap(target: { kind: "shipment"; id: string } | { kind: "incident"; id: string } | { kind: "network" }) {
  useUi.setState({ mapFocus: { ...target, nonce: ++focusNonce } as MapFocus });
}
