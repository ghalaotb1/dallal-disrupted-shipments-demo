"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowRight, Bot, CircleCheck, Info, Loader2, OctagonAlert, RotateCcw, Siren, Sparkles, TriangleAlert, UserRoundCheck, Zap } from "lucide-react";
import { cn } from "@/lib/cn";
import { fmtTime } from "@/lib/time";
import { Tooltip } from "@/components/common/Tooltip";
import { Button } from "@/components/common/Button";
import { InquiryCard } from "@/components/live/InquiryCard";
import { LiveTag } from "@/components/live/LiveTags";
import type { AgentOutcome, AgentRun, AgentStep } from "@/types/domain";

const STATUS = {
  running: { icon: Loader2, cls: "bg-brand-50 text-brand-600 ring-brand-200", spin: true },
  ok: { icon: CircleCheck, cls: "bg-ok-50 text-ok-600 ring-ok-200" },
  warn: { icon: TriangleAlert, cls: "bg-warn-50 text-warn-600 ring-warn-200" },
  alert: { icon: OctagonAlert, cls: "bg-crit-50 text-crit-600 ring-crit-200" },
} as const;

const KIND = { read: "Read", analysis: "Analysis", action: "Action", inquiry: "Question" } as const;

export function AgentPanel({
  investigation,
  execution,
  running,
  onInvestigate,
  canInvestigate,
  incidentMode,
}: {
  investigation?: AgentRun;
  execution?: AgentRun;
  running?: AgentRun;
  onInvestigate: () => void;
  canInvestigate: boolean;
  incidentMode?: boolean;
}) {
  const busy = !!running;
  return (
    <section className="flex min-h-0 flex-col rounded-xl border border-line bg-surface shadow-card" aria-label="Agent investigation">
      <header className="flex items-start justify-between gap-3 border-b border-line-soft px-4 py-3">
        <div className="flex items-start gap-2.5">
          <span className="mt-0.5 flex size-8 items-center justify-center rounded-lg bg-brand-600 text-white shadow-[0_1px_2px_rgb(15_30_54/0.25)]">
            <Bot className="size-[18px]" aria-hidden />
          </span>
          <div>
            <h2 className="flex items-center gap-1.5 text-sm font-semibold text-ink">
              Agent investigation
              {(investigation ?? running)?.source === "live" ? <LiveTag /> : null}
            </h2>
            <p className="text-xs text-ink-3">
              {running ? (
                <span className="text-brand-700">
                  {running.mode === "execution"
                    ? "Executing action…"
                    : running.backendStatus === "awaiting_response"
                      ? "Paused — waiting for an answer to a question the agent asked"
                      : "Investigating — choosing tools from evidence…"}
                </span>
              ) : investigation ? (
                <>
                  Run at {fmtTime(investigation.startedAt)} · {investigation.steps.length} tool calls
                </>
              ) : (
                "Tool-using agent · visible trace"
              )}
            </p>
          </div>
        </div>
        {investigation && !busy && canInvestigate ? (
          <Button size="xs" variant="ghost" onClick={onInvestigate}>
            <RotateCcw /> Re-run
          </Button>
        ) : null}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 scrollbar-thin">
        {!investigation && !running ? (
          <div className="py-2">
            <p className="text-13 leading-5 text-ink-2">
              The agent investigates with typed tools — shipment record, journey scans, address and route context, the risk score, the evidence check and the incident detector — and{" "}
              <span className="font-medium text-ink">chooses the next tool from what it finds</span>. Different cases take different paths.
            </p>
            <div className="mt-3 flex flex-wrap gap-1.5" aria-label="Available tools">
              {["get_shipment", "get_journey", "get_address_context", "get_route_context", "predict_risk", "analyze_disruption", "check_incident_context", "rank_recovery_actions", "retrieve_policy_constraints"].map((t) => (
                <span key={t} className="rounded-md bg-muted px-1.5 py-0.5 font-mono text-[10.5px] text-ink-3">
                  {t}()
                </span>
              ))}
            </div>
            <Button variant="primary" className="mt-4 w-full" onClick={onInvestigate} disabled={!canInvestigate}>
              <Sparkles /> Investigate with agent
            </Button>
            {incidentMode ? <p className="mt-2 text-xs text-ink-3">This shipment belongs to an incident — the agent will route it to the incident response.</p> : null}
          </div>
        ) : null}

        {[investigation, execution].map((run) =>
          run ? (
            <RunTrace key={run.id} run={run} title={run.mode === "execution" ? "Action execution" : undefined} />
          ) : null,
        )}
        {running && running !== investigation && running !== execution ? <RunTrace run={running} title={running.mode === "execution" ? "Action execution" : undefined} /> : null}
      </div>

      <footer className="flex items-start gap-2 border-t border-line-soft px-4 py-2.5 text-2xs leading-4 text-ink-4">
        <Info className="mt-px size-3.5 shrink-0" aria-hidden />
        {(investigation ?? running)?.source === "live" ? (
          <span>
            Live backend: a Bayesian belief over causes, tools and questions chosen by net value of information, bounded-autonomy policy. The agent never invents numbers — tools produce them. Probabilities are expert assumptions, not fitted
            to SPL data. Actions only touch the simulated environment.
          </span>
        ) : (
          <span>Prototype planner: a deterministic policy over the same tool interface an LLM agent will call. The agent never invents numbers — tools produce them. Action tools only touch the demo environment.</span>
        )}
      </footer>
    </section>
  );
}

