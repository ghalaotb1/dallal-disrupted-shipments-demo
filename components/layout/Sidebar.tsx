"use client";

import Link from "next/link";
import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { Bell, FlaskConical, Info, LayoutDashboard, Package, PanelLeftClose, PanelLeftOpen, Siren, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { people } from "@/data/people";
import { SHIFT } from "@/lib/time";
import { cn } from "@/lib/cn";
import { useKpis } from "@/hooks/useWorldData";
import { useUi } from "@/store/ui";
import { useWorld } from "@/store/world";
import { Avatar } from "@/components/common/Card";
import { Kbd } from "@/components/common/Badges";
import { Tooltip } from "@/components/common/Tooltip";
import { LogoMark } from "@/components/layout/Logo";

function useAutoCollapse() {
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 1279px)");
    const apply = () => useUi.setState({ sidebarCollapsed: mq.matches });
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, []);
}

export function Sidebar() {
  useAutoCollapse();
  const pathname = usePathname();
  const collapsed = useUi((s) => s.sidebarCollapsed);
  const set = useUi((s) => s.set);
  const kpis = useKpis();
  const unread = useWorld((w) => w.notifications.filter((n) => !n.read).length);
  const awaiting = useWorld((w) => w.escalations.filter((e) => e.status === "awaiting").length);

  const nav = [
    { href: "/", label: "Overview", icon: LayoutDashboard, match: (p: string) => p === "/" },
    { href: "/shipments", label: "Shipments", icon: Package, match: (p: string) => p.startsWith("/shipments"), count: kpis.disrupted + kpis.atRisk + kpis.review || undefined },
    { href: "/incidents", label: "Incidents", icon: Siren, match: (p: string) => p.startsWith("/incidents"), count: kpis.incidents || undefined, alert: !!kpis.criticalIncident },
    { href: "/models", label: "Model Lab", icon: FlaskConical, match: (p: string) => p.startsWith("/models") },
    { href: "/notifications", label: "Notifications", icon: Bell, match: (p: string) => p.startsWith("/notifications"), count: unread || undefined },
  ];

  return (
    <aside className={cn("sticky top-0 flex h-dvh shrink-0 flex-col border-r border-line bg-surface transition-[width] duration-200", collapsed ? "w-[68px]" : "w-[232px]")} aria-label="Primary">
      <div className={cn("flex h-14 items-center border-b border-line-soft", collapsed ? "justify-center px-2" : "justify-between px-4")}>
        <Link href="/" className="rounded-lg" aria-label="Dallal — Operations overview">
          <LogoMark size={collapsed ? 30 : 40} />
        </Link>
        {collapsed ? null : (
          <button onClick={() => set({ sidebarCollapsed: true })} className="rounded-md p-1 text-ink-4 hover:bg-hover hover:text-ink-2" aria-label="Collapse sidebar">
            <PanelLeftClose className="size-4" />
          </button>
        )}
      </div>

      <nav className="flex flex-col gap-0.5 px-2.5 pt-3">
        {nav.map((item) => {
          const active = item.match(pathname);
          const Icon = item.icon;
          const link = (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "group relative flex h-9 items-center gap-2.5 rounded-lg text-13 font-medium transition-colors",
                collapsed ? "justify-center px-0" : "px-2.5",
                active ? "bg-brand-50 text-brand-800" : "text-ink-2 hover:bg-hover hover:text-ink",
              )}
            >
              {active ? <motion.span layoutId="nav-active" className="absolute inset-y-1.5 left-0 w-[3px] rounded-r bg-brand-600" transition={{ type: "spring", stiffness: 500, damping: 40 }} /> : null}
              <Icon className={cn("size-[18px] shrink-0", active ? "text-brand-600" : "text-ink-3 group-hover:text-ink-2")} />
              {collapsed ? null : <span className="flex-1">{item.label}</span>}
              {item.count ? (
                <span
                  className={cn(
                    "rounded-full px-1.5 text-2xs font-semibold tabular",
                    collapsed ? "absolute top-0.5 right-1 min-w-4 text-center" : "",
                    item.alert ? "bg-crit-600 text-white" : active ? "bg-brand-100 text-brand-800" : "bg-muted text-ink-2",
                  )}
                >
                  {item.count}
                </span>
              ) : null}
            </Link>
          );
          return collapsed ? (
            <Tooltip key={item.href} content={item.label} side="right">
              {link}
            </Tooltip>
          ) : (
            link
          );
        })}
        <button
          onClick={() => set({ assistantOpen: true })}
          className={cn("group flex h-9 items-center gap-2.5 rounded-lg text-13 font-medium text-ink-2 transition-colors hover:bg-hover hover:text-ink", collapsed ? "justify-center" : "px-2.5")}
          aria-label="Open Dallal Assistant"
        >
          <Sparkles className="size-[18px] text-brand-500" />
          {collapsed ? null : (
            <>
              <span className="flex-1 text-left">Assistant</span>
              <Kbd>⌘J</Kbd>
            </>
          )}
        </button>
      </nav>

      <div className="flex-1" />

      {collapsed ? (
        <div className="flex flex-col items-center gap-3 pb-4">
          <Tooltip content={`${people.supervisor.name} · ${people.supervisor.role} on duty`} side="right">
            <span className="relative">
              <Avatar initials={people.supervisor.initials} tone="review" size={30} />
              <span className="absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full bg-ok-500 ring-2 ring-surface" />
            </span>
          </Tooltip>
          <button onClick={() => set({ sidebarCollapsed: false })} className="rounded-md p-1.5 text-ink-4 hover:bg-hover hover:text-ink-2" aria-label="Expand sidebar">
            <PanelLeftOpen className="size-4" />
          </button>
        </div>
      ) : (
        <div className="space-y-3 px-3 pb-4">
          <div className="rounded-xl border border-line bg-subtle p-3">
            <div className="text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">Escalations go to</div>
            <div className="mt-2 flex items-center gap-2.5">
              <span className="relative">
                <Avatar initials={people.supervisor.initials} tone="review" size={32} />
                <span className="absolute -right-0.5 -bottom-0.5 size-2.5 rounded-full bg-ok-500 ring-2 ring-subtle" aria-label="On duty" />
              </span>
              <div className="min-w-0">
                <div className="truncate text-13 font-semibold text-ink">{people.supervisor.name}</div>
                <div className="truncate text-xs text-ink-3">{people.supervisor.role}</div>
                <div className="truncate text-2xs text-ok-700">On duty until {SHIFT.end}</div>
              </div>
            </div>
            {awaiting ? (
              <Link href="/shipments?tab=supervisor" className="mt-2.5 flex items-center justify-between rounded-lg bg-review-50 px-2 py-1.5 text-xs font-medium text-review-700 hover:bg-review-100">
                <span>Awaiting decision</span>
                <span className="font-semibold tabular">{awaiting}</span>
              </Link>
            ) : null}
          </div>
          <div className="flex gap-2 rounded-xl px-1 text-2xs leading-4 text-ink-4">
            <Info className="mt-px size-3.5 shrink-0" aria-hidden />
            <p>
              Prototype. Roads and places are real (OpenStreetMap); shipments, events and scores are simulated.
            </p>
          </div>
        </div>
      )}
    </aside>
  );
}
