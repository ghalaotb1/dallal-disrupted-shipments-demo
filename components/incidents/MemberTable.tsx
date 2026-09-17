"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Users } from "lucide-react";
import { cn } from "@/lib/cn";
import { fmtTime } from "@/lib/time";
import { estimateEta } from "@/services/logic/movement";
import { AgentBadge, StatusBadge } from "@/components/common/Badges";
import type { Incident, Shipment } from "@/types/domain";

export function MemberTable({ incident: inc, shipments, now, onHover }: { incident: Incident; shipments: Record<string, Shipment>; now: number; onHover?: (id: string | null) => void }) {
  const [tab, setTab] = useState<"affected" | "exposed">("affected");
  const ids = tab === "affected" ? inc.affected : inc.exposed;
  const rows = ids.map((id) => shipments[id]).filter(Boolean);
  return (
    <section className="rounded-xl border border-line bg-surface shadow-card" aria-labelledby="members-title">
      <header className="flex flex-wrap items-center justify-between gap-3 px-5 pt-4 pb-3">
        <div>
          <div className="flex items-center gap-2 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">
            <Users className="size-3.5" aria-hidden /> Shipments in this incident
          </div>
          <h2 id="members-title" className="mt-1 text-15 font-semibold text-ink">
            {tab === "affected" ? "Already failing" : "Not failed yet — on the same path"}
          </h2>
        </div>
        <div role="tablist" aria-label="Incident members" className="flex rounded-lg bg-muted p-0.5">
          {(["affected", "exposed"] as const).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className={cn("rounded-md px-3 py-1 text-xs font-semibold capitalize transition-colors", tab === t ? "bg-surface text-ink shadow-card" : "text-ink-3 hover:text-ink-2")}
            >
              {t} <span className="ml-0.5 text-ink-4 tabular">{t === "affected" ? inc.affected.length : inc.exposed.length}</span>
            </button>
          ))}
        </div>
      </header>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left">
          <thead>
            <tr className="border-y border-line-soft bg-subtle text-2xs font-semibold tracking-[0.04em] text-ink-4 uppercase">
              <th className="px-5 py-2 font-semibold">Shipment</th>
              <th className="px-2 py-2 font-semibold">Status</th>
              <th className="px-2 py-2 font-semibold">Symptom</th>
              <th className="px-2 py-2 font-semibold">ETA</th>
              <th className="px-2 py-2 font-semibold">Agent</th>
              <th className="px-5 py-2" aria-label="Open" />
            </tr>
          </thead>
          <tbody className="divide-y divide-line-soft">
            {rows.map((s) => {
              const eta = estimateEta(s, now);
              return (
                <tr key={s.id} className="group hover:bg-hover" onMouseEnter={() => onHover?.(s.id)} onMouseLeave={() => onHover?.(null)}>
                  <td className="px-5 py-2.5">
                    <Link href={`/shipments/${s.id}`} className="font-mono text-13 font-semibold text-ink hover:underline">
                      {s.id}
                    </Link>
                    <div className="text-2xs text-ink-4">{s.destination.district}</div>
                  </td>
                  <td className="px-2 py-2.5">
                    <StatusBadge health={s.health} size="xs" />
                  </td>
                  <td className="max-w-[260px] px-2 py-2.5">
                    <div className="truncate text-xs text-ink-2">{s.headline ?? "—"}</div>
                    {s.exception ? <div className="text-2xs text-ink-4">Recorded: {s.exception.code} · {s.exception.label}</div> : null}
                  </td>
                  <td className={cn("px-2 py-2.5 text-xs tabular", eta && eta > s.slaDeadline ? "font-semibold text-crit-600" : "text-ink-2")}>{s.closed ? "Delivered" : eta ? fmtTime(eta) : "—"}</td>
                  <td className="px-2 py-2.5">
                    <AgentBadge state={s.agent.state} />
                  </td>
                  <td className="px-5 py-2.5 text-right">
                    <Link href={`/shipments/${s.id}`} className="inline-flex items-center text-ink-4 group-hover:text-brand-600" aria-label={`Open ${s.id}`}>
                      <ArrowRight className="size-4" />
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length ? <p className="px-5 py-6 text-center text-xs text-ink-3">No {tab} shipments.</p> : null}
      </div>
    </section>
  );
}
