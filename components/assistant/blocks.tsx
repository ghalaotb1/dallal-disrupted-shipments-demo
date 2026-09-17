"use client";

import Link from "next/link";
import { useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ArrowRight, Check, MapPinned, Minus, Siren, Sparkles, UserRoundCheck, X } from "lucide-react";
import { useShallow } from "zustand/react/shallow";
import { places } from "@/data/network";
import { cn } from "@/lib/cn";
import { plural } from "@/lib/format";
import { fmtRelative, fmtTime } from "@/lib/time";
import { useDemoNow } from "@/hooks/useDemoNow";
import { analyzeDisruption } from "@/services/logic/diagnosis";
import { estimateEta } from "@/services/logic/movement";
import { focusMap, useUi } from "@/store/ui";
import { getWorld, useWorld } from "@/store/world";
import { askAssistant } from "@/components/assistant/askAssistant";
import { AgentBadge, PriorityBadge, RiskMeter, SeverityBadge, StatusBadge } from "@/components/common/Badges";
import { HEALTH } from "@/components/common/status";
import { HourlyChart } from "@/components/charts/HourlyChart";
import { RankedBars } from "@/components/charts/RankedBars";
import { RouteProgress } from "@/components/shipments/RouteProgress";
import type { AssistantAction, AssistantBlock } from "@/types/assistant";

export function BlockView({ block }: { block: AssistantBlock }) {
  switch (block.type) {
    case "kpis":
      return <KpiBlock items={block.items} />;
    case "shipment":
      return <ShipmentBlock id={block.id} />;
    case "shipment_list":
      return <ShipmentListBlock title={block.title} ids={block.ids} empty={block.empty} />;
    case "timeline":
      return <TimelineBlock id={block.id} limit={block.limit ?? 4} />;
    case "evidence":
      return <EvidenceBlock id={block.id} />;
    case "incident":
      return <IncidentBlock id={block.id} />;
    case "hourly_chart":
      return (
        <Frame title={block.title}>
          <HourlyChart data={block.data} />
        </Frame>
      );
    case "bar_chart":
      return (
        <Frame title={block.title}>
          <RankedBars data={block.data} unit={block.unit} />
        </Frame>
      );
    case "agent_trace":
      return <AgentTraceBlock runId={block.runId} />;
    case "approvals":
      return <ApprovalsBlock items={block.items} />;
    case "actions":
      return <ActionsBlock actions={block.actions} />;
    case "note":
      return <p className="rounded-lg bg-subtle px-3 py-2 text-xs text-ink-3">{block.text}</p>;
  }
}

function Frame({ title, children, className }: { title?: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-xl border border-line bg-surface p-3", className)}>
      {title ? <div className="mb-2 text-xs font-semibold text-ink-2">{title}</div> : null}
      {children}
    </div>
  );
}

function KpiBlock({ items }: { items: Extract<AssistantBlock, { type: "kpis" }>["items"] }) {
  const dot = { neutral: "bg-ink-4", ok: "bg-ok-500", warn: "bg-warn-500", crit: "bg-crit-500", review: "bg-review-500" };
  return (
    <div className="grid grid-cols-3 gap-2">
      {items.map((k) => (
        <div key={k.label} className="rounded-xl border border-line bg-surface px-3 py-2">
          <div className="flex items-center gap-1.5 text-2xs text-ink-3">
            <span className={cn("size-1.5 rounded-full", dot[k.tone ?? "neutral"])} aria-hidden />
            <span className="truncate">{k.label}</span>
          </div>
          <div className="mt-0.5 text-[20px] leading-7 font-semibold tracking-[-0.02em] text-ink">{k.value}</div>
        </div>
      ))}
    </div>
  );
}

function ShipmentBlock({ id }: { id: string }) {
  const s = useWorld((w) => w.shipments[id]);
  const now = useDemoNow(2000);
  if (!s) return null;
  const eta = estimateEta(s, now);
  return (
    <Link href={`/shipments/${s.id}`} className="block rounded-xl border border-line bg-surface p-3 transition-shadow hover:shadow-float">
      <div className="flex items-center gap-2">
        <span className="font-mono text-13 font-semibold text-ink">{s.id}</span>
        <StatusBadge health={s.health} size="xs" />
        <PriorityBadge priority={s.priority} />
        <span className="ml-auto text-xs text-ink-3 tabular">{s.closed ? "Closed" : eta ? `ETA ${fmtTime(eta)}` : ""}</span>
      </div>
      <div className="mt-1 truncate text-xs text-ink-3">
        {places[s.originId].short} → {s.destination.label}
      </div>
      {s.headline ? <div className={cn("mt-1 line-clamp-2 text-xs font-medium", HEALTH[s.health].text)}>{s.headline}</div> : null}
      <RouteProgress s={s} now={now} className="mt-2" />
      <div className="mt-2 flex items-center justify-between">
        <RiskMeter risk={s.risk} />
        <AgentBadge state={s.agent.state} />
      </div>
    </Link>
  );
}

