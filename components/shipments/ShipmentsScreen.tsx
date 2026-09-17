"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, BookCheck, Search, Siren, X } from "lucide-react";
import { corridors, places } from "@/data/network";
import { cn } from "@/lib/cn";
import { fmtRelative, fmtTime, fmtWindow } from "@/lib/time";
import { useDemoNow } from "@/hooks/useDemoNow";
import { useAllShipments } from "@/hooks/useWorldData";
import { compareByPriority } from "@/services/logic/priority";
import { estimateEta } from "@/services/logic/movement";
import { useWorld } from "@/store/world";
import { AgentBadge, PriorityBadge, RiskMeter, SimTag, StatusBadge } from "@/components/common/Badges";
import { EmptyState } from "@/components/common/Card";
import type { LedgerEntry, Shipment } from "@/types/domain";

type Tab = "active" | "attention" | "supervisor" | "closed" | "ledger";
const TABS: { key: Tab; label: string }[] = [
  { key: "active", label: "All active" },
  { key: "attention", label: "Needs attention" },
  { key: "supervisor", label: "Awaiting supervisor" },
  { key: "closed", label: "Closed today" },
  { key: "ledger", label: "Outcome ledger" },
];

export function ShipmentsScreen() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = (TABS.find((t) => t.key === params.get("tab"))?.key ?? "active") as Tab;
  const all = useAllShipments();
  const ledger = useWorld((w) => w.ledger);
  const now = useDemoNow(5000);
  const [q, setQ] = useState("");
  const [corridor, setCorridor] = useState("all");

  const groups = useMemo(() => {
    const active = all.filter((s) => !s.closed);
    return {
      active: active.sort(compareByPriority),
      attention: active.filter((s) => s.health === "disrupted" || s.health === "at_risk" || s.health === "review").sort(compareByPriority),
      supervisor: active.filter((s) => s.agent.state === "awaiting_supervisor").sort(compareByPriority),
      closed: all.filter((s) => s.closed && !s.generated).sort((a, b) => (b.outcome?.at ?? b.lastEventAt) - (a.outcome?.at ?? a.lastEventAt)),
    };
  }, [all]);

  const setTab = (t: Tab) => router.replace(t === "active" ? "/shipments" : `/shipments?tab=${t}`, { scroll: false });
  const counts: Record<Tab, number> = { active: groups.active.length, attention: groups.attention.length, supervisor: groups.supervisor.length, closed: groups.closed.length, ledger: ledger.length };

  const rows = tab === "ledger" ? [] : groups[tab].filter((s) => (corridor === "all" || s.corridorId === corridor) && (!q || `${s.id} ${s.destination.label} ${s.merchant} ${s.headline ?? ""}`.toLowerCase().includes(q.toLowerCase())));

  return (
    <div className="mx-auto w-full max-w-[1480px] space-y-3 p-3 lg:p-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] leading-8 font-semibold tracking-[-0.02em] text-ink">Shipments</h1>
          <p className="text-13 text-ink-3">Every shipment on the Dammam–Khobar desk today — health, prototype risk score, agent state and outcome.</p>
        </div>
        <SimTag label="simulated scenario" />
      </header>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label="Shipment views" className="flex flex-wrap gap-1 rounded-xl bg-muted p-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
              className={cn("inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-13 font-medium transition-colors", tab === t.key ? "bg-surface text-ink shadow-card" : "text-ink-3 hover:text-ink")}
            >
              {t.key === "ledger" ? <BookCheck className="size-3.5" aria-hidden /> : null}
              {t.label}
              <span className={cn("rounded px-1 text-2xs tabular", tab === t.key ? "bg-muted text-ink-2" : "text-ink-4")}>{counts[t.key]}</span>
            </button>
          ))}
        </div>
        {tab !== "ledger" ? (
          <div className="flex items-center gap-2">
            <label className="flex h-9 w-64 items-center gap-2 rounded-lg border border-line bg-surface px-2.5 focus-within:border-brand-300 focus-within:ring-2 focus-within:ring-brand-100">
              <Search className="size-4 text-ink-4" aria-hidden />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search ID, district, merchant" className="flex-1 bg-transparent text-13 outline-none placeholder:text-ink-4" aria-label="Search shipments" />
              {q ? (
                <button onClick={() => setQ("")} aria-label="Clear search">
                  <X className="size-3.5 text-ink-4" />
                </button>
              ) : null}
            </label>
            <select value={corridor} onChange={(e) => setCorridor(e.target.value)} className="h-9 rounded-lg border border-line bg-surface px-2.5 text-13 text-ink-2 outline-none focus:border-brand-300" aria-label="Filter by corridor">
              <option value="all">All corridors</option>
              {Object.values(corridors).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.code} · {c.name}
                </option>
              ))}
            </select>
          </div>
        ) : null}
      </div>

      {tab === "ledger" ? <Ledger entries={ledger} now={now} /> : <ShipmentTable rows={rows} now={now} closed={tab === "closed"} />}
    </div>
  );
}

