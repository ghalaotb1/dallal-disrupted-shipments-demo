"use client";

import { useEffect, useRef } from "react";
import { Bot, Check, ChevronDown, CircleHelp, Loader2, ShieldCheck, TriangleAlert, UserRoundSearch, X } from "lucide-react";
import { cn } from "@/lib/cn";
import { executeRun } from "@/lib/ops/agent";
import { askStep, beliefStory, bestUnaskedQuestion, CAUSE, findings, incidentSentence, inquiryFor, pct, safetyChecks, WHO } from "@/lib/ops/narrative";
import { getUi, setUi, useOps, useOpsUi } from "@/store/ops";
import { Button } from "@/components/common/Button";
import { PlanCard } from "@/components/ops/PlanCard";
import { ReplyDevice } from "@/components/ops/ReplyDevice";
import type { RunRecord } from "@/types/ops";

const TONE = { ok: "text-ok-600", warn: "text-warn-600", alert: "text-crit-600" } as const;
const DOT = { ok: "bg-ok-500", warn: "bg-warn-500", alert: "bg-crit-500" } as const;

function Stage({ n, title, children, active = true }: { n: number; title: string; children: React.ReactNode; active?: boolean }) {
  return (
    <section className={cn("relative pl-9", !active && "opacity-60")}>
      <span className="absolute top-0 left-0 flex size-6 items-center justify-center rounded-full bg-ink text-xs font-semibold text-white">{n}</span>
      <h3 className="text-xs font-semibold tracking-[0.06em] text-ink-3 uppercase">{title}</h3>
      <div className="mt-1.5">{children}</div>
    </section>
  );
}

