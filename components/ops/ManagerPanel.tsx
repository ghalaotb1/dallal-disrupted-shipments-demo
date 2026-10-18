"use client";

import { CheckCircle2, Inbox, UserCheck } from "lucide-react";
import { cn } from "@/lib/cn";
import { fmtTime } from "@/lib/time";
import { MANAGER_NAME, takeOver } from "@/lib/ops/agent";
import { findings, incidentSentence } from "@/lib/ops/narrative";
import { useOps } from "@/store/ops";
import { Button } from "@/components/common/Button";
import { PlanCard } from "@/components/ops/PlanCard";

const TONE = { info: "bg-brand-500", ok: "bg-ok-500", warn: "bg-warn-500", review: "bg-review-500" } as const;

/** What needs a manager: group plans (policy: supervisor only) and escalated cases, each with the evidence and a clear decision. */
export function ManagerPanel() {
  const plans = useOps((s) => s.plans);
  const runs = useOps((s) => s.runs);
  const parcels = useOps((s) => s.parcels);
  const events = useOps((s) => s.events);
  const active = useOps((s) => s.active);
  const pending = Object.values(plans).filter((p) => p.status === "ready" || p.status === "awaiting_evidence");
  const escalations = Object.values(runs).filter((r) => r.decision.type === "escalate" && parcels[r.ui.shipmentId]?.state === "awaiting_manager");
  const count = pending.filter((p) => p.status === "ready").length + escalations.length;

  return (
    <div className="space-y-4">
      <header>
        <div className="flex items-center gap-2 text-xs font-semibold tracking-[0.06em] text-review-700 uppercase">
          <UserCheck className="size-3.5" aria-hidden /> Manager · {MANAGER_NAME}
        </div>
        <h2 className="mt-1 flex items-center gap-2 text-lg leading-6 font-semibold text-ink">
          <Inbox className="size-5 text-ink-3" aria-hidden /> {count ? `${count} decision${count > 1 ? "s" : ""} waiting for you` : "Nothing needs your approval"}
        </h2>
        {!count ? <p className="mt-1 text-13 leading-5 text-ink-3">Dallal handles routine recoveries on its own, inside strict limits (low value, reversible, high confidence). Group plans and uncertain or sensitive cases come here.</p> : null}
      </header>

      {pending.map((plan) => {
        const run = active?.runId ? runs[active.runId] : undefined;
        const evidence = run ? findings(run).filter((f) => f.tone !== "ok").slice(0, 3) : [];
        return (
          <section key={plan.plan_id} className="space-y-3 rounded-xl border border-review-200 bg-surface p-4 shadow-card">
            <div>
              <p className="text-xs font-semibold tracking-[0.06em] text-ink-4 uppercase">Why Dallal is asking you</p>
              <p className="mt-1 text-13 leading-5 text-ink">
                {run && active ? incidentSentence(String(run.decision.rationale ?? ""), Object.values(parcels).filter((q) => q.exception && q.incident).length, active.affectedDriverIds.length, active.exposedParcelIds.length) : "Several deliveries share one disruption."} One coordinated response beats case-by-case fixes. The recovery moves parcels between couriers and pickup points, which affects several customers and shared capacity, so policy requires a manager.
              </p>
            </div>
            {evidence.length ? (
              <ul className="space-y-1">
                {evidence.map((e) => (
                  <li key={e.id} className="text-xs text-ink-2">
                    <b>{e.label}:</b> {e.text}
                    {e.detail ? <span className="text-ink-3"> · {e.detail}</span> : null}
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
          {r.decision.question ? <p className="text-xs text-ink-2"><b>Question:</b> {String(r.decision.question)}</p> : null}
          <Button size="sm" variant="review" onClick={() => takeOver(r.ui.shipmentId)}>
            <CheckCircle2 /> Take over this case
          </Button>
        </section>
      ))}

      <section>
        <p className="mb-1.5 text-xs font-semibold tracking-[0.06em] text-ink-4 uppercase">Recent activity</p>
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
