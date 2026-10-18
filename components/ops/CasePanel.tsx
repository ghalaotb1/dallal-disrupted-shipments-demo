"use client";

import Link from "next/link";
import { ArrowLeft, Loader2, Play, RotateCcw, Sparkles } from "lucide-react";
import { cn } from "@/lib/cn";
import { fmtTime } from "@/lib/time";
import { investigate, startScenario } from "@/lib/ops/agent";
import { parcelHealth } from "@/lib/ops/derive";
import { SCENARIOS } from "@/lib/ops/scenarios";
import { useOpsNow } from "@/hooks/useOpsNow";
import { setUi, useOps, useOpsUi } from "@/store/ops";
import { Button } from "@/components/common/Button";
import { HealthChip, SimTag } from "@/components/ops/Chips";
import { InvestigationStory, TechnicalDetails } from "@/components/ops/Story";
import { ManagerPanel } from "@/components/ops/ManagerPanel";
import type { Parcel } from "@/types/ops";

export function CasePanel() {
  const role = useOpsUi((s) => s.role);
  const active = useOps((s) => s.active);
  const selected = useOpsUi((s) => s.selectedParcelId);
  let body: React.ReactNode;
  if (role === "manager") body = <ManagerPanel />;
  else if (selected && (!active || selected !== active.parcelId)) body = <ParcelPanel id={selected} />;
  else if (active) body = <ScenarioCase />;
  else body = <IdlePanel />;
  return (
    <aside aria-label="Dallal" className="flex min-h-0 flex-col border-l border-line bg-surface">
      <div key={role} className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {body}
      </div>
    </aside>
  );
}

function IdlePanel() {
  const busy = useOpsUi((s) => s.busy);
  return (
    <div className="space-y-4">
      <div>
        <div className="flex items-center gap-2 text-xs font-semibold tracking-[0.06em] text-brand-700 uppercase">
          <Sparkles className="size-3.5" aria-hidden /> Dallal
        </div>
        <h2 className="mt-1 text-lg leading-6 font-semibold text-ink">Watching every driver and route</h2>
        <p className="mt-1 text-13 leading-5 text-ink-3">When a delivery fails or a road jams, Dallal investigates, asks the right person only when it is worth it, and recovers the parcels - or tells the manager.</p>
      </div>
      <div className="space-y-2.5">
        <p className="text-xs font-semibold tracking-[0.06em] text-ink-4 uppercase">Pick a situation</p>
        {SCENARIOS.map((s) => (
          <button key={s.id} type="button" disabled={!!busy} onClick={() => startScenario(s.id)} className="group w-full rounded-xl border border-line bg-surface p-3.5 text-left shadow-card transition-all hover:border-brand-300 hover:shadow-float disabled:opacity-60">
            <div className="flex items-center gap-2">
              <span className="flex size-6 items-center justify-center rounded-full bg-ink text-xs font-bold text-white">{s.id}</span>
              <b className="text-sm text-ink">{s.title}</b>
              <span className={cn("ml-auto rounded-full px-2 py-0.5 text-[11px] font-medium ring-1", s.tone === "ok" ? "bg-ok-50 text-ok-700 ring-ok-100" : s.tone === "info" ? "bg-brand-50 text-brand-700 ring-brand-100" : "bg-review-50 text-review-700 ring-review-100")}>{s.tag}</span>
            </div>
            <p className="mt-1.5 text-xs leading-5 text-ink-3">{s.shows}</p>
            <p className="mt-1.5 flex items-center gap-1 text-xs font-medium text-brand-700">
              <Play className="size-3" aria-hidden /> Show it on {s.short}
            </p>
          </button>
        ))}
      </div>
      <p className="text-[11px] leading-4 text-ink-4">Simulated operation on real Eastern Province roads. Drivers, parcels and recipients are fictional; WhatsApp is sandbox only and actions are executed in simulation.{" "}
        <Link href="/models" className="font-medium text-brand-700 hover:underline">
          See how the trained risk models were validated
        </Link>
        .
      </p>
    </div>
  );
}

