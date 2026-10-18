"use client";

import Link from "next/link";
import { Beaker, RotateCcw, ShieldCheck, UserCog, Wifi, WifiOff } from "lucide-react";
import { cn } from "@/lib/cn";
import { LogoMark } from "@/components/layout/Logo";
import { resetDemo, startScenario } from "@/lib/ops/agent";
import { SCENARIOS } from "@/lib/ops/scenarios";
import { setUi, useOps, useOpsUi } from "@/store/ops";
import { useLive } from "@/store/live";

export function TopBar() {
  const live = useLive((s) => s.status);
  const meta = useLive((s) => s.meta);
  const active = useOps((s) => s.active?.scenario ?? null);
  const role = useOpsUi((s) => s.role);
  const busy = useOpsUi((s) => s.busy);
  const waiting = useOps((s) => Object.values(s.plans).filter((p) => p.status === "ready").length + Object.values(s.runs).filter((r) => r.decision.type === "escalate" && s.parcels[r.ui.shipmentId]?.state === "awaiting_manager").length);
  const connected = live === "connected";
  const sandbox = meta?.whatsapp?.mode === "sandbox" || meta?.whatsapp_mode === "sandbox";
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface px-3">
      <div className="flex items-center gap-2.5">
        <LogoMark size={28} />
        <div className="leading-tight">
          <div className="text-sm font-semibold whitespace-nowrap text-ink">Dallal <span className="font-arabic text-ink-3">دلّال</span></div>
          <div className="hidden text-[11px] whitespace-nowrap text-ink-4 min-[1500px]:block">Last-mile control · Dammam – Khobar</div>
        </div>
      </div>

      <nav aria-label="Demo scenarios" className="mx-auto flex items-center gap-1.5">
        <span className="mr-1 hidden text-xs font-medium text-ink-4 min-[1500px]:inline">Scenarios</span>
        {SCENARIOS.map((s) => (
          <button
            key={s.id}
            type="button"
            disabled={!!busy}
            onClick={() => startScenario(s.id)}
            aria-pressed={active === s.id}
            className={cn("flex h-9 items-center gap-2 rounded-lg px-3 text-13 font-medium whitespace-nowrap transition-colors disabled:opacity-60", active === s.id ? "bg-ink text-white shadow-card" : "text-ink-2 ring-1 ring-line-strong ring-inset hover:bg-hover")}
          >
            <span className={cn("flex size-5 items-center justify-center rounded-full text-[11px] font-bold", active === s.id ? "bg-white/20" : "bg-muted")}>{s.id}</span>
            {s.title}
          </button>
        ))}
        <button type="button" disabled={!!busy} onClick={() => resetDemo()} className="ml-1 flex h-9 items-center gap-1.5 rounded-lg px-2.5 text-13 font-medium text-ink-3 hover:bg-hover hover:text-ink disabled:opacity-60" title="Back to a calm network (also clears the backend's demo history)">
          <RotateCcw className="size-4" aria-hidden /> Reset
        </button>
      </nav>

      <div className="flex items-center gap-2">
        <span className={cn("hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium whitespace-nowrap ring-1 ring-inset lg:inline-flex", connected ? "bg-ok-50 text-ok-700 ring-ok-100" : "bg-crit-50 text-crit-700 ring-crit-100")} title={connected ? "Decisions come from the real Dallal backend" : "Start the backend with npm run demo"}>
          {connected ? <Wifi className="size-3.5" aria-hidden /> : <WifiOff className="size-3.5" aria-hidden />}
          {connected ? "Live backend" : "Backend offline"}
        </span>
        <span className="hidden items-center gap-1.5 rounded-full bg-warn-50 px-2.5 py-1 text-xs font-medium whitespace-nowrap text-warn-700 ring-1 ring-warn-100 ring-inset xl:inline-flex" title="No message can reach a real phone">
          <ShieldCheck className="size-3.5" aria-hidden /> {sandbox || !connected ? "WhatsApp sandbox" : "WhatsApp"}
        </span>
        <span className="hidden items-center gap-1.5 rounded-full bg-muted px-2.5 py-1 text-xs font-medium whitespace-nowrap text-ink-3 ring-1 ring-line ring-inset xl:inline-flex" title="Fictional drivers and parcels on real roads; actions execute in simulation">
          <Beaker className="size-3.5" aria-hidden /> Simulated
        </span>
        <div className="ml-1 flex rounded-lg bg-muted p-0.5" role="group" aria-label="View as">
          {(["operator", "manager"] as const).map((r) => (
            <button key={r} type="button" onClick={() => setUi({ role: r })} aria-pressed={role === r} className={cn("relative flex h-8 items-center gap-1.5 rounded-md px-3 text-13 font-medium transition-colors", role === r ? "bg-surface text-ink shadow-card" : "text-ink-3 hover:text-ink")}>
              {r === "manager" ? <UserCog className="size-4" aria-hidden /> : null}
              {r === "operator" ? "Operations" : "Manager"}
              {r === "manager" && waiting > 0 ? <span className="flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-review-600 px-1 text-[11px] font-bold text-white tabular">{waiting}</span> : null}
            </button>
          ))}
        </div>
        <Link href="/models" className="hidden text-xs font-medium whitespace-nowrap text-ink-4 hover:text-ink min-[1700px]:inline">Model evidence</Link>
      </div>
    </header>
  );
}
