"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { ChevronRight, Clock3, MapPinned, Siren, SkipForward, UserRoundCheck } from "lucide-react";
import { people } from "@/data/people";
import { cn } from "@/lib/cn";
import { fmtRelative, fmtTime } from "@/lib/time";
import { useDemoNow } from "@/hooks/useDemoNow";
import { incidentService } from "@/services";
import { advanceTo } from "@/simulation/engine";
import { useUi } from "@/store/ui";
import { useWorld } from "@/store/world";
import { Avatar, EmptyState } from "@/components/common/Card";
import { SeverityBadge, SimTag } from "@/components/common/Badges";
import { Button } from "@/components/common/Button";
import { LazyNetworkMap } from "@/components/map/LazyMap";
import { ConsolidationHero } from "@/components/incidents/ConsolidationHero";
import { IncidentSignals } from "@/components/incidents/IncidentSignals";
import { IncidentTimeline } from "@/components/incidents/IncidentTimeline";
import { MemberTable } from "@/components/incidents/MemberTable";
import { ResponsePlan } from "@/components/incidents/ResponsePlan";

const STATUS_CHIP = {
  active: "bg-crit-600 text-white",
  mitigating: "bg-warn-100 text-warn-700",
  resolved: "bg-ok-100 text-ok-700",
};

export function IncidentIntelligence({ id }: { id: string }) {
  const inc = useWorld((w) => w.incidents[id]);
  const shipments = useWorld((w) => w.shipments);
  const set = useUi((s) => s.set);
  const now = useDemoNow(5000);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [resolving, setResolving] = useState(false);

  const notify = useCallback(() => set({ escalation: { target: { type: "incident", id } } }), [set, id]);
  const apply = useCallback(() => set({ groupResponseIncidentId: id }), [set, id]);
  const resolve = useCallback(async () => {
    setResolving(true);
    await incidentService.resolve(id);
    setResolving(false);
  }, [id]);

  if (!inc) {
    return (
      <div className="p-6">
        <EmptyState
          icon={<Siren />}
          title={`${id} hasn't been detected in this session yet`}
          body="Incidents appear when the detector sees failures cluster above a corridor's baseline. In the demo, the King Fahd Rd failures arrive a couple of minutes in."
          action={
            id === "INC-2417" ? (
              <Button variant="primary" onClick={() => advanceTo("incident-detected")}>
                <SkipForward /> Advance demo to detection
              </Button>
            ) : (
              <Link href="/incidents" className="text-13 font-medium text-brand-700 hover:underline">
                All incidents
              </Link>
            )
          }
        />
      </div>
    );
  }

  const members = [...inc.affected, ...inc.exposed];
  return (
    <div className="mx-auto w-full max-w-[1480px] space-y-3 p-3 lg:p-4">
      <section className="rounded-xl border border-line bg-surface px-5 py-4 shadow-card">
        <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-xs text-ink-3">
          <Link href="/incidents" className="hover:text-ink hover:underline">
            Incidents
          </Link>
          <ChevronRight className="size-3.5 text-ink-5" aria-hidden />
          <span className="text-ink-2">Incident Intelligence</span>
        </nav>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className={cn("flex size-9 items-center justify-center rounded-xl text-white", inc.status === "resolved" ? "bg-ok-600" : inc.severity === "medium" ? "bg-warn-500" : "bg-crit-600")}>
                <Siren className="size-5" aria-hidden />
              </span>
              <h1 className="text-[22px] leading-8 font-semibold tracking-[-0.02em] text-ink">{inc.title}</h1>
              <SeverityBadge severity={inc.severity} />
              <span className={cn("inline-flex h-[22px] items-center rounded-full px-2 text-xs font-semibold capitalize", STATUS_CHIP[inc.status])}>{inc.status}</span>
              <SimTag />
            </div>
            <p className="mt-1 text-13 text-ink-2">
              <span className="font-mono text-ink-3">{inc.id}</span> · {inc.subtitle} · <span className="text-ink-3">{inc.simulatedCause}</span>
            </p>
            <p className="mt-1 flex items-center gap-1.5 text-xs text-ink-3">
              <Clock3 className="size-3.5" aria-hidden /> Detected {fmtTime(inc.detectedAt)} ({fmtRelative(inc.detectedAt, now)})
              {inc.resolvedAt ? ` · resolved ${fmtTime(inc.resolvedAt)}` : ""}
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <div className="flex items-center gap-2.5 rounded-lg border border-line bg-subtle px-3 py-2">
              <Avatar initials={people.supervisor.initials} tone="review" size={30} />
              <div className="leading-tight">
                <div className="text-2xs text-ink-4">Incident owner</div>
                <div className="text-13 font-semibold text-ink">{inc.owner.name}</div>
                <div className="text-2xs text-ink-3">
                  {inc.owner.role}
                  {inc.supervisorNotifiedAt ? ` · notified ${fmtTime(inc.supervisorNotifiedAt)}` : " · not yet notified"}
                </div>
              </div>
            </div>
            {inc.status !== "resolved" ? (
              <div className="flex gap-2">
                <Button size="sm" variant="secondary" onClick={notify}>
                  <UserRoundCheck /> Notify shift supervisor
                </Button>
                {inc.response.state !== "applied" ? (
                  <Button size="sm" variant="primary" onClick={apply}>
                    Apply group response
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      </section>

      <ConsolidationHero incident={inc} shipments={shipments} />

      <div className="grid items-start gap-3 xl:grid-cols-[minmax(0,1fr)_440px]">
        <div className="min-w-0 space-y-3">
          <section className="relative h-[460px] overflow-hidden rounded-xl border border-line shadow-card" aria-label="Incident map">
            <LazyNetworkMap variant="incident" incidentId={inc.id} shipmentIds={members} highlightIds={hoverId ? [hoverId] : null} className="absolute inset-0" />
            <div className="pointer-events-none absolute top-3 left-3 z-10 max-w-[70%] rounded-lg border border-line bg-surface/95 px-3 py-2 shadow-card backdrop-blur-sm">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-ink">
                <MapPinned className="size-3.5 text-crit-600" /> {inc.sharedFactor.label}
              </div>
              <div className="mt-0.5 text-2xs text-ink-3">
                {inc.affected.length} affected (solid) · {inc.exposed.length} exposed (dashed planned routes)
                {inc.kind === "route" && inc.response.state !== "applied" ? " · blue dashed = proposed reroute" : ""}
              </div>
            </div>
          </section>
          <MemberTable incident={inc} shipments={shipments} now={now} onHover={setHoverId} />
        </div>
        <div className="space-y-3">
          <ResponsePlan incident={inc} onApply={apply} onNotify={notify} onResolve={resolve} resolving={resolving} />
          <IncidentSignals incident={inc} />
          <IncidentTimeline incident={inc} />
        </div>
      </div>
    </div>
  );
}
