"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, MapPinned, Siren } from "lucide-react";
import { corridors, places } from "@/data/network";
import { cn } from "@/lib/cn";
import { fmtKm, fmtSar } from "@/lib/format";
import { fmtDuration, fmtTime, fmtWindow } from "@/lib/time";
import { estimateEta, progressOf, remainingM } from "@/services/logic/movement";
import { focusMap, useUi } from "@/store/ui";
import { AgentBadge, PriorityBadge, RiskMeter, SimTag, StatusBadge } from "@/components/common/Badges";
import { HEALTH } from "@/components/common/status";
import { LazyNetworkMap } from "@/components/map/LazyMap";
import { RouteProgress } from "@/components/shipments/RouteProgress";
import type { Shipment } from "@/types/domain";

export function ShipmentHeader({ s, now }: { s: Shipment; now: number }) {
  const router = useRouter();
  const eta = estimateEta(s, now);
  const late = !!eta && eta > s.slaDeadline;
  const slaLeft = s.slaDeadline - now;
  const pay = s.payment.type === "COD" ? `COD ${fmtSar(s.payment.amountSar)}` : "Prepaid";
  const showOnMap = () => {
    useUi.setState({ selectedShipmentId: s.id, selectedFacilityId: null, statusFilter: "all" });
    router.push("/");
    setTimeout(() => focusMap({ kind: "shipment", id: s.id }), 350);
  };

  return (
    <section className="grid overflow-hidden rounded-xl border border-line bg-surface shadow-card lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
      <div className="min-w-0 p-5">
        <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-xs text-ink-3">
          <Link href="/shipments" className="hover:text-ink hover:underline">
            Shipments
          </Link>
          <ChevronRight className="size-3.5 text-ink-5" aria-hidden />
          <span className="text-ink-2">Shipment Intelligence</span>
        </nav>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          <h1 className="font-mono text-[24px] leading-8 font-semibold tracking-[-0.02em] text-ink">{s.id}</h1>
          <StatusBadge health={s.health} />
          <PriorityBadge priority={s.priority} />
          {s.incident ? (
            <Link href={`/incidents/${s.incident.id}`} className="inline-flex h-[22px] items-center gap-1 rounded-full bg-crit-600 px-2 text-xs font-semibold text-white hover:bg-crit-700">
              <Siren className="size-3.5" aria-hidden /> {s.incident.id} · {s.incident.role}
            </Link>
          ) : null}
          <SimTag />
        </div>
        {s.headline ? <p className={cn("mt-1.5 text-15 leading-6 font-medium", HEALTH[s.health].text)}>{s.headline}</p> : null}
        <p className="mt-1 text-13 text-ink-3">
          {s.merchant} · {s.service} · {pay} · {s.contents}
        </p>

        <div className="mt-4 rounded-lg bg-subtle p-3">
          <div className="flex items-center justify-between gap-3 text-xs">
            <span className="text-ink-3">
              From <span className="font-medium text-ink-2">{places[s.originId].name}</span>
            </span>
            <span className="truncate text-right text-ink-3">
              To <span className="font-medium text-ink-2">{s.destination.label}</span>
            </span>
          </div>
          <RouteProgress s={s} now={now} className="mt-2" />
          <div className="mt-1.5 flex items-center justify-between text-2xs text-ink-4">
            <span>
              {corridors[s.corridorId].code} · {corridors[s.corridorId].name}
            </span>
            <span className="tabular">{s.closed ? "Completed" : s.movement.mode === "facility" ? "Not departed" : `${Math.round(progressOf(s, now) * 100)}% · ${fmtKm(remainingM(s, now))} to go`}</span>
          </div>
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
          <Fact label="ETA">
            <span className={cn("font-semibold tabular", late ? "text-crit-600" : "text-ink")}>{s.closed ? "—" : eta ? fmtTime(eta) : "—"}</span>
            {late && !s.closed ? <span className="ml-1 text-2xs font-medium text-crit-600">late</span> : null}
          </Fact>
          <Fact label="Promised window">
            <span className="text-ink tabular">{fmtWindow(s.window)}</span>
          </Fact>
          <Fact label="SLA">
            <span className="text-ink tabular">{fmtTime(s.slaDeadline)}</span>
            <span className={cn("ml-1 text-2xs", slaLeft < 0 ? "text-crit-600" : slaLeft < 90 * 60_000 ? "text-warn-700" : "text-ink-4")}>{s.closed ? "" : slaLeft < 0 ? "passed" : `in ${fmtDuration(slaLeft)}`}</span>
          </Fact>
          <Fact label="Risk">
            <RiskMeter risk={s.risk} />
          </Fact>
          <Fact label="Agent">
            <AgentBadge state={s.agent.state} />
          </Fact>
          <Fact label="Owner">
            <span className="text-ink-2">{s.owner.name}</span>
          </Fact>
        </dl>
      </div>

      <div className="relative min-h-[300px] border-t border-line-soft lg:border-t-0 lg:border-l">
        <LazyNetworkMap variant="shipment" shipmentIds={[s.id]} className="absolute inset-0" legend={false} />
        {!s.closed ? (
          <button onClick={showOnMap} className="absolute bottom-7 left-3 z-10 inline-flex items-center gap-1.5 rounded-lg border border-line bg-surface/95 px-2.5 py-1.5 text-xs font-medium text-ink-2 shadow-card hover:bg-surface hover:text-ink">
            <MapPinned className="size-3.5" /> Show on live network map
          </button>
        ) : null}
      </div>
    </section>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-2xs font-medium text-ink-4">{label}</dt>
      <dd className="mt-0.5 flex items-center text-13">{children}</dd>
    </div>
  );
}
