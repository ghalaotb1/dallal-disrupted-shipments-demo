"use client";

import { AlertOctagon, BadgeCheck, Bot, Mail, Siren, TriangleAlert, UserRoundCheck, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";
import { fmtRelative } from "@/lib/time";
import type { AppNotification } from "@/types/domain";

const KIND_ICON: Record<AppNotification["kind"], LucideIcon> = {
  escalation: UserRoundCheck,
  incident: Siren,
  agent: Bot,
  outcome: BadgeCheck,
  risk: TriangleAlert,
  approval: BadgeCheck,
};
const TONE: Record<AppNotification["tone"], string> = {
  info: "bg-brand-50 text-brand-600",
  ok: "bg-ok-50 text-ok-600",
  warn: "bg-warn-50 text-warn-600",
  crit: "bg-crit-50 text-crit-600",
  review: "bg-review-50 text-review-600",
};

export function NotificationItem({ n, now, onClick, selected, compact }: { n: AppNotification; now: number; onClick?: () => void; selected?: boolean; compact?: boolean }) {
  const Icon = n.tone === "crit" && n.kind === "risk" ? AlertOctagon : KIND_ICON[n.kind];
  return (
    <button
      onClick={onClick}
      className={cn(
        "group flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors",
        selected ? "bg-brand-50" : "hover:bg-hover",
      )}
    >
      <span className={cn("mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full", TONE[n.tone])}>
        <Icon className="size-3.5" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-start gap-2">
          <span className={cn("flex-1 text-13 leading-5", n.read ? "text-ink-2" : "font-semibold text-ink")}>{n.title}</span>
          {!n.read ? <span className="mt-1.5 size-2 shrink-0 rounded-full bg-brand-500" aria-label="Unread" /> : null}
        </span>
        {compact ? null : <span className="mt-0.5 line-clamp-2 block text-xs text-ink-3">{n.body}</span>}
        <span className="mt-1 flex items-center gap-1.5 text-2xs text-ink-4">
          <span className="tabular">{fmtRelative(n.at, now)}</span>
          <span aria-hidden>·</span>
          <span>{n.actor}</span>
          {n.emailId ? (
            <span className="inline-flex items-center gap-0.5 text-review-600">
              <Mail className="size-3" aria-hidden /> Email (simulated)
            </span>
          ) : null}
        </span>
      </span>
    </button>
  );
}

export const hrefFor = (n: AppNotification) => (n.target.type === "shipment" ? `/shipments/${n.target.id}` : `/incidents/${n.target.id}`);