function RunTrace({ run, title }: { run: AgentRun; title?: string }) {
  const reduce = useReducedMotion();
  return (
    <div className={cn(title && "mt-4 border-t border-dashed border-line pt-3")}>
      {title ? (
        <div className="mb-2 flex items-center gap-1.5 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">
          <Zap className="size-3" aria-hidden /> {title} · {fmtTime(run.startedAt)}
        </div>
      ) : (
        <PathSignature run={run} />
      )}
      <ol className="relative">
        <AnimatePresence initial={false}>
          {run.steps.map((step, i) => (
            <motion.li
              key={step.id}
              initial={reduce ? { opacity: 0 } : { opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.28, ease: "easeOut" }}
              className="relative flex gap-3 pb-3 last:pb-1"
            >
              {i < run.steps.length - 1 ? <span className="absolute top-7 bottom-0 left-[13px] w-px bg-line" aria-hidden /> : null}
              <StepIcon status={step.status} />
              <StepBody step={step} run={run} />
            </motion.li>
          ))}
        </AnimatePresence>
      </ol>
      <AnimatePresence>{run.outcome ? <OutcomeBox key="outcome" outcome={run.outcome} /> : null}</AnimatePresence>
      {run.backend?.utility_table?.length && run.outcome ? <UtilityTable run={run} /> : null}
    </div>
  );
}

function PathSignature({ run }: { run: AgentRun }) {
  if (!run.steps.length) return null;
  return (
    <div className="mb-3 rounded-lg bg-subtle px-2.5 py-2">
      <div className="flex items-center gap-1 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">
        Path chosen for this case
        <Tooltip content="The planner picks each next tool from the previous results, so an address case, a code conflict and an unknown pattern follow different paths.">
          <Info className="size-3 cursor-help" aria-label="About the path" />
        </Tooltip>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-1 gap-y-1 font-mono text-[10.5px] text-ink-2">
        {run.steps.map((s, i) => (
          <span key={s.id} className="flex items-center gap-1">
            <span className={cn("rounded px-1 py-px", s.status === "alert" ? "bg-crit-50 text-crit-700" : s.status === "warn" ? "bg-warn-50 text-warn-700" : s.status === "running" ? "bg-brand-50 text-brand-700" : "bg-surface text-ink-2 ring-1 ring-line")}>
              {s.tool.replace(/_/g, "_​")}
            </span>
            {i < run.steps.length - 1 ? <ArrowRight className="size-3 text-ink-5" aria-hidden /> : null}
          </span>
        ))}
      </div>
    </div>
  );
}

function StepIcon({ status }: { status: AgentStep["status"] }) {
  const s = STATUS[status];
  const Icon = s.icon;
  return (
    <span className={cn("relative z-[1] flex size-7 shrink-0 items-center justify-center rounded-full ring-1", s.cls)}>
      <Icon className={cn("size-3.5", "spin" in s && s.spin && "animate-spin")} strokeWidth={2.4} aria-hidden />
      <span className="sr-only">{status}</span>
    </span>
  );
}

