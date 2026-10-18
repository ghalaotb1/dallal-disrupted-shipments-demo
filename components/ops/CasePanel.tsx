"use client";

import { ArrowLeft, ChevronRight, Loader2, MessageSquare, Sparkles, Briefcase } from "lucide-react";
import { cn } from "@/lib/cn";
import { fmtTime } from "@/lib/time";
import { closeCase, investigateParcel, openCase } from "@/lib/ops/agent";
import { parcelHealth } from "@/lib/ops/derive";
import { caseStatus, type CaseStatus } from "@/lib/ops/narrative";
import { SCENARIOS } from "@/lib/ops/scenarios";
import { useOpsNow } from "@/hooks/useOpsNow";
import { setUi, useOps, useOpsUi } from "@/store/ops";
import { Button } from "@/components/common/Button";
import { Assistant } from "@/components/ops/Assistant";
import { HealthChip, SimTag } from "@/components/ops/Chips";
import { ManagerPanel } from "@/components/ops/ManagerPanel";
import { InvestigationStory, TechnicalDetails } from "@/components/ops/Story";
import type { Parcel, ScenarioCase } from "@/types/ops";

const STATUS_STYLE: Record<CaseStatus["tone"], string> = {
  new: "bg-brand-50 text-brand-700 ring-brand-100",
  work: "bg-brand-50 text-brand-700 ring-brand-100",
  wait: "bg-warn-50 text-warn-700 ring-warn-100",
  ok: "bg-ok-50 text-ok-700 ring-ok-100",
  manager: "bg-review-50 text-review-700 ring-review-100",
};

function StatusPill({ s }: { s: CaseStatus }) {
  return (
    <span className={cn("inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap ring-1 ring-inset", STATUS_STYLE[s.tone])}>
      {s.tone === "work" ? <Loader2 className="size-3 animate-spin" aria-hidden /> : null}
      {s.label}
    </span>
  );
}

export function CasePanel() {
  const role = useOpsUi((s) => s.role);
  const tab = useOpsUi((s) => s.tab);
  const open = useOpsUi((s) => s.openCaseId);
  const selected = useOpsUi((s) => s.selectedParcelId);
  let body: React.ReactNode;
  if (role === "manager") body = <ManagerPanel />;
  else if (tab === "assistant") body = <Assistant />;
  else if (open) body = <CaseDetail id={open} />;
  else if (selected) body = <ParcelPanel id={selected} />;
  else body = <CaseList />;
  return (
    <aside aria-label="Dallal" className="flex min-h-0 flex-col border-l border-line bg-surface">
      {role === "operator" ? (
        <div className="flex shrink-0 gap-1 border-b border-line px-3 pt-2" role="tablist">
          {([["cases", "Cases", Briefcase], ["assistant", "Assistant", MessageSquare]] as const).map(([k, label, Icon]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setUi({ tab: k })} className={cn("flex items-center gap-1.5 border-b-2 px-3 py-2 text-13 font-medium transition-colors", tab === k ? "border-brand-600 text-ink" : "border-transparent text-ink-3 hover:text-ink")}>
              <Icon className="size-4" aria-hidden /> {label}
            </button>
          ))}
        </div>
      ) : null}
      <div key={`${role}:${tab}`} className="scrollbar-thin min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {body}
      </div>
    </aside>
  );
}

