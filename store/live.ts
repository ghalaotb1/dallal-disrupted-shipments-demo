"use client";

import { create } from "zustand";
import type { LiveEvent, LiveMeta, LivePlan } from "@/types/live";

/** Connection and audit-feed state for the live backend. Business state lives in the shared world store, so every screen agrees. */
interface LiveState {
  status: "unknown" | "connected" | "offline";
  meta?: LiveMeta;
  lastEventId: number;
  events: LiveEvent[];
  lastError?: string;
  /** Coordinated recovery plans by incident id (one consistent copy for every screen). */
  plans: Record<string, LivePlan>;
}

export const useLive = create<LiveState>(() => ({ status: "unknown", lastEventId: 0, events: [], plans: {} }));
export const getLive = () => useLive.getState();
export const setLive = (p: Partial<LiveState>) => useLive.setState(p);
export const setPlan = (incidentId: string, plan: LivePlan) => useLive.setState((s) => ({ plans: { ...s.plans, [incidentId]: plan } }));
