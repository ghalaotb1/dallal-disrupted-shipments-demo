"use client";

import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import { buildWorld } from "@/data/ops/world";
import { stageAll } from "@/lib/ops/scenarios";
import { SCENARIO_START } from "@/lib/time";
import type { DemoTime } from "@/types/domain";
import type { AssistantMessage, OpsWorld } from "@/types/ops";

/** Demo clock speed: one real second advances the operations clock by this many seconds (vans cross a stop in ~half a minute of screen time). */
export const OPS_TIME_SCALE = 4;

export function freshWorld(generation = 0): OpsWorld {
  const world: OpsWorld = {
    generation,
    clock: { baseDemo: SCENARIO_START, baseReal: 0, scale: OPS_TIME_SCALE, running: false },
    ...buildWorld(SCENARIO_START),
    runs: {},
    plans: {},
    planBefore: {},
    events: [],
    cases: [],
    blockage: null,
  };
  stageAll(world, SCENARIO_START); // the operation starts with its three open situations already on the board
  return world;
}

export interface UiState {
  /** Which persona is looking: the desk operator or the manager (approvals). */
  role: "operator" | "manager";
  /** Right panel tab and the open case. */
  tab: "cases" | "assistant";
  openCaseId: "A" | "B" | "C" | null;
  /** KPI card filter on the routes list. */
  kpiFilter: "all" | "at_risk" | "disrupted" | "review" | "cases" | "resolved";
  assistant: AssistantMessage[];
  selectedDriverId: string | null;
  selectedParcelId: string | null;
  expandedDriverIds: string[];
  detailsOpen: boolean;
  /** How many story items of each run have been revealed so far (the real trace is shown at a readable pace). */
  revealed: Record<string, number>;
  /** Set while a request is in flight so the UI never shows a stale idle state. */
  busy: string | null;
  toast: { id: number; tone: "ok" | "warn" | "info"; text: string } | null;
}

export const useOps = create<OpsWorld>()(immer(() => freshWorld()));
export const useOpsUi = create<UiState>(() => ({ role: "operator", tab: "cases", openCaseId: null, kpiFilter: "all", assistant: [], selectedDriverId: null, selectedParcelId: null, expandedDriverIds: [], detailsOpen: false, revealed: {}, busy: null, toast: null }));

export const getOps = () => useOps.getState();
export const updateOps = (recipe: (draft: OpsWorld) => void) => useOps.setState(recipe);
export const setUi = (p: Partial<UiState>) => useOpsUi.setState(p);
export const getUi = () => useOpsUi.getState();

export function clockNow(c: OpsWorld["clock"], realNow = Date.now()): DemoTime {
  return c.running ? c.baseDemo + (realNow - c.baseReal) * c.scale : c.baseDemo;
}
export const opsNow = () => clockNow(getOps().clock);

let toastId = 0;
export function toast(tone: "ok" | "warn" | "info", text: string) {
  const id = ++toastId;
  setUi({ toast: { id, tone, text } });
  setTimeout(() => {
    if (getUi().toast?.id === id) setUi({ toast: null });
  }, 4500);
}
