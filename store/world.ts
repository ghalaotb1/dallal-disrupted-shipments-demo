"use client";

import { create } from "zustand";
import { immer } from "zustand/middleware/immer";
import { SCENARIO_START, DEMO_TIME_SCALE } from "@/lib/time";
import type {
  AgentRun,
  AppNotification,
  DemoTime,
  Escalation,
  Incident,
  JourneyEvent,
  LedgerEntry,
  Shipment,
  ShipmentContext,
  SimulatedEmail,
} from "@/types/domain";

/**
 * Client-side state cache for the operations world.
 *
 * In this prototype the demo service adapters write here directly. With a real
 * backend the same store is hydrated from API responses and live event
 * subscriptions, and components keep reading it unchanged.
 */

export interface Clock {
  baseDemo: DemoTime;
  baseReal: number;
  running: boolean;
  scale: number;
}

export interface ScenarioState {
  autoplay: boolean;
  firedBeats: string[];
  completedSteps: string[];
  nextLaneSeq: number;
  nextDispatchAt: DemoTime;
  holdUntilReal: number;
  generation: number;
}

export interface WorldState {
  ready: boolean;
  clock: Clock;
  shipments: Record<string, Shipment>;
  journeys: Record<string, JourneyEvent[]>;
  contexts: Record<string, ShipmentContext>;
  incidents: Record<string, Incident>;
  agentRuns: Record<string, AgentRun>;
  notifications: AppNotification[];
  emails: Record<string, SimulatedEmail>;
  escalations: Escalation[];
  ledger: LedgerEntry[];
  scenario: ScenarioState;
}

const emptyWorld: WorldState = {
  ready: false,
  clock: { baseDemo: SCENARIO_START, baseReal: 0, running: false, scale: DEMO_TIME_SCALE },
  shipments: {},
  journeys: {},
  contexts: {},
  incidents: {},
  agentRuns: {},
  notifications: [],
  emails: {},
  escalations: [],
  ledger: [],
  scenario: { autoplay: true, firedBeats: [], completedSteps: [], nextLaneSeq: 21001, nextDispatchAt: SCENARIO_START, holdUntilReal: 0, generation: 0 },
};

export const useWorld = create<WorldState>()(immer(() => emptyWorld));

export const getWorld = () => useWorld.getState();
export const updateWorld = (recipe: (draft: WorldState) => void) => useWorld.setState(recipe);

export function clockNow(clock: Clock, realNow = Date.now()): DemoTime {
  return clock.running ? clock.baseDemo + (realNow - clock.baseReal) * clock.scale : clock.baseDemo;
}

export const demoNow = () => clockNow(getWorld().clock);

let idCounter = 0;
export const nextId = (prefix: string) => `${prefix}-${Date.now().toString(36).slice(-4)}${(idCounter++).toString(36)}`;
