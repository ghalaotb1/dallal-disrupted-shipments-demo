"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, LayoutGroup, motion, useReducedMotion } from "motion/react";
import { DropdownMenu } from "radix-ui";
import { ArrowDownUp, ArrowRight, Check, ChevronDown, ChevronRight, MapPinned, Search, Siren, X } from "lucide-react";
import { places } from "@/data/network";
import { cn } from "@/lib/cn";
import { plural } from "@/lib/format";
import { fmtRelative, fmtTime } from "@/lib/time";
import { useDemoNow } from "@/hooks/useDemoNow";
import { useActiveShipments, useIncidents } from "@/hooks/useWorldData";
import { compareByPriority } from "@/services/logic/priority";
import { estimateEta } from "@/services/logic/movement";
import { focusMap, useUi, type StatusFilter } from "@/store/ui";
import { AgentBadge, PriorityBadge, SeverityBadge, StatusBadge } from "@/components/common/Badges";
import { HEALTH, SEVERITY } from "@/components/common/status";
import { EmptyState } from "@/components/common/Card";
import { RouteProgress } from "@/components/shipments/RouteProgress";
import type { Incident, Shipment } from "@/types/domain";

type Sort = "priority" | "risk" | "sla";
const SORTS: Record<Sort, { label: string; fn: (a: Shipment, b: Shipment) => number }> = {
  priority: { label: "Priority", fn: compareByPriority },
  risk: { label: "Risk score", fn: (a, b) => b.risk.score - a.risk.score },
  sla: { label: "SLA deadline", fn: (a, b) => a.slaDeadline - b.slaDeadline },
};
const FILTER_LABEL: Record<StatusFilter, string> = { all: "All active", at_risk: "At risk", disrupted: "Disrupted", review: "Human review", incidents: "Incidents" };

