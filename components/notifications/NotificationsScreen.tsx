"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowRight, BellOff, CheckCheck, Mail, Siren, UserRoundCheck } from "lucide-react";
import { people } from "@/data/people";
import { cn } from "@/lib/cn";
import { fmtDate, fmtRelative, fmtTime } from "@/lib/time";
import { useDemoNow } from "@/hooks/useDemoNow";
import { notificationService } from "@/services";
import { simulateSupervisorApproval } from "@/services/demo/supervisorSimulator";
import { useUi } from "@/store/ui";
import { useWorld } from "@/store/world";
import { EmptyState } from "@/components/common/Card";
import { AgentBadge, SeverityBadge, SimTag, StatusBadge } from "@/components/common/Badges";
import { Button } from "@/components/common/Button";
import { hrefFor, NotificationItem } from "@/components/notifications/NotificationItem";
import type { AppNotification, NotificationKind } from "@/types/domain";

const FILTERS: { key: "all" | NotificationKind | "email"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "escalation", label: "Escalations" },
  { key: "incident", label: "Incidents" },
  { key: "risk", label: "Risk & failures" },
  { key: "agent", label: "Agent actions" },
  { key: "approval", label: "Approvals" },
  { key: "outcome", label: "Outcomes" },
  { key: "email", label: "Email log" },
];

export function NotificationsScreen() {
  const raw = useWorld((w) => w.notifications);
  const notifications = useMemo(() => [...raw].sort((a, b) => b.at - a.at), [raw]);
  const emails = useWorld((w) => w.emails);
  const now = useDemoNow(10_000);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const list = useMemo(() => {
    if (filter === "email") return notifications.filter((n) => n.emailId);
    return filter === "all" ? notifications : notifications.filter((n) => n.kind === filter);
  }, [notifications, filter]);
  const selected = notifications.find((n) => n.id === selectedId) ?? list[0];
  const unread = notifications.filter((n) => !n.read).length;

  return (
    <div className="flex h-[calc(100dvh-56px)] min-h-[600px] flex-col gap-3 p-3 lg:p-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[22px] leading-8 font-semibold tracking-[-0.02em] text-ink">Notifications</h1>
          <p className="text-13 text-ink-3">
            {unread} unread · escalations, incidents, agent actions and outcomes · {Object.keys(emails).length} simulated emails
          </p>
        </div>
        <Button size="sm" variant="secondary" onClick={() => notificationService.markAllRead()} disabled={!unread}>
          <CheckCheck /> Mark all read
        </Button>
      </header>

      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter notifications">
        {FILTERS.map((f) => {
          const count = f.key === "all" ? notifications.length : f.key === "email" ? notifications.filter((n) => n.emailId).length : notifications.filter((n) => n.kind === f.key).length;
          return (
            <button
              key={f.key}
              role="tab"
              aria-selected={filter === f.key}
              onClick={() => {
                setFilter(f.key);
                setSelectedId(null);
              }}
              className={cn("inline-flex h-8 items-center gap-1.5 rounded-full px-3 text-xs font-medium transition-colors", filter === f.key ? "bg-ink text-white" : "bg-surface text-ink-2 ring-1 ring-line hover:bg-hover")}
            >
              {f.key === "email" ? <Mail className="size-3.5" aria-hidden /> : null}
              {f.label}
              <span className={cn("tabular", filter === f.key ? "text-white/70" : "text-ink-4")}>{count}</span>
            </button>
          );
        })}
      </div>

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[400px_1fr]">
        <section className="min-h-0 overflow-y-auto rounded-xl border border-line bg-surface p-1.5 shadow-card scrollbar-thin" aria-label="Notification list">
          {list.length ? (
            list.map((n) => (
              <NotificationItem
                key={n.id}
                n={n}
                now={now}
                selected={selected?.id === n.id}
                onClick={() => {
                  setSelectedId(n.id);
                  notificationService.markRead(n.id);
                }}
              />
            ))
          ) : (
            <EmptyState icon={<BellOff />} title="Nothing here yet" body="Notifications of this type will appear as the shift unfolds." />
          )}
        </section>
        <section className="min-h-0 overflow-y-auto rounded-xl border border-line bg-surface shadow-card scrollbar-thin" aria-label="Notification detail">
          {selected ? <Detail n={selected} now={now} /> : <EmptyState icon={<BellOff />} title="Select a notification" />}
        </section>
      </div>
    </div>
  );
}

