"use client";

import { CircleCheck, Lock, Route, Send, ShieldCheck, Undo2, UserRoundCheck, Workflow } from "lucide-react";
import { people } from "@/data/people";
import { cn } from "@/lib/cn";
import { plural } from "@/lib/format";
import { fmtTime } from "@/lib/time";
import { Button } from "@/components/common/Button";
import type { Incident } from "@/types/domain";

const STEP_ICON: Record<string, typeof Route> = { reroute: Route, resume: Workflow, notify: Send, codes: Undo2 };

export function ResponsePlan({ incident: inc, onApply, onNotify, onResolve, resolving }: { incident: Incident; onApply: () => void; onNotify: () => void; onResolve: () => void; resolving: boolean }) {
  const r = inc.response;
  const applied = r.state === "applied";
  const total = new Set(r.steps.flatMap((s) => s.shipments)).size;
  return (
    <section className={cn("rounded-xl border bg-surface shadow-card", applied ? "border-ok-200" : "border-brand-200")} aria-labelledby="response-title">
      <header className={cn("rounded-t-xl px-5 pt-4 pb-3", applied ? "bg-ok-50" : "bg-brand-25")}>
        <div className="flex items-center gap-2 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">
          <ShieldCheck className="size-3.5" aria-hidden /> Recommended response
        </div>
        <h2 id="response-title" className="mt-1 text-15 font-semibold text-ink">
          {applied ? "Group response applied" : `One response for ${plural(total, "shipment")}`}
        </h2>
        <p className="mt-0.5 text-xs text-ink-2">{r.summary}</p>
      </header>
      <ol className="space-y-2 px-5 py-3">
        {r.steps.map((st, i) => {
          const Icon = STEP_ICON[st.id] ?? Workflow;
          return (
            <li key={st.id} className="flex gap-3 rounded-lg border border-line-soft px-3 py-2.5">
              <span className={cn("flex size-7 shrink-0 items-center justify-center rounded-lg", applied ? "bg-ok-50 text-ok-600" : "bg-muted text-ink-2")}>
                {applied ? <CircleCheck className="size-4" aria-label="done" /> : <Icon className="size-4" aria-hidden />}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-13 font-semibold text-ink">
                    {i + 1}. {st.title}
                  </span>
                  <span className="shrink-0 text-2xs text-ink-3 tabular">{plural(st.shipments.length, "shipment")}</span>
                </div>
                <div className="text-xs text-ink-3">{st.detail}</div>
                <div className="mt-1 font-mono text-2xs text-ink-4">{st.tool}()</div>
              </div>
            </li>
          );
        })}
      </ol>
      <div className="space-y-2.5 border-t border-line-soft px-5 py-3">
        {r.approvalRequired && !applied ? (
          <p className="flex items-start gap-2 text-xs text-ink-3">
            <Lock className="mt-0.5 size-3.5 shrink-0 text-review-600" aria-hidden />
            Group actions affecting more than 3 shipments need approval from {people.supervisor.name} ({people.supervisor.role.toLowerCase()}). Applying sends the request first.
          </p>
        ) : null}
        {applied ? (
          <p className="flex items-center gap-2 text-xs text-ok-700">
            <CircleCheck className="size-3.5" /> Approved by {r.approvedBy} · applied {r.appliedAt ? fmtTime(r.appliedAt) : ""}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {inc.status === "resolved" ? (
            <span className="text-13 font-medium text-ok-700">Incident resolved {inc.resolvedAt ? `at ${fmtTime(inc.resolvedAt)}` : ""}</span>
          ) : applied ? (
            <Button variant="primary" onClick={onResolve} loading={resolving}>
              <CircleCheck /> Resolve incident
            </Button>
          ) : (
            <Button variant="primary" onClick={onApply} disabled={r.state === "awaiting_approval"}>
              <ShieldCheck /> Apply group response
            </Button>
          )}
          {inc.status !== "resolved" ? (
            <Button variant="secondary" onClick={onNotify}>
              <UserRoundCheck /> {inc.supervisorNotifiedAt ? "Notify supervisor again" : "Notify shift supervisor"}
            </Button>
          ) : null}
        </div>
      </div>
    </section>
  );
}
