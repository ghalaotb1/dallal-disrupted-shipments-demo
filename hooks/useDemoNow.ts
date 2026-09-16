"use client";

import { useEffect, useState } from "react";
import { clockNow, useWorld } from "@/store/world";

/** Re-renders on an interval with the current simulated operations time. */
export function useDemoNow(intervalMs = 1000) {
  const clock = useWorld((w) => w.clock);
  const [now, setNow] = useState(() => clockNow(clock));
  useEffect(() => {
    setNow(clockNow(clock));
    if (!clock.running) return;
    const id = setInterval(() => setNow(clockNow(clock)), intervalMs);
    return () => clearInterval(id);
  }, [clock, intervalMs]);
  return now;
}
