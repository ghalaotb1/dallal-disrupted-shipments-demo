"use client";

import { CheckCircle2, Inbox } from "lucide-react";
import { cn } from "@/lib/cn";
import { fmtTime } from "@/lib/time";
import { MANAGER_NAME, takeOver } from "@/lib/ops/agent";
import { findings, incidentSentence } from "@/lib/ops/narrative";
import { useOps } from "@/store/ops";
import { Button } from "@/components/common/Button";
import { PlanCard } from "@/components/ops/PlanCard";

const TONE = { info: "bg-brand-500", ok: "bg-ok-500", warn: "bg-warn-500", review: "bg-review-500" } as const;

/** What needs a manager: group plans and escalated cases, each with the reason, the evidence and a clear decision. */
export function ManagerPanel() {
  const plans = useOps((s) => s.plans);
  const runs = useOps((s) => s.runs);
  const parcels = useOps((s) => s.parcels);
  const events = useOps((s) => s.events);
  const cases = useOps((s) => s.cases);
  const pending = Object.values(plans).filter((p) => p.status === "ready" || p.status === "awaiting_evidence");
  const escalations = Object.values(runs).filter((r) => r.decision.type === "escalate" && parcels[r.ui.shipmentId]?.state === "awaiting_manager");
  const count = pending.filter((p) => p.status === "ready").length + escalations.length;

  return (
    <div className="space-y-4">
      <header className="flex items-center gap-2">
        <Inbox className="size-5 text-ink-3" aria-hidden />
        <h2 className="text-base font-semibold text-ink">Manager</h2>
        <span className="text-xs text-ink-3">{MANAGER_NAME}</span>
        <span className={cn("ml-auto rounded-full px-2 py-0.5 text-xs font-medium", count ? "bg-review-50 text-review-700" : "bg-muted text-ink-3")}>{count ? `${count} waiting` : "Nothing waiting"}</span>
      </header>

      {pending.map((plan) => {
        const c = cases.find((x) => x.planId === plan.plan_id);
        const run = c?.runId ? runs[c.runId] : undefined;
        const evidence = run ? findings(run).filter((f) => f.tone !== "ok").slice(0, 3) : [];
        return (
          <section key={plan.plan_id} className="space-y-3 rounded-xl border border-review-200 bg-surface p-4 shadow-card">
            <div>
              <p className="text-xs font-semibold tracking-[0.06em] text-ink-4 uppercase">Why Dallal escalated</p>
              <p className="mt-1 text-13 leading-5 text-ink">
                {run && c ? incidentSentence(String(run.decision.rationale ?? ""), Object.values(parcels).filter((q) => q.exception && q.incident).length, c.affectedDriverIds.length, c.exposedParcelIds.length) : "Several deliveries share one disruption."} The plan moves parcels between couriers, which needs a manager.
              </p>
            </div>
            {evidence.length ? (
              <ul className="space-y-1">
                {evidence.map((e) => (
                  <li key={e.id} className="text-xs text-ink-2">
                    <b>{e.label}:</b> {e.text}
                  </li>
                ))}
              </ul>
            ) : null}
            <PlanCard planId={plan.plan_id} mode="manager" />
          </section>
        );
      })}

      {escalations.map((r) => (
        <section key={r.ui.id} className="space-y-2 rounded-xl border border-review-200 bg-surface p-4 shadow-card">
          <p className="text-13 font-semibold text-ink">
            {r.ui.shipmentId}: {String(r.decision.headline ?? "Escalated")}
          </p>
          <p className="text-xs leading-5 text-ink-2">{String(r.decision.rationale ?? "")}</p>
          <Button size="sm" variant="review" onClick={() => takeOver(r.ui.shipmentId)}>
            <CheckCircle2 /> Take over
          </Button>
        </section>
      ))}

      {!count && !pending.length ? <p className="text-13 text-ink-3">Dallal handles routine recoveries alone. Group plans and sensitive cases appear here.</p> : null}

      <section>
        <p className="mb-1.5 text-xs font-semibold tracking-[0.06em] text-ink-4 uppercase">Activity</p>
        {events.length ? (
          <ul className="space-y-1.5">
            {events.slice(0, 8).map((e) => (
              <li key={e.id} className="flex items-start gap-2 text-xs text-ink-2">
                <span className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", TONE[e.tone])} aria-hidden />
                <span className="font-mono text-ink-4">{fmtTime(e.at)}</span>
                <span>{e.text}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-ink-4">No activity yet.</p>
        )}
      </section>
    </div>
  );
}