function StepBody({ step, run }: { step: AgentStep; run: AgentRun }) {
  const running = step.status === "running";
  return (
    <div className="min-w-0 flex-1 pt-0.5">
      <div className="flex items-center gap-2">
        <span className="font-mono text-[12.5px] font-semibold text-ink">{step.tool}()</span>
        <span className="rounded bg-muted px-1 text-[9.5px] font-semibold tracking-wide text-ink-3 uppercase">{KIND[step.kind]}</span>
        {step.durationMs ? <span className="ml-auto text-2xs text-ink-4 tabular">{(step.durationMs / 1000).toFixed(1)}s</span> : null}
      </div>
      {running ? (
        <p className="text-shimmer mt-0.5 text-xs">{step.checking}</p>
      ) : (
        <>
          <p className="mt-0.5 text-xs text-ink-4">{step.checking}</p>
          {step.summary ? (
            <p className={cn("mt-1 text-13 leading-5 font-medium", step.status === "alert" ? "text-crit-700" : step.status === "warn" ? "text-warn-700" : "text-ink")}>{step.summary}</p>
          ) : null}
          {step.facts?.length ? (
            <ul className="mt-1 space-y-0.5">
              {step.facts.map((f, fi) => (
                <li key={`${fi}-${f}`} className="flex gap-1.5 text-xs text-ink-2">
                  <span className="mt-[7px] size-1 shrink-0 rounded-full bg-ink-5" aria-hidden />
                  <span>{f}</span>
                </li>
              ))}
            </ul>
          ) : null}
          {step.belief ? (
            <p className="mt-1 font-mono text-[10.5px] leading-4 text-ink-4" title="Belief after this step (mixture over uncertain likelihood tables)">
              belief: {step.belief.top.slice(0, 3).map(([c, p]) => `${c.replace(/_/g, " ")} ${Math.round(p * 100)}%`).join(" · ")} · systemic {Math.round(step.belief.p_systemic * 100)}%
            </p>
          ) : null}
          {step.kind === "inquiry" ? (() => {
            const inq = run.backend?.inquiries.find((i) => i.inquiry_id === step.inquiryId);
            return inq ? <InquiryCard inquiry={inq} /> : null;
          })() : null}
        </>
      )}
    </div>
  );
}

const OUTCOME_STYLE: Record<AgentOutcome["type"], { cls: string; icon: typeof Bot; label: string }> = {
  recommend: { cls: "border-brand-200 bg-brand-25 text-brand-800", icon: Sparkles, label: "Recommendation" },
  auto_eligible: { cls: "border-ok-200 bg-ok-50 text-ok-700", icon: Zap, label: "Eligible for automated action" },
  escalate: { cls: "border-review-200 bg-review-50 text-review-700", icon: UserRoundCheck, label: "Escalation required" },
  incident: { cls: "border-crit-200 bg-crit-50 text-crit-700", icon: Siren, label: "Incident-level handling" },
  resolved: { cls: "border-ok-200 bg-ok-50 text-ok-700", icon: CircleCheck, label: "Outcome" },
};

function OutcomeBox({ outcome }: { outcome: AgentOutcome }) {
  const s = OUTCOME_STYLE[outcome.type];
  const Icon = s.icon;
  return (
    <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className={cn("mt-1 rounded-lg border px-3 py-2.5", s.cls)} role="status">
      <div className="flex items-center gap-1.5 text-2xs font-semibold tracking-[0.06em] uppercase opacity-80">
        <Icon className="size-3.5" aria-hidden /> {s.label}
      </div>
      <p className="mt-1 text-13 font-semibold text-ink">{outcome.headline}</p>
      <p className="mt-0.5 text-xs text-ink-2">{outcome.rationale}</p>
      {outcome.type === "escalate" ? <p className="mt-1.5 text-xs text-ink-2">Open question: “{outcome.question}”</p> : null}
    </motion.div>
  );
}

function UtilityTable({ run }: { run: AgentRun }) {
  const b = run.backend!;
  return (
    <details className="mt-2 rounded-lg border border-line-soft bg-subtle px-2.5 py-1.5 text-xs">
      <summary className="cursor-pointer text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">
        Why this option · expected utility (SAR-equivalent, assumed) · stability {Math.round((b.decision.decision_stability ?? 0) * 100)}% · {b.virtual_minutes.toFixed(0)} min elapsed
      </summary>
      <table className="mt-1.5 w-full text-left tabular">
        <thead className="text-ink-4">
          <tr>
            <th className="font-medium">Option</th>
            <th className="font-medium">EU</th>
            <th className="font-medium">Approval</th>
            <th className="font-medium">Delay</th>
            <th className="font-medium">Cost</th>
          </tr>
        </thead>
        <tbody>
          {b.utility_table.map((r, i) => (
            <tr key={r.option} className={cn(i === 0 && "font-semibold text-ink")}>
              <td className="font-mono">{r.option}</td>
              <td>{r.eu.toFixed(1)}</td>
              <td>{r.approval}</td>
              <td>{r.delay_min.toFixed(0)}m</td>
              <td>{r.cost.toFixed(0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-ink-4">Decision stability = share of table-uncertainty particles that agree on this option. Values depend on stated assumptions, not SPL accounting.</p>
    </details>
  );
}
