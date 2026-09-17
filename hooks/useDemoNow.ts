"use client";

import { useSyncExternalStore } from "react";
import { clockNow, getWorld, SCENARIO_START_TIME, useWorld } from "@/store/world";

/**
 * Shared operations-clock ticker. One interval drives every consumer; each
 * consumer only re-renders when its own bucket (1 s, 5 s, 15 s…) advances.
 */
const listeners = new Set<() => void>();
const buckets = new Map<number, number>();
let ticks = 0;
let timer: ReturnType<typeof setInterval> | null = null;

function refresh(all: boolean) {
  const now = clockNow(getWorld().clock);
  for (const interval of buckets.keys()) {
    if (all || (ticks * 1000) % interval === 0) buckets.set(interval, now);
  }
  listeners.forEach((l) => l());
}

let unsubClock: (() => void) | null = null;

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (!timer) {
    timer = setInterval(() => {
      ticks += 1;
      refresh(false);
    }, 1000);
    unsubClock = useWorld.subscribe((s, prev) => {
      if (s.clock !== prev.clock) refresh(true);
    });
  }
  return () => {
    listeners.delete(listener);
    if (!listeners.size) {
      if (timer) clearInterval(timer);
      unsubClock?.();
      timer = null;
      unsubClock = null;
    }
  };
}

export function useDemoNow(intervalMs = 1000) {
  const bucket = Math.max(1000, Math.round(intervalMs / 1000) * 1000);
  return useSyncExternalStore(
    subscribe,
    () => {
      if (!buckets.has(bucket)) buckets.set(bucket, clockNow(getWorld().clock));
      return buckets.get(bucket)!;
    },
    () => SCENARIO_START_TIME,
  );
}
