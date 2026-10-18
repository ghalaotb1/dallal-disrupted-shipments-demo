"use client";

import { useEffect } from "react";
import { CheckCircle2, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/cn";
import { connectBackend } from "@/lib/ops/agent";
import { updateOps, useOps, useOpsUi } from "@/store/ops";
import { useLive } from "@/store/live";
import { CasePanel } from "@/components/ops/CasePanel";
import { KpiStrip } from "@/components/ops/KpiStrip";
import { LazyOpsMap } from "@/components/ops/LazyOpsMap";
import { MapLegend } from "@/components/ops/MapLegend";
import { RoutesPanel } from "@/components/ops/RoutesPanel";
import { TopBar } from "@/components/ops/TopBar";

export function OpsApp() {
  const toast = useOpsUi((s) => s.toast);
  const live = useLive((s) => s.status);
  const generation = useOps((s) => s.generation);

  useEffect(() => {
    updateOps((w) => {
      if (!w.clock.running) w.clock = { ...w.clock, baseReal: Date.now(), running: true };
    });
    void connectBackend();
    const t = setInterval(() => void connectBackend(), 15_000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="flex h-dvh min-h-[640px] flex-col bg-canvas">
      <TopBar />
      {live === "offline" ? (
        <div role="alert" className="flex items-center gap-2 border-b border-crit-100 bg-crit-50 px-4 py-1.5 text-xs text-crit-700">
          <TriangleAlert className="size-3.5" aria-hidden /> The Dallal backend is not reachable, so no investigation can run. Start everything with <code className="rounded bg-white px-1 font-mono">npm run demo</code>.
        </div>
      ) : null}
      <KpiStrip />
      <main className="grid min-h-0 flex-1 grid-cols-[330px_minmax(0,1fr)_420px] grid-rows-[minmax(0,1fr)]" key={generation}>
        <RoutesPanel />
        <div className="relative min-w-0">
          <LazyOpsMap />
          <MapLegend />
        </div>
        <CasePanel />
      </main>
      {toast ? (
        <div role="status" className={cn("fixed bottom-5 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 rounded-xl px-4 py-2.5 text-13 font-medium text-white shadow-pop", toast.tone === "warn" ? "bg-crit-600" : "bg-ink")}>
          {toast.tone === "ok" ? <CheckCircle2 className="size-4" aria-hidden /> : <TriangleAlert className="size-4" aria-hidden />}
          {toast.text}
        </div>
      ) : null}
    </div>
  );
}
