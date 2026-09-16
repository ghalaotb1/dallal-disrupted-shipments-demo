"use client";

import { Bot, Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";
import { HEALTH, RISK, SEVERITY } from "@/components/common/status";
import { Tooltip } from "@/components/common/Tooltip";
import type { AgentState, Priority, RiskAssessment, Severity, ShipmentHealth } from "@/types/domain";

export function StatusBadge({ health, size = "sm", className }: { health: ShipmentHealth; size?: "xs" | "sm"; className?: string }) {
  const h = HEALTH[health];
  const Icon = h.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full font-medium whitespace-nowrap ring-1 ring-inset",
        size === "xs" ? "h-5 px-1.5 text-2xs [&_svg]:size-3" : "h-[22px] px-2 text-xs [&_svg]:size-3.5",
        h.chip,
        className,
      )}
    >
      <Icon aria-hidden strokeWidth={2.25} />
      {h.label}
    </span>
  );
}

export function PriorityBadge({ priority, className }: { priority: Priority; className?: string }) {
  const style = priority === "P1" ? "bg-ink text-white" : priority === "P2" ? "bg-ink-5/40 text-ink" : "bg-muted text-ink-3";
  return (
    <Tooltip content={priority === "P1" ? "Priority 1 — decide now" : priority === "P2" ? "Priority 2 — decide this hour" : "Priority 3 — monitoring"}>
      <span className={cn("inline-flex h-5 items-center rounded-md px-1.5 font-mono text-2xs font-semibold tabular", style, className)}>{priority}</span>
    </Tooltip>
  );
}

export function RiskMeter({ risk, showLabel = true, className }: { risk: RiskAssessment; showLabel?: boolean; className?: string }) {
  const r = RISK[risk.level];
  return (
    <Tooltip
      content={
        <div className="max-w-60">
          <div className="font-medium">Risk {risk.score} · {r.label}</div>
          <div className="mt-0.5 text-ink-4">Prototype heuristic on simulated signals — replaced by the trained model next phase.</div>
        </div>
      }
    >
      <span className={cn("inline-flex items-center gap-1.5", className)}>
        <span className="flex items-center gap-[2px]" aria-hidden>
          {[0, 1, 2, 3].map((i) => (
            <span key={i} className={cn("h-2.5 w-1 rounded-[1px]", i < r.segments ? r.bar : "bg-line")} />
          ))}
        </span>
        <span className={cn("text-xs font-medium tabular", r.text)}>
          {risk.score}
          {showLabel ? <span className="ml-1 font-normal text-ink-3">{r.label}</span> : null}
        </span>
      </span>
    </Tooltip>
  );
}

const AGENT_COPY: Record<AgentState, { label: string; tone: string; spin?: boolean }> = {
  monitoring: { label: "Monitoring", tone: "text-ink-3" },
  investigating: { label: "Investigating", tone: "text-brand-700", spin: true },
  recommendation: { label: "Recommendation ready", tone: "text-brand-700" },
  auto_eligible: { label: "Can act automatically", tone: "text-ok-700" },
  acting: { label: "Acting", tone: "text-brand-700", spin: true },
  awaiting_supervisor: { label: "Awaiting supervisor", tone: "text-review-700" },
  incident: { label: "Handled via incident", tone: "text-crit-700" },
  resolved: { label: "Resolved", tone: "text-ok-700" },
};

export function AgentBadge({ state, className }: { state: AgentState; className?: string }) {
  const a = AGENT_COPY[state];
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs font-medium whitespace-nowrap", a.tone, className)}>
      {a.spin ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <Bot className="size-3.5" aria-hidden />}
      <span>
        <span className="sr-only">Agent: </span>
        {a.label}
      </span>
    </span>
  );
}

export function SeverityBadge({ severity, className }: { severity: Severity; className?: string }) {
  const s = SEVERITY[severity];
  return <span className={cn("inline-flex h-[22px] items-center gap-1.5 rounded-full px-2 text-xs font-semibold ring-1 ring-inset", s.chip, className)}>{s.label}</span>;
}

/** Marks simulated / prototype values so judges never mistake them for model output. */
export function SimTag({ className, label = "SIM", tip }: { className?: string; label?: string; tip?: string }) {
  return (
    <Tooltip content={tip ?? "Simulated scenario data for this prototype. Roads and places are real; shipments, events and scores are not."}>
      <span
        className={cn(
          "inline-flex h-4 cursor-help items-center rounded border border-dashed border-ink-5 px-1 font-mono text-[9.5px] font-semibold tracking-wide text-ink-3 uppercase",
          className,
        )}
      >
        {label}
      </span>
    </Tooltip>
  );
}

export function Kbd({ children, className }: { children: React.ReactNode; className?: string }) {
  return <kbd className={cn("inline-flex h-5 min-w-5 items-center justify-center rounded border border-line bg-subtle px-1 font-sans text-2xs font-medium text-ink-3", className)}>{children}</kbd>;
}