export function PriorityQueue() {
  const shipments = useActiveShipments();
  const incidents = useIncidents();
  const filter = useUi((s) => s.statusFilter);
  const selectedId = useUi((s) => s.selectedShipmentId);
  const set = useUi((s) => s.set);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>("priority");
  const [showOnTrack, setShowOnTrack] = useState(false);
  const now = useDemoNow(5000);

  const openIncidents = incidents.filter((i) => i.status !== "resolved");
  const grouped = useMemo(() => new Set(openIncidents.flatMap((i) => [...i.affected, ...i.exposed])), [openIncidents]);

  const q = query.trim().toLowerCase();
  const matches = (s: Shipment) => !q || `${s.id} ${s.destination.label} ${s.merchant} ${s.corridorId} ${places[s.originId].short}`.toLowerCase().includes(q);

  const sections = useMemo(() => {
    const list = shipments.filter(matches).sort(SORTS[sort].fn);
    const byFilter = (s: Shipment) =>
      filter === "all" ||
      (filter === "at_risk" && s.health === "at_risk") ||
      (filter === "disrupted" && s.health === "disrupted") ||
      (filter === "review" && (s.health === "review" || s.agent.state === "awaiting_supervisor"));
    const pool = filter === "incidents" ? [] : list.filter(byFilter).filter((s) => filter !== "all" || !grouped.has(s.id));
    const decision = pool.filter((s) => s.health === "review" || s.agent.state === "awaiting_supervisor" || (s.health !== "on_track" && (s.agent.state === "recommendation" || s.agent.state === "auto_eligible")));
    const rest = pool.filter((s) => !decision.includes(s));
    return {
      incidents: filter === "all" || filter === "incidents" ? openIncidents.filter((i) => !q || `${i.id} ${i.title}`.toLowerCase().includes(q)) : [],
      decision,
      disrupted: rest.filter((s) => s.health === "disrupted"),
      atRisk: rest.filter((s) => s.health === "at_risk"),
      recovering: rest.filter((s) => s.health === "recovering" || s.health === "recovered" || s.health === "prevented"),
      onTrack: rest.filter((s) => s.health === "on_track"),
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shipments, filter, q, sort, grouped, openIncidents]);

  const attentionCount = sections.decision.length + sections.disrupted.length + sections.atRisk.length;
  const select = (id: string) => {
    set({ selectedShipmentId: id, selectedFacilityId: null });
    focusMap({ kind: "shipment", id });
  };

  return (
    <section className="flex min-h-0 flex-col rounded-xl border border-line bg-surface shadow-card" aria-label="Priority queue">
      <div className="flex items-center justify-between gap-2 px-4 pt-3.5 pb-2">
        <div>
          <h2 className="text-sm font-semibold text-ink">Priority queue</h2>
          <p className="text-xs text-ink-3">
            {sections.incidents.length ? `${plural(sections.incidents.length, "incident")} · ` : ""}
            {plural(attentionCount, "case")} need attention
          </p>
        </div>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button className="inline-flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs font-medium text-ink-2 hover:bg-hover data-[state=open]:bg-muted" aria-label="Sort queue">
              <ArrowDownUp className="size-3.5 text-ink-4" /> {SORTS[sort].label} <ChevronDown className="size-3.5 text-ink-4" />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content align="end" sideOffset={4} className="z-[70] min-w-40 rounded-lg border border-line bg-surface p-1 shadow-pop">
              {(Object.keys(SORTS) as Sort[]).map((k) => (
                <DropdownMenu.Item key={k} onSelect={() => setSort(k)} className="flex cursor-pointer items-center justify-between rounded-md px-2 py-1.5 text-13 text-ink-2 outline-none data-[highlighted]:bg-hover">
                  {SORTS[k].label}
                  {sort === k ? <Check className="size-3.5 text-brand-600" /> : null}
                </DropdownMenu.Item>
              ))}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>

      <div className="space-y-2 px-4 pb-2.5">
        <label className="flex h-8 items-center gap-2 rounded-lg border border-line bg-subtle px-2.5 focus-within:border-brand-300 focus-within:bg-surface focus-within:ring-2 focus-within:ring-brand-100">
          <Search className="size-3.5 text-ink-4" aria-hidden />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter by ID, district, merchant, corridor" className="h-full flex-1 bg-transparent text-13 outline-none placeholder:text-ink-4" aria-label="Filter queue" />
          {query ? (
            <button onClick={() => setQuery("")} aria-label="Clear filter" className="text-ink-4 hover:text-ink-2">
              <X className="size-3.5" />
            </button>
          ) : null}
        </label>
        {filter !== "all" ? (
          <div className="flex items-center gap-2 text-xs text-ink-3">
            Showing
            <button onClick={() => set({ statusFilter: "all" })} className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-2 py-0.5 font-medium text-brand-700 hover:bg-brand-100">
              {FILTER_LABEL[filter]} <X className="size-3" />
            </button>
          </div>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto border-t border-line-soft scrollbar-thin">
        <LayoutGroup>
          {sections.incidents.length ? (
            <QueueSection label="Incidents" count={sections.incidents.length}>
              {sections.incidents.map((inc) => (
                <IncidentGroupCard key={inc.id} incident={inc} now={now} />
              ))}
            </QueueSection>
          ) : null}
          <ShipmentSection label="Needs a decision" list={sections.decision} selectedId={selectedId} onSelect={select} now={now} />
          <ShipmentSection label="Disrupted" list={sections.disrupted} selectedId={selectedId} onSelect={select} now={now} />
          <ShipmentSection label="At risk" list={sections.atRisk} selectedId={selectedId} onSelect={select} now={now} />
          <ShipmentSection label="Recovering" list={sections.recovering} selectedId={selectedId} onSelect={select} now={now} />
          {sections.onTrack.length ? (
            <div className="border-t border-line-soft">
              <button onClick={() => setShowOnTrack((v) => !v)} className="flex w-full items-center justify-between px-4 py-2.5 text-left hover:bg-hover" aria-expanded={showOnTrack}>
                <span className="flex items-center gap-2 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">
                  On track <span className="rounded bg-muted px-1 font-mono tracking-normal text-ink-3 tabular">{sections.onTrack.length}</span>
                </span>
                <ChevronRight className={cn("size-4 text-ink-4 transition-transform", showOnTrack && "rotate-90")} />
              </button>
              {showOnTrack ? (
                <div className="pb-1">
                  {sections.onTrack.map((s) => (
                    <QueueRow key={s.id} s={s} selected={selectedId === s.id} onSelect={select} now={now} compact />
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          {!sections.incidents.length && !attentionCount && !sections.onTrack.length && !sections.recovering.length ? (
            <EmptyState icon={<Search />} title="Nothing matches" body={query ? `No shipments match “${query}”.` : `No shipments are ${FILTER_LABEL[filter].toLowerCase()} right now.`} />
          ) : null}
        </LayoutGroup>
      </div>
    </section>
  );
}

function QueueSection({ label, count, children }: { label: string; count: number; children: React.ReactNode }) {
  return (
    <div className="border-t border-line-soft first:border-t-0">
      <div className="sticky top-0 z-10 flex items-center gap-2 bg-surface/95 px-4 pt-2.5 pb-1.5 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase backdrop-blur-sm">
        {label}
        <span className="rounded bg-muted px-1 font-mono tracking-normal text-ink-3 tabular">{count}</span>
      </div>
      <div className="pb-1.5">{children}</div>
    </div>
  );
}

function ShipmentSection({ label, list, selectedId, onSelect, now }: { label: string; list: Shipment[]; selectedId: string | null; onSelect: (id: string) => void; now: number }) {
  if (!list.length) return null;
  return (
    <QueueSection label={label} count={list.length}>
      <AnimatePresence initial={false}>
        {list.map((s) => (
          <QueueRow key={s.id} s={s} selected={selectedId === s.id} onSelect={onSelect} now={now} />
        ))}
      </AnimatePresence>
    </QueueSection>
  );
}

export function QueueRow({ s, selected, onSelect, now, compact }: { s: Shipment; selected: boolean; onSelect: (id: string) => void; now: number; compact?: boolean }) {
  const router = useRouter();
  const reduce = useReducedMotion();
  const h = HEALTH[s.health];
  const Icon = h.icon;
  const eta = estimateEta(s, now);
  const late = eta && eta > s.slaDeadline;
  return (
    <motion.div
      layout={reduce ? false : "position"}
      layoutId={reduce ? undefined : `queue-${s.id}`}
      initial={{ opacity: 0, backgroundColor: "rgba(237,243,255,1)" }}
      animate={{ opacity: 1, backgroundColor: "rgba(237,243,255,0)" }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.35, backgroundColor: { duration: 1.6 } }}
    >
      <div
        role="button"
        tabIndex={0}
        onClick={() => onSelect(s.id)}
        onDoubleClick={() => router.push(`/shipments/${s.id}`)}
        onKeyDown={(e) => {
          if (e.key === "Enter") router.push(`/shipments/${s.id}`);
          if (e.key === " ") {
            e.preventDefault();
            onSelect(s.id);
          }
        }}
        aria-pressed={selected}
        aria-label={`${s.id}, ${h.label}, priority ${s.priority}. Enter to open.`}
        className={cn(
          "group relative mx-2 my-0.5 cursor-pointer rounded-lg px-2.5 py-2 outline-none focus-visible:ring-2 focus-visible:ring-brand-400",
          selected ? "bg-brand-50 ring-1 ring-brand-200" : "hover:bg-hover",
        )}
      >
        <div className="flex items-center gap-2">
          <Icon className={cn("size-4 shrink-0", h.text)} strokeWidth={2.25} aria-hidden />
          <span className="font-mono text-13 font-semibold text-ink">{s.id}</span>
          {compact ? null : <PriorityBadge priority={s.priority} />}
          <span className="sr-only">{h.label}</span>
          <span className="ml-auto text-xs whitespace-nowrap text-ink-3 tabular">
            {s.movement.mode === "facility" ? "At facility" : eta ? (
              <>
                ETA <span className={cn("font-medium", late ? "text-crit-600" : "text-ink-2")}>{fmtTime(eta)}</span>
              </>
            ) : null}
          </span>
        </div>
        <div className="mt-0.5 truncate pl-6 text-xs text-ink-3">
          {places[s.originId].short} → {s.destination.label}
        </div>
        {!compact && s.headline ? <div className={cn("mt-1 line-clamp-1 pl-6 text-xs font-medium", h.text)}>{s.headline}</div> : null}
        {!compact ? (
          <div className="mt-1.5 flex items-center gap-3 pl-6">
            <RouteProgress s={s} now={now} className="flex-1" />
            <AgentBadge state={s.agent.state} />
          </div>
        ) : null}
        {selected ? (
          <Link href={`/shipments/${s.id}`} onClick={(e) => e.stopPropagation()} className="mt-2 ml-6 inline-flex items-center gap-1 text-xs font-semibold text-brand-700 hover:underline">
            Open Shipment Intelligence <ArrowRight className="size-3.5" />
          </Link>
        ) : null}
      </div>
    </motion.div>
  );
}

function IncidentGroupCard({ incident: inc, now }: { incident: Incident; now: number }) {
  const shipments = useActiveShipments();
  const reduce = useReducedMotion();
  const members = inc.affected.map((id) => shipments.find((s) => s.id === id)).filter(Boolean) as Shipment[];
  const exposed = inc.exposed.length;
  const sev = SEVERITY[inc.severity];
  const active = inc.status === "active";
  return (
    <motion.div layout={reduce ? false : "position"} initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} className="mx-2 my-1">
      <div className={cn("relative overflow-hidden rounded-xl border bg-surface px-3 py-2.5", active ? "border-crit-200 shadow-[0_0_0_3px_rgb(223_59_48/0.06)]" : "border-line")}>
        <span className={cn("absolute inset-y-0 left-0 w-[3px]", sev.dot)} aria-hidden />
        <div className="flex items-start gap-2">
          <Siren className={cn("mt-0.5 size-4 shrink-0", active ? "text-crit-600" : "text-warn-600")} aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-13 font-semibold text-ink">{inc.title}</span>
              <SeverityBadge severity={inc.severity} className="h-5 text-2xs" />
            </div>
            <div className="truncate text-xs text-ink-3">
              {inc.id} · {inc.status === "mitigating" ? "Mitigating" : "Active"} · {fmtRelative(inc.detectedAt, now)}
            </div>
          </div>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-1 pl-6">
          {members.slice(0, 6).map((s) => (
            <motion.span
              key={s.id}
              layoutId={reduce ? undefined : `queue-${s.id}`}
              className={cn("inline-flex h-5 items-center gap-1 rounded-md px-1.5 font-mono text-[10.5px] font-semibold", HEALTH[s.health].chip, "ring-1 ring-inset")}
            >
              {s.id.slice(3)}
            </motion.span>
          ))}
          {members.length > 6 ? <span className="text-2xs text-ink-3">+{members.length - 6}</span> : null}
        </div>
        <div className="mt-1.5 pl-6 text-xs text-ink-2">
          <span className="font-semibold text-ink">{plural(inc.affected.length, "failure")}</span> grouped
          {exposed ? (
            <>
              {" · "}
              <span className="font-semibold text-warn-700">{exposed} exposed</span>
            </>
          ) : null}
        </div>
        <div className="mt-2 flex items-center justify-between pl-6">
          <button onClick={() => focusMap({ kind: "incident", id: inc.id })} className="inline-flex items-center gap-1 text-xs font-medium text-ink-2 hover:text-ink">
            <MapPinned className="size-3.5" /> Show on map
          </button>
          <Link href={`/incidents/${inc.id}`} className="inline-flex items-center gap-1 text-xs font-semibold text-brand-700 hover:underline">
            Open incident <ArrowRight className="size-3.5" />
          </Link>
        </div>
      </div>
    </motion.div>
  );
}

export { StatusBadge };