function CaseList() {
  const cases = useOps((s) => s.cases);
  const w = useOps((s) => s);
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-ink">Open cases</h2>
        <span className="text-xs text-ink-3">{cases.length} today</span>
      </div>
      <ul className="space-y-2">
        {cases.map((c) => {
          const meta = SCENARIOS.find((m) => m.id === c.scenario)!;
          return (
            <li key={c.scenario}>
              <button type="button" onClick={() => openCase(c.scenario)} className="group flex w-full items-center gap-3 rounded-xl border border-line bg-surface p-3.5 text-left shadow-card transition-all hover:border-brand-300 hover:shadow-float">
                <span className={cn("size-2.5 shrink-0 rounded-full", meta.tone === "ok" ? "bg-warn-500" : meta.tone === "info" ? "bg-crit-500" : "bg-crit-500")} aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="block text-13 font-semibold text-ink">{c.label}</span>
                  <span className="block truncate text-xs text-ink-3">{c.problem.detail}</span>
                </span>
                <StatusPill s={caseStatus(w, c)} />
                <ChevronRight className="size-4 shrink-0 text-ink-4 transition-colors group-hover:text-brand-600" aria-hidden />
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function CaseDetail({ id }: { id: ScenarioCase["scenario"] }) {
  const c = useOps((s) => s.cases.find((x) => x.scenario === id))!;
  const w = useOps((s) => s);
  const parcel = useOps((s) => s.parcels[c.parcelId]);
  const driver = useOps((s) => s.drivers[c.driverId]);
  const drivers = useOps((s) => s.drivers);
  const run = useOps((s) => (c.runId ? s.runs[c.runId] : undefined));
  const now = useOpsNow(1000);
  const health = parcelHealth(parcel, driver, now);
  return (
    <div className="space-y-5">
      <button type="button" onClick={closeCase} className="flex items-center gap-1 text-xs font-medium text-ink-3 hover:text-ink">
        <ArrowLeft className="size-3.5" aria-hidden /> Cases
      </button>
      <header className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="text-base leading-6 font-semibold text-ink">{c.problem.title}</h2>
          <p className="text-xs text-ink-3">{c.problem.detail}</p>
        </div>
        <StatusPill s={caseStatus(w, c)} />
      </header>

      <section className="relative pl-9">
        <span className="absolute top-0 left-0 flex size-6 items-center justify-center rounded-full bg-ink text-xs font-semibold text-white">1</span>
        <h3 className="text-xs font-semibold tracking-[0.06em] text-ink-3 uppercase">What happened</h3>
        <div className="mt-1.5 rounded-xl border border-warn-200 bg-warn-50 p-3">
          <div className="flex items-start gap-2">
            <p className="flex-1 text-13 leading-5 font-medium text-ink">
              {c.scenario === "C" ? `${c.affectedDriverIds.map((d) => drivers[d]?.name).join(", ")} stuck behind a blockage` : parcel.headline ?? "Delivery failed"}
            </p>
            <HealthChip health={health} />
          </div>
          <p className="mt-1 text-xs text-ink-3">
            {c.scenario === "C" ? `${c.exposedParcelIds.length} more parcels heading into the same stretch` : `${parcel.id} · stop ${parcel.seq} · ${parcel.address.district} · window until ${fmtTime(parcel.window.end)}`}
          </p>
        </div>
        {c.error ? (
          <p role="alert" className="mt-2 rounded-lg bg-crit-50 px-3 py-2 text-xs text-crit-700 ring-1 ring-crit-100">
            {c.error}
          </p>
        ) : null}
      </section>

      {run && c.runId ? (
        <>
          <InvestigationStory runId={c.runId} valueSar={parcel.valueSar} />
          <TechnicalDetails runId={c.runId} />
        </>
      ) : c.running ? (
        <p className="flex items-center gap-2 pl-9 text-xs text-ink-3">
          <Loader2 className="size-3.5 animate-spin" aria-hidden /> Dallal is investigating…
        </p>
      ) : c.error ? (
        <Button size="sm" variant="secondary" onClick={() => openCase(c.scenario)}>
          Retry
        </Button>
      ) : null}
    </div>
  );
}

function ParcelPanel({ id }: { id: string }) {
  const p = useOps((s) => s.parcels[id]) as Parcel | undefined;
  const driver = useOps((s) => (p ? s.drivers[p.driverId] : undefined));
  const journey = useOps((s) => s.journeys[id]) ?? [];
  const cases = useOps((s) => s.cases);
  const run = useOps((s) => Object.values(s.runs).filter((r) => r.ui.shipmentId === id).sort((a, b) => b.ui.startedAt - a.ui.startedAt)[0]);
  const busy = useOpsUi((s) => s.busy);
  const now = useOpsNow(1000);
  if (!p || !driver) return null;
  const h = parcelHealth(p, driver, now);
  const inCase = cases.find((c) => c.parcelId === id || c.exposedParcelIds.includes(id) || (c.scenario === "C" && p.incident && c.affectedDriverIds.includes(p.driverId)));
  return (
    <div className="space-y-4">
      <button type="button" onClick={() => setUi({ selectedParcelId: null })} className="flex items-center gap-1 text-xs font-medium text-ink-3 hover:text-ink">
        <ArrowLeft className="size-3.5" aria-hidden /> Cases
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
      <dl className="grid grid-cols-[84px_1fr] gap-x-3 gap-y-1.5 text-xs">
        <dt className="text-ink-4">Driver</dt><dd className="text-ink">{driver.name} · {driver.vehicle} · stop {p.seq}</dd>
        <dt className="text-ink-4">Deliver to</dt><dd className="text-ink">{p.recipient.name} · {p.address.district}</dd>
        <dt className="text-ink-4">Promise</dt><dd className="text-ink">{p.service} · until {fmtTime(p.window.end)}</dd>
        <dt className="text-ink-4">Value</dt><dd className="text-ink">SAR {p.valueSar.toLocaleString("en-US")}{p.payment.type === "COD" ? " · COD" : ""}</dd>
        {p.headline ? (<><dt className="text-ink-4">Status</dt><dd className="text-ink">{p.headline}</dd></>) : null}
        {p.recovery ? (<><dt className="text-ink-4">Recovery</dt><dd className="text-brand-700">{p.recovery.label}</dd></>) : null}
      </dl>
      {inCase ? (
        <Button variant="soft" onClick={() => openCase(inCase.scenario)}>
          Open case: {inCase.label}
        </Button>
      ) : null}
      <div>
        <p className="mb-1.5 text-xs font-semibold tracking-[0.06em] text-ink-4 uppercase">Journey</p>
        <ol className="space-y-1.5 border-l border-line pl-3">
          {journey.slice(-5).map((e) => (
            <li key={e.id} className="relative text-xs">
              <span className="absolute top-1.5 -left-[15px] size-1.5 rounded-full bg-ink-4" aria-hidden />
              <span className="font-mono text-ink-4">{fmtTime(e.at)}</span> <span className="text-ink">{e.title}</span>
            </li>
          ))}
        </ol>
      </div>
      {run ? (
        <>
          <InvestigationStory runId={run.ui.id} valueSar={p.valueSar} />
          <TechnicalDetails runId={run.ui.id} />
        </>
      ) : !inCase ? (
        <Button variant="secondary" loading={busy === "investigate"} onClick={() => investigateParcel(p.id)}>
          <Sparkles /> Check with Dallal
        </Button>
      ) : null}
    </div>
  );
}