function BeliefBars({ top, label }: { top: [string, number][]; label: string }) {
  return (
    <div className="min-w-0 flex-1">
      <p className="text-[11px] font-medium text-ink-4">{label}</p>
      <ul className="mt-1 space-y-1">
        {top.slice(0, 3).map(([c, p], i) => (
          <li key={c} className="flex items-center gap-2 text-xs">
            <span className={cn("w-32 shrink-0 truncate", i === 0 ? "font-semibold text-ink" : "text-ink-3")}>{CAUSE[c] ?? c}</span>
            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
              <span className={cn("block h-full rounded-full transition-all duration-700", i === 0 ? "bg-brand-500" : "bg-ink-5")} style={{ width: `${Math.round(p * 100)}%` }} />
            </span>
            <span className="w-9 text-right tabular text-ink-2">{pct(p)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The real investigation, told as: what Dallal found -> who it asked -> what changed -> what it did. */
export function InvestigationStory({ runId, valueSar }: { runId: string; valueSar: number }) {
  const run = useOps((s) => s.runs[runId]);
  const driverName = useOps((s) => s.drivers[s.parcels[s.runs[runId]?.ui.shipmentId ?? ""]?.driverId ?? ""]?.name);
  const parcelState = useOps((s) => s.parcels[run?.ui.shipmentId ?? ""]);
  const revealed = useOpsUi((s) => s.revealed[runId] ?? 0);
  const busy = useOpsUi((s) => s.busy);
  const f = run ? findings(run) : [];
  const ask = run ? askStep(run) : undefined;
  const done = !!run && run.status !== "awaiting_response";
  const total = f.length + (ask ? 1 : 0) + (done ? 2 : 0);

  useEffect(() => {
    if (!run || revealed >= total) return;
    const t = setTimeout(() => setUi({ revealed: { ...getUi().revealed, [runId]: revealed + 1 } }), revealed === 0 ? 300 : 650);
    return () => clearTimeout(t);
  }, [run, revealed, total, runId]);

  const planStatus = useOps((s) => (s.active?.planId ? s.plans[s.active.planId]?.status : undefined));
  const tail = useRef<HTMLDivElement>(null);
  const follow = `${revealed}:${run?.status}:${run?.inquiries[0]?.status}:${planStatus}:${parcelState?.state}`;
  useEffect(() => {
    const t = setTimeout(() => tail.current?.scrollIntoView({ behavior: "smooth", block: "end" }), 120);
    return () => clearTimeout(t);
  }, [follow]);

  if (!run) return null;
  const shownFindings = f.slice(0, revealed);
  const askShown = !!ask && revealed > f.length;
  const beliefShown = done && revealed > f.length + (ask ? 1 : 0);
  const decisionShown = done && revealed >= total;
  const inq = inquiryFor(run);
  const bs = beliefStory(run);
  const thinking = revealed < total;
  return (
    <div className="relative space-y-5">
      <span className="absolute top-3 bottom-3 left-3 w-px bg-line" aria-hidden />
      <Stage n={2} title="What Dallal found">
        <ul className="space-y-1.5">
          {shownFindings.map((x) => (
            <li key={x.id} className="animate-fade-in rounded-lg bg-subtle px-3 py-2 text-xs ring-1 ring-line-soft">
              <div className="flex items-start gap-2">
                <span className={cn("mt-1 size-2 shrink-0 rounded-full", DOT[x.tone])} aria-hidden />
                <div className="min-w-0">
                  <p className="text-ink">
                    <b className="font-semibold">{x.label}:</b> <span className={x.tone === "ok" ? "" : TONE[x.tone]}>{x.text}</span>
                  </p>
                  {x.detail && (x.tone !== "ok" || x.tool === "predict_risk") ? <p className="mt-0.5 text-ink-3">{x.detail}</p> : null}
                </div>
              </div>
            </li>
          ))}
          {thinking && !beliefShown ? (
            <li className="flex items-center gap-2 px-1 text-xs text-ink-3">
              <Loader2 className="size-3.5 animate-spin" aria-hidden /> Dallal is checking the records…
            </li>
          ) : null}
        </ul>
      </Stage>

      {askShown || (done && !ask) ? (
        <Stage n={3} title={ask ? "Who it asked, and why" : "Did it need to ask anyone?"}>
          {ask && inq ? (
            <div className="space-y-2">
              <p className="text-xs leading-5 text-ink-2">
                The records could not settle it, and the answer was expected to change the best action. Dallal asked <b>{inq.target === "courier" && driverName ? `${driverName}, the driver` : (WHO[inq.target] ?? inq.target)}</b> - the person who can see it - because a
                reply is quick and costs little.
                {inq.net_voi != null ? <span className="text-ink-3"> Worth asking: +{inq.net_voi.toFixed(1)} SAR-eq net, {Math.round((inq.p_response ?? 0) * 100)}% chance of a reply.</span> : null}
              </p>
              <ReplyDevice inquiry={inq} run={runId} suggested="at_address_no_answer" who={inq.target === "courier" && driverName ? driverName : undefined} />
            </div>
          ) : (
            <p className="text-xs leading-5 text-ink-2">
              <b>No.</b> The records were enough, so Dallal asked nobody.
              {(() => {
                const q = bestUnaskedQuestion(run.decision);
                return q ? <span className="text-ink-3"> The best question it considered was not worth its cost (net {q.net.toFixed(1)} SAR-eq).</span> : null;
              })()}
            </p>
          )}
        </Stage>
      ) : null}

      {beliefShown && bs.before && bs.after ? (
        <Stage n={4} title={bs.asked ? "What the answer changed" : "What Dallal concluded"}>
          <div className="flex gap-4 rounded-lg bg-subtle px-3 py-2.5 ring-1 ring-line-soft">
            {bs.asked ? <BeliefBars top={bs.before.top} label="Before the question" /> : null}
            {bs.asked ? <span className="self-center text-ink-4">→</span> : null}
            <BeliefBars top={bs.after.top} label={bs.asked ? "After the reply" : "Most likely cause"} />
          </div>
        </Stage>
      ) : null}

      {decisionShown ? (
        <Stage n={5} title="Decision and action">
          <DecisionBlock run={run} valueSar={valueSar} busy={busy === "execute"} stateLabel={parcelState?.headline} />
        </Stage>
      ) : null}
      <div ref={tail} aria-hidden />
    </div>
  );
}

function ChecksList({ run, valueSar }: { run: RunRecord; valueSar: number }) {
  const checks = safetyChecks(run.decision, valueSar);
  return (
    <ul className="grid gap-x-3 gap-y-1 sm:grid-cols-2">
      {checks.map((c) => (
        <li key={c.label} className="flex items-start gap-1.5 text-xs text-ink-2">
          {c.pass ? <Check className="mt-0.5 size-3.5 shrink-0 text-ok-600" aria-hidden /> : <X className="mt-0.5 size-3.5 shrink-0 text-crit-600" aria-hidden />}
          <span className={c.pass ? "" : "font-medium text-crit-700"}>{c.label}</span>
        </li>
      ))}
    </ul>
  );
}

function DecisionBlock({ run, valueSar, busy, stateLabel }: { run: RunRecord; valueSar: number; busy: boolean; stateLabel?: string }) {
  const type = run.decision.type as string;
  const title = String(run.decision.action_title ?? run.decision.headline ?? "");
  const parcelId = run.ui.shipmentId;
  const p = useOps((s) => s.parcels[parcelId]);
  const plan = useOps((s) => (s.active?.planId ? s.plans[s.active.planId] : undefined));
  const active = useOps((s) => s.active);
  const affectedCount = useOps((s) => Object.values(s.parcels).filter((q) => q.exception && q.incident).length);

  if (type === "auto_eligible") {
    const sent = p?.state === "recovering" || p?.state === "prevented" || p?.state === "recovered";
    return (
      <div className="space-y-2.5 rounded-xl border border-ok-200 bg-ok-50 p-3.5">
        <div className="flex items-center gap-2">
          <Bot className="size-4 text-ok-700" aria-hidden />
          <b className="text-13 text-ok-700">Dallal resolved this on its own</b>
          <span className="ml-auto rounded-full bg-white px-2 py-0.5 text-[11px] font-medium text-ok-700 ring-1 ring-ok-200">No manager needed</span>
        </div>
        <p className="text-13 text-ink">{title}</p>
        <p className="flex items-center gap-1.5 text-xs text-ink-2">
          {busy && !sent ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Check className="size-3.5 text-ok-600" aria-hidden />}
          {sent ? stateLabel : busy ? "Sending…" : "Ready"}{" "}
          {p?.state === "recovering" ? <span className="text-ink-3">· sent in the sandbox, waiting for the customer</span> : null}
        </p>
        {p?.simOutcome ? <p className="rounded-md bg-white px-2.5 py-1.5 text-xs text-ok-700 ring-1 ring-ok-200">Outcome in the simulated world: {p.simOutcome.label}.</p> : null}
        <div>
          <p className="mb-1 flex items-center gap-1 text-[11px] font-semibold tracking-[0.05em] text-ink-3 uppercase">
            <ShieldCheck className="size-3.5" aria-hidden /> Why no manager was needed
          </p>
          <ChecksList run={run} valueSar={valueSar} />
        </div>
        <p className="text-[11px] text-ink-3">Executed in simulation · WhatsApp is sandbox only · the outcome is observed afterwards, never assumed.</p>
      </div>
    );
  }
  if (type === "recommend") {
    return (
      <div className="space-y-2.5 rounded-xl border border-brand-200 bg-brand-25 p-3.5">
        <div className="flex items-center gap-2">
          <UserRoundSearch className="size-4 text-brand-700" aria-hidden />
          <b className="text-13 text-brand-700">Dallal recommends - an operator confirms</b>
        </div>
        <p className="text-13 text-ink">{title}</p>
        <ChecksList run={run} valueSar={valueSar} />
        {p?.state === "recovering" || p?.state === "prevented" || p?.state === "recovered" ? (
          <p className="text-xs text-ok-700">Confirmed and sent (simulated). {p.simOutcome ? `Outcome: ${p.simOutcome.label}.` : "Waiting for the customer."}</p>
        ) : (
          <Button variant="primary" loading={busy} onClick={() => executeRun(run.ui.id, "Desk operator", "analyst")}>
            Confirm as operator
          </Button>
        )}
      </div>
    );
  }
  if (type === "escalate") {
    return (
      <div className="space-y-2 rounded-xl border border-review-200 bg-review-50 p-3.5">
        <div className="flex items-center gap-2">
          <TriangleAlert className="size-4 text-review-700" aria-hidden />
          <b className="text-13 text-review-700">Dallal is escalating to the manager</b>
        </div>
        <p className="text-xs leading-5 text-ink-2">{String(run.decision.rationale ?? "")}</p>
        {run.decision.question ? <p className="text-xs text-ink-2"><b>Question for the manager:</b> {String(run.decision.question)}</p> : null}
        <Button size="sm" variant="review" onClick={() => setUi({ role: "manager" })}>
          Open manager view
        </Button>
      </div>
    );
  }
  if (type === "incident") {
    return (
      <div className="space-y-3">
        <div className="rounded-xl border border-crit-200 bg-crit-50 p-3.5">
          <div className="flex items-center gap-2">
            <TriangleAlert className="size-4 text-crit-700" aria-hidden />
            <b className="text-13 text-crit-700">One disruption is behind several delays</b>
          </div>
          <p className="mt-1 text-xs leading-5 text-ink-2">{incidentSentence(String(run.decision.rationale ?? ""), affectedCount, active?.affectedDriverIds.length ?? 0, active?.exposedParcelIds.length ?? 0)} Dallal stops treating them one by one and plans them together.</p>
        </div>
        {active?.planId && plan ? <PlanCard planId={active.planId} mode="operator" /> : <p className="flex items-center gap-2 text-xs text-ink-3"><Loader2 className="size-3.5 animate-spin" aria-hidden /> Building the coordinated plan…</p>}
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-line bg-subtle p-3.5">
      <div className="flex items-center gap-2">
        <CircleHelp className="size-4 text-ink-3" aria-hidden />
        <b className="text-13 text-ink">{String(run.decision.headline ?? "No action needed")}</b>
      </div>
      <p className="mt-1 text-xs text-ink-2">{String(run.decision.rationale ?? "Dallal keeps watching this parcel.")}</p>
    </div>
  );
}

/** Optional technical view: the trace behind the story, for judges who ask "how does it know?". */
export function TechnicalDetails({ runId }: { runId: string }) {
  const run = useOps((s) => s.runs[runId]);
  const open = useOpsUi((s) => s.detailsOpen);
  if (!run) return null;
  const d = run.decision;
  return (
    <div className="rounded-xl border border-line bg-surface">
      <button type="button" onClick={() => setUi({ detailsOpen: !open })} className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-xs font-medium text-ink-2" aria-expanded={open}>
        Technical details <span className="font-normal text-ink-4">(trace, probabilities, policy)</span>
        <ChevronDown className={cn("ml-auto size-4 text-ink-4 transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open ? (
        <div className="space-y-3 border-t border-line-soft px-3.5 py-3 text-xs text-ink-2">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            <span>Engine</span><span className="text-ink">{run.ui.backend?.engine} · planner {run.ui.backend?.planner}</span>
            <span>Decision type</span><span className="text-ink">{String(d.type)} · policy {String(d.policy_version ?? "")}</span>
            <span>Top cause</span><span className="text-ink">{CAUSE[String(d.top_cause)] ?? String(d.top_cause)} · {typeof d.posterior === "number" ? pct(d.posterior) : "-"}</span>
            <span>Unexplained share</span><span className="text-ink">{typeof d.p_unknown === "number" ? pct(d.p_unknown) : "-"}</span>
            <span>Robust effectiveness</span><span className="text-ink">{typeof d.robust_effectiveness === "number" ? pct(d.robust_effectiveness) : "-"}</span>
            <span>Data origin</span><span className="text-ink">{run.ui.backend?.data_origin ?? "demo"} (simulated, not SPL data)</span>
          </div>
          <div>
            <p className="mb-1 font-semibold text-ink">Steps (net value of information chose each one)</p>
            <ol className="space-y-1">
              {run.ui.steps.map((s) => (
                <li key={s.id} className="rounded-md bg-subtle px-2 py-1.5">
                  <span className="font-mono text-[11px] text-brand-700">{s.backendTool ?? s.tool}</span> <span className="text-ink-3">- {s.summary}</span>
                  {s.checking ? <p className="mt-0.5 text-[11px] text-ink-4">{s.checking}</p> : null}
                </li>
              ))}
            </ol>
          </div>
          {Array.isArray(d.utility_table) ? (
            <div>
              <p className="mb-1 font-semibold text-ink">Options by expected value (SAR-eq)</p>
              <ul className="space-y-0.5">
                {(d.utility_table as { option: string; eu: number; approval: string }[]).slice(0, 5).map((u) => (
                  <li key={u.option} className="flex justify-between"><span>{u.option} <span className="text-ink-4">({u.approval === "none" ? "no approval" : u.approval})</span></span><span className="tabular text-ink">{u.eu.toFixed(1)}</span></li>
                ))}
              </ul>
            </div>
          ) : null}
          <p className="text-[11px] leading-4 text-ink-4">
            Every number comes from the real backend run {run.ui.id}. Likelihoods and costs are expert assumptions (no public SPL outcome data). Steps are shown at a readable pace; the run itself completes in well under a second. The language model never makes this decision: it only suggests how to read an unclear reply, and a person confirms.
          </p>
        </div>
      ) : null}
    </div>
  );
}

