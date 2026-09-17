"use client";

import { AnimatePresence, motion } from "motion/react";
import { Check, CircleDot, Equal, EqualNot, FileQuestion, Minus, ScanSearch, TriangleAlert, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { fmtTime } from "@/lib/time";
import { SimTag } from "@/components/common/Badges";
import { Button } from "@/components/common/Button";
import type { AgentRun, Diagnosis, Evidence, RiskAssessment, Shipment } from "@/types/domain";

const STANCE: Record<Evidence["stance"], { icon: typeof Check; cls: string; label: string }> = {
  supports: { icon: Check, cls: "bg-ok-50 text-ok-600 ring-ok-200", label: "Supports likely cause" },
  contradicts: { icon: X, cls: "bg-crit-50 text-crit-600 ring-crit-200", label: "Contradicts recorded code" },
  context: { icon: Minus, cls: "bg-muted text-ink-3 ring-line", label: "Context" },
};

export function DiagnosisCard({ shipment: s, run, running, onInvestigate, stale }: { shipment: Shipment; run?: AgentRun; running: boolean; onInvestigate: () => void; stale: boolean }) {
  const d = run?.diagnosis;
  return (
    <section className="rounded-xl border border-line bg-surface shadow-card" aria-labelledby="diagnosis-title">
      <header className="flex items-start justify-between gap-3 px-5 pt-4">
        <div>
          <div className="flex items-center gap-2 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">
            <ScanSearch className="size-3.5" aria-hidden /> {d ? (s.exception ? "What happened" : "What is likely to happen") : "Signals"}
          </div>
          <h2 id="diagnosis-title" className="mt-1 text-[17px] leading-6 font-semibold tracking-[-0.01em] text-ink">
            {d ? d.headline : s.closed ? "Resolved earlier today" : s.exception ? `Exception recorded: ${s.exception.label}` : s.health === "on_track" ? "No disruption signals" : "Risk rose before any failure"}
          </h2>
        </div>
        {d ? (
          <div className="shrink-0 text-right text-xs text-ink-3">
            <div>
              Confidence <span className={cn("font-semibold capitalize", d.confidence === "high" ? "text-ink" : d.confidence === "medium" ? "text-warn-700" : "text-crit-700")}>{d.confidence}</span>
            </div>
            <div className="text-ink-4">as of {fmtTime(run!.finishedAt ?? run!.startedAt)}</div>
          </div>
        ) : null}
      </header>

      <AnimatePresence mode="wait" initial={false}>
        {d ? (
          <motion.div key="diagnosis" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="px-5 pt-1.5 pb-5">
            <p className="max-w-[70ch] text-13 leading-5 text-ink-2">{d.summary}</p>
            {s.outcome && (s.health === "prevented" || s.health === "recovered") ? (
              <p className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-ok-50 px-2 py-1 text-xs font-medium text-ok-700">
                <Check className="size-3.5" /> Outcome at {fmtTime(s.outcome.at)}: {s.outcome.label}
              </p>
            ) : null}
            {stale ? (
              <p className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-warn-50 px-2 py-1 text-xs text-warn-700">
                <TriangleAlert className="size-3.5" /> New events since this investigation — re-run the agent to refresh.
              </p>
            ) : null}
            <Comparison d={d} s={s} />
            <div className="mt-4">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold text-ink-2">Evidence ({d.evidence.length})</h3>
                <div className="flex items-center gap-3 text-2xs text-ink-4">
                  {(Object.keys(STANCE) as Evidence["stance"][]).map((k) => {
                    const I = STANCE[k].icon;
                    return (
                      <span key={k} className="flex items-center gap-1">
                        <span className={cn("flex size-3.5 items-center justify-center rounded-full ring-1", STANCE[k].cls)}>
                          <I className="size-2.5" strokeWidth={3} aria-hidden />
                        </span>
                        {STANCE[k].label}
                      </span>
                    );
                  })}
                </div>
              </div>
              <ul className="mt-2 divide-y divide-line-soft rounded-lg border border-line-soft">
                {d.evidence.map((e, i) => {
                  const st = STANCE[e.stance];
                  const I = st.icon;
                  return (
                    <motion.li key={e.id} initial={{ opacity: 0, x: -4 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }} className="flex items-start gap-3 px-3 py-2.5">
                      <span className={cn("mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full ring-1", st.cls)} title={st.label}>
                        <I className="size-3" strokeWidth={3} aria-hidden />
                        <span className="sr-only">{st.label}</span>
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="text-13 font-medium text-ink">{e.label}</div>
                        <div className="text-xs text-ink-3">{e.detail}</div>
                      </div>
                      <span className="shrink-0 rounded-md bg-subtle px-1.5 py-0.5 text-2xs text-ink-3">{e.source}</span>
                    </motion.li>
                  );
                })}
              </ul>
            </div>
          </motion.div>
        ) : (
          <motion.div key="signals" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="px-5 pt-2 pb-5">
            {s.closed ? (
              <div className="rounded-lg border border-ok-200 bg-ok-50 px-4 py-3">
                <div className="text-13 font-semibold text-ok-700">Case closed · {s.outcome?.label ?? "Delivered"}</div>
                <p className="mt-0.5 text-xs text-ink-2">
                  {s.headline ?? "The exception was resolved earlier today."} The full sequence of signals, decisions and outcomes is in the journey below.
                </p>
              </div>
            ) : null}
            {s.closed ? null : <Signals s={s} risk={s.risk} />}
            {s.closed ? null : (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed border-line-strong bg-subtle px-4 py-3">
              <p className="max-w-[52ch] text-xs text-ink-3">
                {running
                  ? "The agent is gathering evidence — the diagnosis will appear here as tools return."
                  : "These are raw signals. Run the agent to check them against journey evidence, diagnose the likely cause and rank recovery actions."}
              </p>
              {!running ? (
                <Button size="sm" variant="primary" onClick={onInvestigate}>
                  <ScanSearch /> Investigate
                </Button>
              ) : null}
            </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

function Comparison({ d, s }: { d: Diagnosis; s: Shipment }) {
  const conflict = d.agreement === "conflicts";
  const agrees = d.agreement === "agrees";
  const inconclusive = d.agreement === "inconclusive";
  const Mid = conflict ? EqualNot : agrees ? Equal : inconclusive ? FileQuestion : CircleDot;
  return (
    <div className="mt-4 grid grid-cols-[1fr_auto_1fr] items-stretch gap-2">
      <div className="rounded-lg border border-line bg-subtle p-3">
        <div className="text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">Recorded exception</div>
        {d.recorded ? (
          <>
            <div className="mt-1 flex items-center gap-2">
              <span className="rounded bg-ink px-1.5 py-0.5 font-mono text-2xs font-semibold text-white">{d.recorded.code}</span>
              <span className="text-13 font-semibold text-ink">{d.recorded.label}</span>
            </div>
            {s.exception ? (
              <div className="mt-1 text-xs text-ink-3">
                {s.exception.recordedBy} · {fmtTime(s.exception.recordedAt)}
              </div>
            ) : null}
          </>
        ) : (
          <div className="mt-1 text-13 text-ink-3">None yet — nothing has failed</div>
        )}
      </div>
      <div className="flex flex-col items-center justify-center px-1">
        <span
          className={cn(
            "flex size-8 items-center justify-center rounded-full ring-1",
            conflict ? "bg-crit-50 text-crit-600 ring-crit-200" : agrees ? "bg-ok-50 text-ok-600 ring-ok-200" : inconclusive ? "bg-review-50 text-review-600 ring-review-200" : "bg-brand-50 text-brand-600 ring-brand-200",
          )}
        >
          <Mid className="size-4" strokeWidth={2.5} aria-hidden />
        </span>
        <span className={cn("mt-1 text-2xs font-semibold", conflict ? "text-crit-700" : agrees ? "text-ok-700" : inconclusive ? "text-review-700" : "text-brand-700")}>
          {conflict ? "Conflict" : agrees ? "Agrees" : inconclusive ? "Unclear" : "Predicted"}
        </span>
      </div>
      <div className={cn("rounded-lg border p-3", conflict ? "border-crit-200 bg-crit-50/60" : inconclusive ? "border-review-200 bg-review-50/60" : "border-brand-200 bg-brand-25")}>
        <div className="text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">What the evidence shows</div>
        <div className="mt-1 text-13 font-semibold text-ink">{d.causeLabel}</div>
        <div className="mt-1 text-xs text-ink-3">
          {d.evidence.filter((e) => e.stance !== "context").length} independent signals · confidence {d.confidence}
        </div>
      </div>
    </div>
  );
}

function Signals({ s, risk }: { s: Shipment; risk: RiskAssessment }) {
  return (
    <div className="grid gap-3 md:grid-cols-2">
      <div className="rounded-lg border border-line-soft p-3">
        <div className="flex items-center justify-between">
          <span className="text-xs font-semibold text-ink-2">Risk drivers</span>
          <SimTag label="prototype heuristic" tip="Transparent additive score over simulated signals. The trained failure-risk model replaces this in the next phase — no model accuracy is claimed." />
        </div>
        {risk.drivers.length ? (
          <ul className="mt-2 space-y-1.5">
            {risk.drivers.map((dr) => (
              <li key={dr.label} className="flex items-start gap-2 text-xs">
                <span className={cn("mt-0.5 font-semibold", dr.effect === "raises" ? "text-crit-600" : "text-ok-600")} aria-label={dr.effect}>
                  {dr.effect === "raises" ? "↑" : "↓"}
                </span>
                <span className="flex-1 text-ink-2">{dr.label}</span>
                <span className="text-2xs text-ink-4">{dr.source}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-xs text-ink-3">No risk drivers — shipment progressing normally.</p>
        )}
      </div>
      <div className="rounded-lg border border-line-soft p-3">
        <span className="text-xs font-semibold text-ink-2">Recorded exception</span>
        {s.exception ? (
          <div className="mt-2">
            <div className="flex items-center gap-2">
              <span className="rounded bg-ink px-1.5 py-0.5 font-mono text-2xs font-semibold text-white">{s.exception.code}</span>
              <span className="text-13 font-medium text-ink">{s.exception.label}</span>
            </div>
            <p className="mt-1 text-xs text-ink-3">
              {s.exception.recordedBy} · {fmtTime(s.exception.recordedAt)}. Dallal does not trust a single code — it checks it against GPS, contact logs and route telemetry.
            </p>
          </div>
        ) : (
          <p className="mt-2 text-xs text-ink-3">No exception recorded. Dallal flags risk before anything fails.</p>
        )}
      </div>
    </div>
  );
}