function Detail({ n, now }: { n: AppNotification; now: number }) {
  const set = useUi((s) => s.set);
  const shipment = useWorld((w) => (n.target.type === "shipment" ? w.shipments[n.target.id] : undefined));
  const incident = useWorld((w) => (n.target.type === "incident" ? w.incidents[n.target.id] : undefined));
  const email = useWorld((w) => (n.emailId ? w.emails[n.emailId] : undefined));
  const escalation = useWorld((w) => w.escalations.find((e) => e.target.id === n.target.id && e.status === "awaiting"));
  const [approving, setApproving] = useState(false);

  return (
    <div className="p-5">
      <div className="text-xs text-ink-3">
        {fmtDate(n.at)}, {fmtTime(n.at)} · {fmtRelative(n.at, now)} · {n.actor}
      </div>
      <h2 className="mt-1 text-[18px] leading-7 font-semibold text-ink">{n.title}</h2>
      <p className="mt-1 text-13 text-ink-2">{n.body}</p>

      <div className="mt-4 rounded-xl border border-line p-4">
        <div className="text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">Related {n.target.type}</div>
        {shipment ? (
          <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-15 font-semibold">{shipment.id}</span>
                <StatusBadge health={shipment.health} size="xs" />
              </div>
              <div className="mt-0.5 text-xs text-ink-3">
                {shipment.destination.label} · {shipment.headline ?? shipment.merchant}
              </div>
              <div className="mt-1">
                <AgentBadge state={shipment.agent.state} />
              </div>
            </div>
            <Link href={hrefFor(n)} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-brand-600 px-3.5 text-13 font-medium text-white hover:bg-brand-700">
              Open Shipment Intelligence <ArrowRight className="size-4" />
            </Link>
          </div>
        ) : incident ? (
          <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <Siren className="size-4 text-crit-600" aria-hidden />
                <span className="text-15 font-semibold">{incident.title}</span>
                <SeverityBadge severity={incident.severity} className="h-5 text-2xs" />
              </div>
              <div className="mt-0.5 text-xs text-ink-3">
                {incident.id} · {incident.affected.length} affected · {incident.exposed.length} exposed · {incident.status}
              </div>
            </div>
            <Link href={hrefFor(n)} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-brand-600 px-3.5 text-13 font-medium text-white hover:bg-brand-700">
              Open Incident Intelligence <ArrowRight className="size-4" />
            </Link>
          </div>
        ) : (
          <p className="mt-2 text-xs text-ink-3">This record is no longer in the live session.</p>
        )}
      </div>

      {escalation && n.kind === "escalation" ? (
        <div className="mt-3 rounded-xl border border-review-200 bg-review-50 p-4">
          <div className="flex items-center gap-2 text-13 font-semibold text-review-700">
            <UserRoundCheck className="size-4" /> Awaiting {people.supervisor.name}
          </div>
          <p className="mt-1 text-xs text-ink-2">“{escalation.question}”</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="review"
              loading={approving}
              onClick={async () => {
                setApproving(true);
                await simulateSupervisorApproval(escalation.id);
                setApproving(false);
              }}
            >
              Simulate supervisor approval
            </Button>
            <SimTag label="demo" tip="Stands in for the supervisor approving from their own inbox or phone. Production receives this as a decision event." />
          </div>
        </div>
      ) : null}

      {email ? (
        <div className="mt-3 rounded-xl border border-line bg-subtle p-4">
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-13 font-semibold text-ink">
              <Mail className="size-4 text-ink-3" /> Email notification
              <SimTag label="simulated" tip="Generated preview only — not sent to any real mailbox." />
            </div>
            <Button size="sm" variant="secondary" onClick={() => set({ emailPreviewId: email.id })}>
              Open email preview
            </Button>
          </div>
          <dl className="mt-3 grid grid-cols-[64px_1fr] gap-x-3 gap-y-1 text-xs">
            <dt className="text-ink-4">Subject</dt>
            <dd className="font-medium text-ink">{email.subject}</dd>
            <dt className="text-ink-4">To</dt>
            <dd className="text-ink-2">{email.to}</dd>
            <dt className="text-ink-4">Sent</dt>
            <dd className="text-ink-2">{fmtTime(email.at)} (simulated)</dd>
          </dl>
          <p className="mt-2 line-clamp-2 text-xs text-ink-3">{email.reason}</p>
        </div>
      ) : null}
    </div>
  );
}
