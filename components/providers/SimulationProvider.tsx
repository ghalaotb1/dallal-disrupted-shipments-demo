"use client";

import { useEffect, type ReactNode } from "react";
import { startSimulation } from "@/simulation/engine";
import { useWorld } from "@/store/world";
import { LogoMark } from "@/components/layout/Logo";

export function SimulationProvider({ children }: { children: ReactNode }) {
  const ready = useWorld((w) => w.ready);
  useEffect(() => {
    startSimulation();
  }, []);
  if (!ready) {
    return (
      <div className="flex h-dvh items-center justify-center bg-canvas">
        <div className="flex flex-col items-center gap-3 text-ink-3">
          <LogoMark size={40} className="animate-pulse" />
          <span className="text-13">Loading operations…</span>
        </div>
      </div>
    );
  }
  return <>{children}</>;
}
