"use client";

import { useEffect, useState } from "react";
import { clockNow, getOps } from "@/store/ops";
import type { DemoTime } from "@/types/domain";

/** The simulated operations clock, re-read every `ms` real milliseconds. Before mount it equals the clock base, so server and client agree. */
export function useOpsNow(ms = 500): DemoTime {
  const [now, setNow] = useState<DemoTime>(() => clockNow(getOps().clock));
  useEffect(() => {
    const read = () => setNow(clockNow(getOps().clock));
    read();
    const t = setInterval(read, ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}
