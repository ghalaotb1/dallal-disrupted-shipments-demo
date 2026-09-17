"use client";

import Link from "next/link";
import { motion } from "motion/react";
import { ArrowRight, Bot, CircleCheck, Loader2, Mail, ScanSearch, Siren, Sparkles, UserRoundCheck, Zap } from "lucide-react";
import { people } from "@/data/people";
import { cn } from "@/lib/cn";
import { fmtTime } from "@/lib/time";
import { useUi } from "@/store/ui";
import { Button } from "@/components/common/Button";
import { SimTag } from "@/components/common/Badges";
import { simulateSupervisorApproval } from "@/services/demo/supervisorSimulator";
import { useState } from "react";
import type { AgentRun, Escalation, RecoveryAction, Shipment } from "@/types/domain";

type Tone = "neutral" | "brand" | "ok" | "review" | "crit";
const TONE: Record<Tone, { box: string; icon: string }> = {
  neutral: { box: "border-line bg-surface", icon: "bg-muted text-ink-3" },
  brand: { box: "border-brand-200 bg-brand-25", icon: "bg-brand-600 text-white" },
  ok: { box: "border-ok-200 bg-ok-50", icon: "bg-ok-600 text-white" },
  review: { box: "border-review-200 bg-review-50", icon: "bg-review-600 text-white" },
  crit: { box: "border-crit-200 bg-crit-50", icon: "bg-crit-600 text-white" },
};

/** The single "what should I do now" strip — derived from shipment state and the latest agent run. */
export function DecisionBar({
  s,
  investigation,
  running,
  escalation,
  onInvestigate,
  onRun,
  onEscalate,
}: {
  s: Shipment;
  investigation?: AgentRun;
  running?: AgentRun;
  escalation?: Escalation;
  onInvestigate: () => void;
  onRun: (a: RecoveryAction) => void;
  onEscalate: () => void;
}) {
  const set = useUi((x) => x.set);
  const outcome = investigation?.outcome;
  const top = investigation?.actions?.find((a) => outcome && "actionId" in outcome && a.id === outcome.actionId);

  let tone: Tone = "neutral";
  let Icon = Bot;
  let eyebrow = "Dallal Agent";
  let title = "";
  let body = "";
  let actions: React.ReactNode = null;

  if (running) {
    tone = "brand";
    Icon = Loader2;
    const step = running.steps[running.steps.length - 1];
    title = running.mode === "execution" ? "Executing action in the demo environment…" : "Investigating the case…";
    body = step ? `${step.tool}() — ${step.checking}` : "Planning first tool call";
  } else if (s.closed) {
    tone = "ok";
    Icon = CircleCheck;
    eyebrow = "Closed";
    title = s.outcome?.label ?? "Delivered";
    body = "Outcome recorded in the ledger — this is how rankings can learn from real results later.";
  } else if (s.agent.state === "awaiting_supervisor") {
    tone = "review";
    Icon = UserRoundCheck;
    eyebrow = "Human decision pending";
    title = `Awaiting ${people.supervisor.name} · ${people.supervisor.role}`;
    body = escalation ? `Escalated ${fmtTime(escalation.at)} — “${escalation.question}”` : "Escalated for supervisor review.";
    actions = escalation ? (
      <>
        {escalation.emailId ? (
          <Button size="md" variant="secondary" onClick={() => set({ emailPreviewId: escalation.emailId ?? null })}>
            <Mail /> View escalation email
          </Button>
        ) : null}
        {escalation.status === "awaiting" ? <SupervisorSimButton escalationId={escalation.id} /> : null}
      </>
    ) : null;
  } else if (s.health === "prevented" || s.health === "recovered" || s.agent.state === "resolved") {
    tone = "ok";
    Icon = CircleCheck;
    eyebrow = s.health === "prevented" ? "Failure prevented" : "Recovered";
    title = s.headline ?? "Resolved";
    body = "The agent keeps monitoring until delivery.";
  } else if (s.incident && (s.agent.state === "incident" || outcome?.type === "incident")) {
    tone = "crit";
    Icon = Siren;
    eyebrow = "Incident-level handling";
    title = `Part of ${s.incident.id} — fix the shared cause, not this symptom`;
    body = "One group response covers every affected and exposed shipment on the corridor.";
    actions = (
      <Link href={`/incidents/${s.incident.id}`} className="inline-flex h-9 items-center gap-2 rounded-lg bg-crit-600 px-3.5 text-13 font-medium text-white hover:bg-crit-700">
        Open incident <ArrowRight className="size-4" />
      </Link>
    );
  } else if (outcome?.type === "auto_eligible" && top) {
    tone = "ok";
    Icon = Zap;
    eyebrow = "Eligible for automated action";
    title = top.title;
    body = outcome.rationale;
    actions = (
      <Button size="md" variant="primary" onClick={() => onRun(top)}>
        <Zap /> Run automated action
      </Button>
    );
  } else if (outcome?.type === "escalate") {
    tone = "review";
    Icon = UserRoundCheck;
    eyebrow = "Escalation recommended";
    title = outcome.headline;
    body = outcome.rationale;
    actions = (
      <Button size="md" variant="review" onClick={onEscalate}>
        <UserRoundCheck /> Escalate to shift supervisor
      </Button>
    );
  } else if (outcome?.type === "recommend" && top) {
    tone = "brand";
    Icon = Sparkles;
    eyebrow = top.approval === "analyst" ? "Needs your approval" : "Recommendation";
    title = top.title;
    body = outcome.rationale;
    actions = (
      <Button size="md" variant="primary" onClick={() => onRun(top)}>
        {top.approval === "analyst" ? "Approve & run" : "Run action"}
      </Button>
    );
  } else if (s.health === "on_track") {
    tone = "neutral";
    title = "Monitoring — no action needed";
    body = "The shipment is progressing normally. You can still ask the agent to investigate.";
    actions = (
      <Button size="md" variant="secondary" onClick={onInvestigate}>
        <ScanSearch /> Investigate anyway
      </Button>
    );
  } else {
    tone = "brand";
    Icon = Bot;
    eyebrow = "Next step";
    title = s.exception ? "Verify the recorded exception against journey evidence" : "Check this prediction before the courier arrives";
    body = "The agent assembles evidence with tools, diagnoses the likely cause and ranks recovery actions — you stay in control.";
    actions = (
      <Button size="md" variant="primary" onClick={onInvestigate}>
        <Sparkles /> Investigate with agent
      </Button>
    );
  }

  const t = TONE[tone];
  return (
    <motion.section layout="position" className={cn("flex flex-wrap items-center gap-x-4 gap-y-3 rounded-xl border px-4 py-3", t.box)} aria-live="polite" aria-label="Recommended next step">
      <span className={cn("flex size-9 shrink-0 items-center justify-center rounded-lg", t.icon)}>
        <Icon className={cn("size-[18px]", running && "animate-spin")} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-2xs font-semibold tracking-[0.06em] text-ink-3 uppercase">{eyebrow}</div>
        <div className="text-sm font-semibold text-ink">{title}</div>
        <div className="line-clamp-2 text-xs text-ink-2">{body}</div>
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </motion.section>
  );
}

function SupervisorSimButton({ escalationId }: { escalationId: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <span className="flex items-center gap-1.5">
      <Button
        size="md"
        variant="review"
        loading={busy}
        onClick={async () => {
          setBusy(true);
          await simulateSupervisorApproval(escalationId);
          setBusy(false);
        }}
      >
        Simulate supervisor approval
      </Button>
      <SimTag label="demo" tip="Stands in for the supervisor approving from their own inbox or phone." />
    </span>
  );
}