function ShipmentListBlock({ title, ids, empty }: { title: string; ids: string[]; empty?: string }) {
  const shipments = useWorld(useShallow((w) => ids.map((id) => w.shipments[id]).filter(Boolean)));
  return (
    <Frame title={title} className="p-0 pt-3">
      <div className="px-3">{!shipments.length ? <p className="pb-3 text-xs text-ink-3">{empty ?? "Nothing to show."}</p> : null}</div>
      <ul className="divide-y divide-line-soft">
        {shipments.map((s) => (
          <li key={s.id}>
            <Link href={`/shipments/${s.id}`} className="flex items-center gap-2 px-3 py-2 hover:bg-hover">
              <span className="font-mono text-xs font-semibold text-ink">{s.id}</span>
              <StatusBadge health={s.health} size="xs" />
              <span className="min-w-0 flex-1 truncate text-xs text-ink-3">{s.headline ?? s.destination.label}</span>
              <ArrowRight className="size-3.5 shrink-0 text-ink-4" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
    </Frame>
  );
}

function TimelineBlock({ id, limit }: { id: string; limit: number }) {
  const events = useWorld((w) => w.journeys[id]);
  const recent = useMemo(() => [...(events ?? [])].sort((a, b) => b.at - a.at).slice(0, limit), [events, limit]);
  const tone = { neutral: "bg-ink-4", info: "bg-brand-500", ok: "bg-ok-500", warn: "bg-warn-500", crit: "bg-crit-500", review: "bg-review-500", agent: "bg-brand-600" };
  return (
    <Frame title="Recent journey events">
      <ol className="space-y-1.5">
        {recent.map((e) => (
          <li key={e.id} className="flex items-start gap-2 text-xs">
            <span className="w-9 shrink-0 text-ink-3 tabular">{fmtTime(e.at)}</span>
            <span className={cn("mt-1.5 size-1.5 shrink-0 rounded-full", tone[e.tone])} aria-hidden />
            <span className="text-ink-2">{e.title}</span>
          </li>
        ))}
      </ol>
    </Frame>
  );
}

function EvidenceBlock({ id }: { id: string }) {
  const s = useWorld((w) => w.shipments[id]);
  const ctx = useWorld((w) => w.contexts[id]);
  const now = useDemoNow(30_000);
  const d = useMemo(() => {
    if (!s || !ctx) return null;
    const w = getWorld();
    return analyzeDisruption({ shipment: s, context: ctx, now, corridorPeers: Object.values(w.shipments).filter((p) => p.corridorId === s.corridorId && !p.closed) });
  }, [s, ctx, now]);
  if (!d) return null;
  const icon = { supports: Check, contradicts: X, context: Minus };
  const cls = { supports: "bg-ok-50 text-ok-600", contradicts: "bg-crit-50 text-crit-600", context: "bg-muted text-ink-3" };
  return (
    <Frame title={`Evidence · ${d.causeLabel} (confidence ${d.confidence})`}>
      <ul className="space-y-1.5">
        {d.evidence.slice(0, 5).map((e) => {
          const I = icon[e.stance];
          return (
            <li key={e.id} className="flex items-start gap-2 text-xs">
              <span className={cn("mt-px flex size-4 shrink-0 items-center justify-center rounded-full", cls[e.stance])}>
                <I className="size-2.5" strokeWidth={3} aria-label={e.stance} />
              </span>
              <span>
                <span className="font-medium text-ink">{e.label}</span> <span className="text-ink-3">— {e.detail}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </Frame>
  );
}

function IncidentBlock({ id }: { id: string }) {
  const inc = useWorld((w) => w.incidents[id]);
  const now = useDemoNow(15_000);
  if (!inc) return null;
  return (
    <div className={cn("rounded-xl border bg-surface p-3", inc.status === "active" ? "border-crit-200" : "border-line")}>
      <div className="flex items-start gap-2.5">
        <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-lg text-white", inc.status === "resolved" ? "bg-ok-600" : inc.severity === "medium" ? "bg-warn-500" : "bg-crit-600")}>
          <Siren className="size-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-13 font-semibold text-ink">{inc.title}</span>
            <SeverityBadge severity={inc.severity} className="h-5 text-2xs" />
          </div>
          <div className="text-xs text-ink-3">
            {inc.id} · {inc.status} · detected {fmtRelative(inc.detectedAt, now)}
          </div>
          <div className="mt-1 text-xs text-ink-2">
            <span className="font-semibold text-ink">{plural(inc.affected.length, "failure")}</span> grouped · {inc.exposed.length} exposed · {inc.subtitle}
          </div>
        </div>
      </div>
      <div className="mt-2.5 flex items-center justify-between">
        <FocusIncidentButton id={inc.id} />
        <Link href={`/incidents/${inc.id}`} className="inline-flex items-center gap-1 text-xs font-semibold text-brand-700 hover:underline">
          Open incident <ArrowRight className="size-3.5" />
        </Link>
      </div>
    </div>
  );
}

function AgentTraceBlock({ runId }: { runId: string }) {
  const run = useWorld((w) => w.agentRuns[runId]);
  if (!run) return null;
  return (
    <Frame title={`${run.mode === "execution" ? "Action execution" : "Investigation"} · ${fmtTime(run.startedAt)} · ${plural(run.steps.length, "tool call")}`}>
      <div className="flex flex-wrap items-center gap-1 font-mono text-[10.5px]">
        {run.steps.map((st, i) => (
          <span key={st.id} className="flex items-center gap-1">
            <span className={cn("rounded px-1 py-px", st.status === "alert" ? "bg-crit-50 text-crit-700" : st.status === "warn" ? "bg-warn-50 text-warn-700" : "bg-muted text-ink-2")}>{st.tool}</span>
            {i < run.steps.length - 1 ? <ArrowRight className="size-3 text-ink-5" aria-hidden /> : null}
          </span>
        ))}
      </div>
      {run.outcome ? (
        <p className="mt-2 text-xs text-ink-2">
          <Sparkles className="mr-1 inline size-3.5 text-brand-500" aria-hidden />
          <span className="font-semibold text-ink">{run.outcome.headline}</span>
        </p>
      ) : null}
    </Frame>
  );
}

function ApprovalsBlock({ items }: { items: Extract<AssistantBlock, { type: "approvals" }>["items"] }) {
  const now = useDemoNow(15_000);
  if (!items.length) return null;
  return (
    <Frame title="Waiting on the shift supervisor" className="p-0 pt-3">
      <ul className="divide-y divide-line-soft">
        {items.map((it) => (
          <li key={it.id}>
            <Link href={it.target.type === "shipment" ? `/shipments/${it.target.id}` : `/incidents/${it.target.id}`} className="flex items-start gap-2.5 px-3 py-2.5 hover:bg-hover">
              <UserRoundCheck className="mt-0.5 size-4 shrink-0 text-review-600" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block text-xs font-semibold text-ink">{it.title}</span>
                <span className="line-clamp-2 block text-xs text-ink-3">{it.detail}</span>
              </span>
              <span className="shrink-0 text-2xs text-ink-4">{fmtRelative(it.since, now)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </Frame>
  );
}

function useMapNavigation() {
  const router = useRouter();
  const pathname = usePathname();
  return (target: { kind: "shipment"; id: string } | { kind: "incident"; id: string }) => {
    useUi.setState({ assistantOpen: false, statusFilter: "all", ...(target.kind === "shipment" ? { selectedShipmentId: target.id, selectedFacilityId: null } : { selectedShipmentId: null }) });
    if (pathname !== "/") router.push("/");
    setTimeout(() => focusMap(target), pathname !== "/" ? 450 : 50);
  };
}

function FocusIncidentButton({ id }: { id: string }) {
  const go = useMapNavigation();
  return (
    <button onClick={() => go({ kind: "incident", id })} className="inline-flex items-center gap-1 text-xs font-medium text-ink-2 hover:text-ink">
      <MapPinned className="size-3.5" /> Show on map
    </button>
  );
}

function ActionsBlock({ actions }: { actions: AssistantAction[] }) {
  const router = useRouter();
  const go = useMapNavigation();
  return (
    <div className="flex flex-wrap gap-1.5">
      {actions.map((a, i) => {
        const primary = i === 0;
        const cls = cn(
          "inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium transition-colors",
          primary ? "bg-brand-600 text-white hover:bg-brand-700" : "bg-surface text-ink-2 ring-1 ring-line hover:bg-hover",
        );
        const run = () => {
          switch (a.kind) {
            case "focus_shipment":
              return go({ kind: "shipment", id: a.id });
            case "focus_incident":
              return go({ kind: "incident", id: a.id });
            case "open_shipment":
              return router.push(`/shipments/${a.id}`);
            case "open_incident":
              return router.push(`/incidents/${a.id}`);
            case "open_page":
              return router.push(a.href);
            case "ask":
              return askAssistant(a.prompt);
          }
        };
        const label = a.label ?? (a.kind === "open_incident" ? `Open ${a.id}` : a.kind === "ask" ? a.prompt : "Open");
        return (
          <button key={`${a.kind}-${i}`} onClick={run} className={cls}>
            {a.kind.startsWith("focus") ? <MapPinned className="size-3.5" aria-hidden /> : null}
            {label}
          </button>
        );
      })}
    </div>
  );
}
