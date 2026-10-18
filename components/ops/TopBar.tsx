"use client";

import { RotateCcw, UserCog, Wifi, WifiOff } from "lucide-react";
import { cn } from "@/lib/cn";
import { LogoMark } from "@/components/layout/Logo";
import { resetDemo } from "@/lib/ops/agent";
import { setUi, useOps, useOpsUi } from "@/store/ops";
import { useLive } from "@/store/live";

export function TopBar() {
  const live = useLive((s) => s.status);
  const role = useOpsUi((s) => s.role);
  const busy = useOpsUi((s) => s.busy);
  const waiting = useOps((s) => s.cases.filter((c) => c.planId && s.plans[c.planId]?.status === "ready").length + Object.values(s.runs).filter((r) => r.decision.type === "escalate" && s.parcels[r.ui.shipmentId]?.state === "awaiting_manager").length);
  const connected = live === "connected";
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
      <div className="flex items-center gap-2.5">
        <LogoMark size={28} />
        <div className="text-sm font-semibold whitespace-nowrap text-ink">
          Dallal <span className="font-arabic text-ink-3">دلّال</span>
        </div>
        <span className="hidden text-xs whitespace-nowrap text-ink-4 lg:inline">Dammam · Al Khobar</span>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <span className={cn("hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium whitespace-nowrap ring-1 ring-inset sm:inline-flex", connected ? "bg-ok-50 text-ok-700 ring-ok-100" : "bg-crit-50 text-crit-700 ring-crit-100")} title={connected ? "Decisions come from the Dallal backend" : "Start the backend with npm run demo"}>
          {connected ? <Wifi className="size-3.5" aria-hidden /> : <WifiOff className="size-3.5" aria-hidden />}
          {connected ? "Live" : "Offline"}
        </span>
        <span className="hidden rounded-full bg-warn-50 px-2.5 py-1 text-xs font-medium whitespace-nowrap text-warn-700 ring-1 ring-warn-100 ring-inset sm:inline" title="Sample operation: WhatsApp is sandbox and actions execute in simulation">
          Sandbox
        </span>
        <div className="flex rounded-lg bg-muted p-0.5" role="group" aria-label="View as">
          {(["operator", "manager"] as const).map((r) => (
            <button key={r} type="button" onClick={() => setUi({ role: r })} aria-pressed={role === r} className={cn("flex h-8 items-center gap-1.5 rounded-md px-3 text-13 font-medium transition-colors", role === r ? "bg-surface text-ink shadow-card" : "text-ink-3 hover:text-ink")}>
              {r === "manager" ? <UserCog className="size-4" aria-hidden /> : null}
              {r === "operator" ? "Operations" : "Manager"}
              {r === "manager" && waiting > 0 ? <span className="flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-review-600 px-1 text-[11px] font-bold text-white tabular">{waiting}</span> : null}
            </button>
          ))}
        </div>
        <button type="button" disabled={!!busy} onClick={() => resetDemo()} className="flex size-8 items-center justify-center rounded-lg text-ink-3 hover:bg-hover hover:text-ink disabled:opacity-60" title="Reset the sample operation" aria-label="Reset the sample operation">
          <RotateCcw className="size-4" aria-hidden />
        </button>
      </div>
    </header>
  );
}