function ScenarioCase() {
  const active = useOps((s) => s.active)!;
  const parcel = useOps((s) => s.parcels[active.parcelId]);
  const driver = useOps((s) => s.drivers[active.driverId]);
  const drivers = useOps((s) => s.drivers);
  const stops = useOps((s) => Object.values(s.parcels).filter((p) => p.driverId === active.driverId).length);
  const run = useOps((s) => (active.runId ? s.runs[active.runId] : undefined));
  const busy = useOpsUi((s) => s.busy);
  const now = useOpsNow(1000);
  const meta = SCENARIOS.find((s) => s.id === active.scenario)!;
  const health = parcelHealth(parcel, driver, now);
  const investigating = busy === "investigate";
  return (
    <div className="space-y-5">
      <header>
        <div className="flex items-center gap-2">
          <span className="flex size-6 items-center justify-center rounded-full bg-ink text-xs font-bold text-white">{meta.id}</span>
          <h2 className="text-base font-semibold text-ink">{meta.title}</h2>
          <button type="button" onClick={() => startScenario(active.scenario)} className="ml-auto flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-ink-3 hover:bg-hover hover:text-ink" title="Reset this scenario and play it again">
            <RotateCcw className="size-3.5" aria-hidden /> Replay
          </button>
        </div>
        <p className="mt-1 text-xs leading-5 text-ink-3">{meta.shows}</p>
      </header>

      <section className="relative pl-9">
        <span className="absolute top-0 left-0 flex size-6 items-center justify-center rounded-full bg-ink text-xs font-semibold text-white">1</span>
        <h3 className="text-xs font-semibold tracking-[0.06em] text-ink-3 uppercase">What happened</h3>
        <div className="mt-1.5 rounded-xl border border-warn-200 bg-warn-50 p-3.5">
          <div className="flex items-start gap-2">
            <p className="flex-1 text-13 leading-5 font-semibold text-ink">{active.problem.title}</p>
            <HealthChip health={health} />
          </div>
          <p className="mt-1 text-xs leading-5 text-ink-2">{active.problem.detail}</p>
          {active.scenario === "C" ? (
            <p className="mt-2 text-xs text-ink-2">
              Drivers affected: <b>{active.affectedDriverIds.map((d) => drivers[d]?.name).join(", ")}</b> · {active.exposedParcelIds.length} more parcels exposed
            </p>
          ) : (
            <p className="mt-2 text-xs text-ink-3">
              {driver?.name}&apos;s route · stop {parcel.seq} of {stops} · window until {fmtTime(parcel.window.end)}
            </p>
          )}
        </div>
        {!active.runId ? (
          <div className="mt-3">
            <Button size="lg" variant="primary" className="w-full" loading={investigating} onClick={() => investigate()}>
              {investigating ? "Dallal is investigating…" : "Investigate with Dallal"}
            </Button>
            <p className="mt-1.5 text-center text-[11px] text-ink-4">Runs the real backend agent on this case</p>
          </div>
        ) : null}
        {active.error ? (
          <p role="alert" className="mt-2 rounded-lg bg-crit-50 px-3 py-2 text-xs text-crit-700 ring-1 ring-crit-100">
            {active.error}
          </p>
        ) : null}
      </section>

      {run && active.runId ? (
        <>
          <InvestigationStory runId={active.runId} valueSar={parcel.valueSar} />
          <TechnicalDetails runId={active.runId} />
        </>
      ) : investigating ? (
        <p className="flex items-center gap-2 pl-9 text-xs text-ink-3">
          <Loader2 className="size-3.5 animate-spin" aria-hidden /> Contacting the Dallal agent…
        </p>
      ) : null}
    </div>
  );
}

function ParcelPanel({ id }: { id: string }) {
  const p = useOps((s) => s.parcels[id]) as Parcel | undefined;
  const driver = useOps((s) => (p ? s.drivers[p.driverId] : undefined));
  const journey = useOps((s) => s.journeys[id]) ?? [];
  const active = useOps((s) => s.active);
  const run = useOps((s) => Object.values(s.runs).filter((r) => r.ui.shipmentId === id).sort((a, b) => b.ui.startedAt - a.ui.startedAt)[0]);
  const busy = useOpsUi((s) => s.busy);
  const now = useOpsNow(1000);
  if (!p || !driver) return null;
  const h = parcelHealth(p, driver, now);
  return (
    <div className="space-y-4">
      <button type="button" onClick={() => setUi({ selectedParcelId: active?.parcelId ?? null })} className="flex items-center gap-1 text-xs font-medium text-ink-3 hover:text-ink">
        <ArrowLeft className="size-3.5" aria-hidden /> {active ? "Back to the case" : "Back"}
      </button>
      <div>
        <div className="flex items-center gap-2">
          <h2 className="font-mono text-base font-semibold text-ink">{p.id}</h2>
          <HealthChip health={h} />
          <SimTag className="ml-auto" />
        </div>
        <p className="mt-0.5 text-xs text-ink-3">
          {p.merchant} · {p.contents}
        </p>
      </div>
      <dl className="grid grid-cols-[96px_1fr] gap-x-3 gap-y-1.5 text-xs">
        <dt className="text-ink-4">Driver</dt><dd className="text-ink">{driver.name} · {driver.vehicle} · stop {p.seq}</dd>
        <dt className="text-ink-4">Deliver to</dt><dd className="text-ink">{p.recipient.name} · {p.address.line}, {p.address.district}</dd>
        <dt className="text-ink-4">Promise</dt><dd className="text-ink">{p.service} · until {fmtTime(p.window.end)}</dd>
        <dt className="text-ink-4">Value</dt><dd className="text-ink">SAR {p.valueSar.toLocaleString("en-US")}{p.payment.type === "COD" ? " · cash on delivery" : ""}</dd>
        {p.headline ? (<><dt className="text-ink-4">Status</dt><dd className="text-ink">{p.headline}</dd></>) : null}
        {p.recovery ? (<><dt className="text-ink-4">Recovery</dt><dd className="text-brand-700">{p.recovery.label}</dd></>) : null}
      </dl>
      <div>
        <p className="mb-1.5 text-xs font-semibold tracking-[0.06em] text-ink-4 uppercase">Journey</p>
        <ol className="space-y-1.5 border-l border-line pl-3">
          {journey.slice(-5).map((e) => (
            <li key={e.id} className="relative text-xs">
              <span className="absolute top-1.5 -left-[15px] size-1.5 rounded-full bg-ink-4" aria-hidden />
              <span className="font-mono text-ink-4">{fmtTime(e.at)}</span> <span className="text-ink">{e.title}</span>
              {e.detail ? <span className="block text-ink-3">{e.detail}</span> : null}
            </li>
          ))}
        </ol>
      </div>
      {run ? (
        <>
          <InvestigationStory runId={run.ui.id} valueSar={p.valueSar} />
          <TechnicalDetails runId={run.ui.id} />
        </>
      ) : (
        <Button variant="secondary" loading={busy === "investigate"} onClick={() => investigate(p.id)}>
          <Sparkles /> Ask Dallal to check this parcel
        </Button>
      )}
    </div>
  );
}
