"use client";

import Link from "next/link";
import { ArrowRight, Radar, Siren, SkipForward } from "lucide-react";
import { cn } from "@/lib/cn";
import { plural } from "@/lib/format";
import { fmtRelative, fmtTime } from "@/lib/time";
import { useDemoNow } from "@/hooks/useDemoNow";
import { useIncidents } from "@/hooks/useWorldData";
import { advanceTo } from "@/simulation/engine";
import { useWorld } from "@/store/world";
import { SeverityBadge, SimTag } from "@/components/common/Badges";
import { Button } from "@/components/common/Button";

export function IncidentsList() {
  const incidents = useIncidents();
  const now = useDemoNow(10_000);
  const detected = useWorld((w) => w.scenario.firedBeats.includes("incident-detected"));
  const open = incidents.filter((i) => i.status !== "resolved");
  const resolved = incidents.filter((i) => i.status === "resolved");

  return (
    <div className="mx-auto w-full max-w-[1180px] space-y-4 p-3 lg:p-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] leading-8 font-semibold tracking-[-0.02em] text-ink">Incidents</h1>
          <p className="mt-0.5 max-w-[72ch] text-13 text-ink-3">
            Dallal groups failures that share a cause — a corridor, a branch, a pickup point — using a rolling-baseline detector, so one response replaces many individual alerts.
          </p>
        </div>
        <SimTag label="simulated scenario" />
      </header>

      {!detected ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed border-line-strong bg-surface px-4 py-3">
          <div className="flex items-center gap-2.5 text-13 text-ink-2">
            <Radar className="size-4 text-brand-600" /> The detector is watching King Fahd Rd (DK-04). Failures there arrive a couple of minutes into the demo.
          </div>
          <Button size="sm" variant="secondary" onClick={() => advanceTo("incident-detected")}>
            <SkipForward /> Advance demo to detection
          </Button>
        </div>
      ) : null}

      <section aria-labelledby="open-incidents">
        <h2 id="open-incidents" className="mb-2 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">
          Open · {open.length}
        </h2>
        <div className="grid gap-3 md:grid-cols-2">
          {open.map((i) => (
            <IncidentCard key={i.id} id={i.id} now={now} />
          ))}
        </div>
      </section>
      <section aria-labelledby="resolved-incidents">
        <h2 id="resolved-incidents" className="mb-2 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">
          Resolved today · {resolved.length}
        </h2>
        <div className="grid gap-3 md:grid-cols-2">
          {resolved.map((i) => (
            <IncidentCard key={i.id} id={i.id} now={now} />
          ))}
        </div>
      </section>
    </div>
  );
}

function IncidentCard({ id, now }: { id: string; now: number }) {
  const inc = useWorld((w) => w.incidents[id]);
  if (!inc) return null;
  const maxCount = Math.max(1, ...inc.detector.series.map((p) => p.count));
  const resolved = inc.status === "resolved";
  return (
    <Link href={`/incidents/${inc.id}`} className={cn("group flex flex-col rounded-xl border bg-surface p-4 shadow-card transition-shadow hover:shadow-float", inc.status === "active" ? "border-crit-200" : "border-line")}>
      <div className="flex items-start gap-3">
        <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-xl text-white", resolved ? "bg-ok-600" : inc.severity === "medium" ? "bg-warn-500" : "bg-crit-600")}>
          <Siren className="size-[18px]" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-15 font-semibold text-ink">{inc.title}</span>
            <SeverityBadge severity={inc.severity} className="h-5 text-2xs" />
          </div>
          <div className="text-xs text-ink-3">
            {inc.id} · {inc.subtitle}
          </div>
        </div>
        <ArrowRight className="size-4 text-ink-4 transition-transform group-hover:translate-x-0.5 group-hover:text-brand-600" aria-hidden />
      </div>
      <div className="mt-3 flex items-end justify-between gap-4">
        <dl className="grid grid-cols-3 gap-4 text-xs">
          <div>
            <dt className="text-ink-4">Affected</dt>
            <dd className="text-[20px] leading-7 font-semibold text-ink">{inc.affected.length}</dd>
          </div>
          <div>
            <dt className="text-ink-4">Exposed</dt>
            <dd className="text-[20px] leading-7 font-semibold text-ink">{inc.exposed.length}</dd>
          </div>
          <div>
            <dt className="text-ink-4">Status</dt>
            <dd className="mt-1 font-semibold text-ink-2 capitalize">{inc.status}</dd>
          </div>
        </dl>
        <div className="flex h-10 items-end gap-[3px]" aria-label={`Detector: ${inc.detector.observed} failures in the current window vs baseline ${inc.detector.baselineMean.toFixed(1)}`}>
          {inc.detector.series.map((p) => (
            <span key={p.label} className={cn("w-[7px] rounded-t-[2px]", p.current ? (resolved ? "bg-ok-500" : inc.severity === "medium" || inc.status === "mitigating" ? "bg-warn-500" : "bg-crit-500") : "bg-ink-5/60")} style={{ height: `${Math.max(8, (p.count / maxCount) * 100)}%` }} />
          ))}
        </div>
      </div>
      <p className="mt-3 border-t border-line-soft pt-2.5 text-xs text-ink-3">
        Detected {fmtTime(inc.detectedAt)} ({fmtRelative(inc.detectedAt, now)}) · Response: <span className="font-medium text-ink-2">{inc.response.state.replace("_", " ")}</span> · {plural(inc.affected.length + inc.exposed.length, "shipment")} in one response
      </p>
    </Link>
  );
}