function ShipmentTable({ rows, now, closed }: { rows: Shipment[]; now: number; closed: boolean }) {
  const router = useRouter();
  if (!rows.length) return <EmptyState className="rounded-xl border border-line bg-surface" icon={<Search />} title="No shipments match" body="Try another view, corridor or search term." />;
  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-card">
      <table className="w-full min-w-[1060px] text-left">
        <thead>
          <tr className="border-b border-line bg-subtle text-2xs font-semibold tracking-[0.04em] text-ink-4 uppercase">
            <th className="px-4 py-2.5">Shipment</th>
            <th className="px-2 py-2.5">Status</th>
            <th className="px-2 py-2.5">Risk</th>
            <th className="px-2 py-2.5">Route</th>
            <th className="px-2 py-2.5">{closed ? "Outcome" : "Situation"}</th>
            <th className="px-2 py-2.5">{closed ? "Closed" : "ETA · window"}</th>
            <th className="px-2 py-2.5">Agent</th>
            <th className="px-4 py-2.5" aria-label="Open" />
          </tr>
        </thead>
        <tbody className="divide-y divide-line-soft">
          {rows.map((s) => {
            const eta = estimateEta(s, now);
            return (
              <tr key={s.id} onClick={() => router.push(`/shipments/${s.id}`)} className="group cursor-pointer hover:bg-hover">
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <Link href={`/shipments/${s.id}`} onClick={(e) => e.stopPropagation()} className="font-mono text-13 font-semibold text-ink hover:underline">
                      {s.id}
                    </Link>
                    {!closed ? <PriorityBadge priority={s.priority} /> : null}
                  </div>
                  <div className="text-2xs text-ink-4">
                    {s.merchant} · {s.service}
                  </div>
                </td>
                <td className="px-2 py-2.5">
                  <StatusBadge health={s.health} size="xs" />
                  {s.incident ? (
                    <div className="mt-1 flex items-center gap-1 text-2xs text-crit-700">
                      <Siren className="size-3" aria-hidden /> {s.incident.id}
                    </div>
                  ) : null}
                </td>
                <td className="px-2 py-2.5">
                  <RiskMeter risk={s.risk} />
                </td>
                <td className="px-2 py-2.5">
                  <div className="text-xs text-ink-2">
                    {places[s.originId].short} → {s.destination.label}
                  </div>
                  <div className="text-2xs text-ink-4">
                    {corridors[s.corridorId].code} · {corridors[s.corridorId].name}
                  </div>
                </td>
                <td className="max-w-[260px] px-2 py-2.5">
                  <div className="truncate text-xs text-ink-2">{closed ? (s.outcome?.label ?? "Delivered") : (s.headline ?? "Progressing normally")}</div>
                  {s.exception && !closed ? <div className="truncate text-2xs text-ink-4">Recorded {s.exception.code} · {s.exception.label}</div> : null}
                </td>
                <td className="px-2 py-2.5 text-xs tabular">
                  {closed ? (
                    <span className="text-ink-2">{s.outcome ? fmtTime(s.outcome.at) : fmtTime(s.lastEventAt)}</span>
                  ) : (
                    <>
                      <div className={cn(eta && eta > s.slaDeadline ? "font-semibold text-crit-600" : "text-ink-2")}>{s.movement.mode === "facility" ? "At facility" : eta ? fmtTime(eta) : "—"}</div>
                      <div className="text-2xs text-ink-4">{fmtWindow(s.window)}</div>
                    </>
                  )}
                </td>
                <td className="px-2 py-2.5">
                  <AgentBadge state={s.agent.state} />
                </td>
                <td className="px-4 py-2.5 text-right">
                  <ArrowRight className="inline size-4 text-ink-4 group-hover:text-brand-600" aria-hidden />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const OUTCOME_CHIP: Record<LedgerEntry["outcome"], string> = {
  pending: "bg-muted text-ink-2 ring-line",
  prevented: "bg-ok-50 text-ok-700 ring-ok-100",
  recovered: "bg-ok-50 text-ok-700 ring-ok-100",
  resolved: "bg-ok-50 text-ok-700 ring-ok-100",
  escalated: "bg-review-50 text-review-700 ring-review-100",
};

function Ledger({ entries, now }: { entries: LedgerEntry[]; now: number }) {
  const sorted = useMemo(() => [...entries].sort((a, b) => b.at - a.at), [entries]);
  const automated = entries.filter((e) => e.decidedBy === "Agent (automated)").length;
  const human = entries.filter((e) => e.decidedBy !== "Agent (automated)").length;
  const known = entries.filter((e) => e.outcome !== "pending" && e.outcome !== "escalated").length;
  return (
    <div className="space-y-3">
      <div className="grid gap-3 rounded-xl border border-line bg-surface p-4 shadow-card md:grid-cols-[1.4fr_repeat(3,1fr)]">
        <div>
          <div className="flex items-center gap-2 text-13 font-semibold text-ink">
            <BookCheck className="size-4 text-brand-600" /> Every decision is logged with its eventual outcome
          </div>
          <p className="mt-1 text-xs text-ink-3">This ledger is how rankings can learn from real results in production. Nothing is learned in this prototype — outcomes are recorded, not used to retrain.</p>
        </div>
        {[
          { label: "Automated by agent", value: automated },
          { label: "Decided by people", value: human },
          { label: "Outcomes known", value: `${known} / ${entries.length}` },
        ].map((k) => (
          <div key={k.label} className="rounded-lg bg-subtle px-3 py-2">
            <div className="text-2xs text-ink-4">{k.label}</div>
            <div className="text-[20px] leading-7 font-semibold text-ink">{k.value}</div>
          </div>
        ))}
      </div>
      <div className="overflow-x-auto rounded-xl border border-line bg-surface shadow-card">
        <table className="w-full min-w-[960px] text-left">
          <thead>
            <tr className="border-b border-line bg-subtle text-2xs font-semibold tracking-[0.04em] text-ink-4 uppercase">
              <th className="px-4 py-2.5">Time</th>
              <th className="px-2 py-2.5">Decision</th>
              <th className="px-2 py-2.5">Case</th>
              <th className="px-2 py-2.5">Decided by</th>
              <th className="px-2 py-2.5">Basis</th>
              <th className="px-4 py-2.5">Outcome</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line-soft">
            {sorted.map((e) => (
              <tr key={e.id} className="hover:bg-hover">
                <td className="px-4 py-2.5 text-xs text-ink-2 tabular">
                  {fmtTime(e.at)}
                  <div className="text-2xs text-ink-4">{fmtRelative(e.at, now)}</div>
                </td>
                <td className="px-2 py-2.5 text-13 font-medium text-ink">{e.decision}</td>
                <td className="px-2 py-2.5">
                  {e.shipmentId ? (
                    <Link href={`/shipments/${e.shipmentId}`} className="font-mono text-xs font-semibold text-brand-700 hover:underline">
                      {e.shipmentId}
                    </Link>
                  ) : e.incidentId ? (
                    <Link href={`/incidents/${e.incidentId}`} className="font-mono text-xs font-semibold text-brand-700 hover:underline">
                      {e.incidentId}
                    </Link>
                  ) : null}
                </td>
                <td className="px-2 py-2.5 text-xs text-ink-2">{e.decidedBy}</td>
                <td className="max-w-[260px] px-2 py-2.5 text-xs text-ink-3">{e.basis}</td>
                <td className="px-4 py-2.5">
                  <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-2xs font-semibold capitalize ring-1 ring-inset", OUTCOME_CHIP[e.outcome])}>{e.outcome}</span>
                  {e.outcomeAt ? <span className="ml-1.5 text-2xs text-ink-4 tabular">{fmtTime(e.outcomeAt)}</span> : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
