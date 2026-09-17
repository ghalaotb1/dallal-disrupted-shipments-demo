"use client";

import { useState } from "react";
import { motion } from "motion/react";
import { Popover } from "radix-ui";
import { ChevronDown, CircleHelp, ListOrdered, Lock, RotateCcw, ShieldAlert, UserRoundCheck, Zap } from "lucide-react";
import { cn } from "@/lib/cn";
import { people } from "@/data/people";
import { fmtTime } from "@/lib/time";
import { useShallow } from "zustand/react/shallow";
import { useWorld } from "@/store/world";
import { Button } from "@/components/common/Button";
import { Tooltip } from "@/components/common/Tooltip";
import type { AgentRun, RecoveryAction, Shipment } from "@/types/domain";

const BASIS_TIP = {
  rule: "Business rule — deterministic logic from the diagnosis.",
  assumption: "Stated assumption — a rough operational cost weight, not measured.",
  simulated: "Simulated input — derived from the demo scenario's clock and SLA.",
};

export function RecoveryActions({
  shipment: s,
  run,
  busy,
  onRun,
  onEscalate,
}: {
  shipment: Shipment;
  run?: AgentRun;
  busy: boolean;
  onRun: (action: RecoveryAction) => void;
  onEscalate: (action?: RecoveryAction) => void;
}) {
  const actions = run?.actions ?? [];
  const [open, setOpen] = useState<string | null>(null);
  const handledByIncident = !!s.incident && s.agent.state === "incident";
  const done = s.health === "prevented" || s.health === "recovered" || s.closed;
  const awaiting = s.agent.state === "awaiting_supervisor";

  return (
    <section className="rounded-xl border border-line bg-surface shadow-card" aria-labelledby="actions-title">
      <header className="flex items-start justify-between gap-3 px-5 pt-4 pb-2">
        <div>
          <div className="flex items-center gap-2 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">
            <ListOrdered className="size-3.5" aria-hidden /> Recovery options
          </div>
          <h2 id="actions-title" className="mt-1 text-15 font-semibold text-ink">
            {actions.length ? `${actions.length} eligible actions, ranked` : s.closed ? "Decisions taken" : "Ranked after investigation"}
          </h2>
        </div>
        <RankingExplainer />
      </header>

      {!actions.length && s.closed ? (
        <ClosedDecisions id={s.id} />
      ) : !actions.length ? (
        <div className="space-y-2 px-5 pb-5">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center gap-3 rounded-lg border border-dashed border-line px-3 py-3">
              <span className="flex size-6 items-center justify-center rounded-full bg-muted text-2xs font-semibold text-ink-4">{i + 1}</span>
              <span className={cn("h-2.5 rounded-full bg-muted", i === 0 ? "w-2/3" : i === 1 ? "w-1/2" : "w-2/5")} />
            </div>
          ))}
          <p className="pt-1 text-xs text-ink-3">The agent ranks only actions that fit the diagnosed cause, with a transparent score — never a black-box probability.</p>
        </div>
      ) : (
        <ol className="space-y-2 px-5 pb-5">
          {actions.map((a, i) => {
            const expanded = open ? open === a.id : i === 0;
            const top = i === 0;
            return (
              <motion.li key={a.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }} className={cn("rounded-lg border", top ? "border-brand-200 bg-brand-25" : "border-line")}>
                <button className="flex w-full items-center gap-3 px-3 py-2.5 text-left" onClick={() => setOpen(expanded ? "__none" : a.id)} aria-expanded={expanded}>
                  <span className={cn("flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular", top ? "bg-brand-600 text-white" : "bg-muted text-ink-2")}>{a.rank}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-13 font-semibold text-ink">{a.title}</span>
                    {!expanded ? <span className="block truncate text-xs text-ink-3">{a.reason}</span> : null}
                  </span>
                  <ApprovalTag a={a} />
                  <ChevronDown className={cn("size-4 shrink-0 text-ink-4 transition-transform", expanded && "rotate-180")} aria-hidden />
                </button>
                {expanded ? (
                  <div className="border-t border-line-soft px-3 pt-2.5 pb-3 pl-12">
                    <p className="text-13 leading-5 text-ink-2">{a.reason}</p>
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {a.factors.map((f) => (
                        <Tooltip key={f.label} content={BASIS_TIP[f.basis]}>
                          <span className="inline-flex cursor-help items-center gap-1 rounded-md border border-line bg-surface px-1.5 py-0.5 text-xs">
                            <span className="text-ink-3">{f.label}</span>
                            <span className="font-medium text-ink capitalize">{f.value}</span>
                            <span className="rounded bg-muted px-1 text-[9.5px] font-semibold tracking-wide text-ink-4 uppercase">{f.basis}</span>
                          </span>
                        </Tooltip>
                      ))}
                    </div>
                    <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
                      <span className="font-mono text-2xs text-ink-4">tool: {a.tool}()</span>
                      <ActionButton a={a} busy={busy} disabled={handledByIncident || done || awaiting} onRun={onRun} onEscalate={onEscalate} />
                    </div>
                    {handledByIncident ? <p className="mt-2 text-xs text-crit-700">Handled at incident level — use the incident&apos;s group response.</p> : null}
                    {awaiting ? <p className="mt-2 text-xs text-review-700">Waiting for {people.supervisor.name}&apos;s decision.</p> : null}
                  </div>
                ) : null}
              </motion.li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

function ApprovalTag({ a }: { a: RecoveryAction }) {
  if (a.approval === "supervisor")
    return (
      <Tooltip content={a.approvalReason}>
        <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-review-50 px-2 py-0.5 text-2xs font-semibold whitespace-nowrap text-review-700 ring-1 ring-review-100 ring-inset">
          <Lock className="size-3" aria-hidden /> Supervisor approval
        </span>
      </Tooltip>
    );
  if (a.approval === "analyst")
    return (
      <Tooltip content={a.approvalReason}>
        <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-warn-50 px-2 py-0.5 text-2xs font-semibold whitespace-nowrap text-warn-700 ring-1 ring-warn-100 ring-inset">
          <ShieldAlert className="size-3" aria-hidden /> Your approval
        </span>
      </Tooltip>
    );
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-ok-50 px-2 py-0.5 text-2xs font-semibold whitespace-nowrap text-ok-700 ring-1 ring-ok-100 ring-inset">
      {a.reversible ? <RotateCcw className="size-3" aria-hidden /> : null}
      {a.automatable ? "Safe to automate" : "No approval"}
    </span>
  );
}

function ActionButton({ a, busy, disabled, onRun, onEscalate }: { a: RecoveryAction; busy: boolean; disabled: boolean; onRun: (a: RecoveryAction) => void; onEscalate: (a?: RecoveryAction) => void }) {
  if (a.kind === "supervisor_escalation" || a.approval === "supervisor") {
    return (
      <Button size="sm" variant="review" disabled={disabled || busy} onClick={() => onEscalate(a)}>
        <UserRoundCheck /> Request supervisor approval
      </Button>
    );
  }
  if (a.approval === "analyst") {
    return (
      <Button size="sm" variant="primary" disabled={disabled || busy} onClick={() => onRun(a)}>
        Approve & run
      </Button>
    );
  }
  return (
    <Button size="sm" variant={a.automatable ? "primary" : "secondary"} disabled={disabled || busy} onClick={() => onRun(a)}>
      <Zap /> {a.automatable ? "Run automated action" : "Run"}
    </Button>
  );
}

function RankingExplainer() {
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium text-ink-3 hover:bg-hover hover:text-ink-2">
          <CircleHelp className="size-3.5" /> How ranking works
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="end" sideOffset={6} className="z-[70] w-[340px] rounded-xl border border-line bg-surface p-4 text-13 shadow-pop outline-none">
          <div className="font-semibold text-ink">Transparent ranking formula</div>
          <p className="mt-1.5 rounded-md bg-subtle px-2 py-1.5 font-mono text-xs text-ink-2">score = 4·cause fit + 2·urgency + 1·(low impact) + 0.5·reversible</p>
          <ul className="mt-2.5 space-y-1.5 text-xs text-ink-2">
            <li>
              <span className="font-semibold">Cause fit</span> — business rule from the diagnosis.
            </li>
            <li>
              <span className="font-semibold">Urgency</span> — time left to SLA (simulated scenario clock).
            </li>
            <li>
              <span className="font-semibold">Impact</span> — stated cost assumption, not measured.
            </li>
            <li>
              <span className="font-semibold">Approval</span> — policy: high impact or custody change on COD ≥ SAR 1,000 needs the shift supervisor.
            </li>
          </ul>
          <p className="mt-2.5 text-xs text-ink-3">Scores only order the options. They are not probabilities, expected value or causal uplift — no intervention data exists yet to support such claims.</p>
          <Popover.Arrow className="fill-surface" />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function ClosedDecisions({ id }: { id: string }) {
  const entries = useWorld(useShallow((w) => w.ledger.filter((l) => l.shipmentId === id)));
  if (!entries.length) return <p className="px-5 pb-5 text-xs text-ink-3">No recovery decision was needed for this shipment.</p>;
  return (
    <ul className="space-y-2 px-5 pb-5">
      {entries.map((l) => (
        <li key={l.id} className="flex items-start justify-between gap-3 rounded-lg border border-line px-3 py-2.5">
          <div>
            <div className="text-13 font-semibold text-ink">{l.decision}</div>
            <div className="text-xs text-ink-3">
              {fmtTime(l.at)} · {l.decidedBy} · {l.basis}
            </div>
          </div>
          <span className="shrink-0 rounded-full bg-ok-50 px-2 py-0.5 text-2xs font-semibold text-ok-700 capitalize ring-1 ring-ok-100 ring-inset">{l.outcome}</span>
        </li>
      ))}
    </ul>
  );
}
