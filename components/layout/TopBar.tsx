"use client";

import { MapPin, Search, Sparkles } from "lucide-react";
import { people } from "@/data/people";
import { SHIFT } from "@/lib/time";
import { useUi } from "@/store/ui";
import { Avatar } from "@/components/common/Card";
import { Kbd } from "@/components/common/Badges";
import { Button } from "@/components/common/Button";
import { DemoClock } from "@/components/layout/DemoControl";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import { BackendStatus } from "@/components/live/BackendStatus";

export function TopBar() {
  const set = useUi((s) => s.set);
  return (
    <header className="sticky top-0 z-40 flex h-14 shrink-0 items-center gap-3 border-b border-line bg-surface/95 px-4 backdrop-blur-sm lg:px-5">
      <div className="hidden min-w-0 shrink-0 items-center gap-3 whitespace-nowrap lg:flex">
        <div className="flex items-center gap-1.5 text-13 font-medium text-ink">
          <MapPin className="size-4 text-brand-600" aria-hidden />
          Eastern Region
          <span className="hidden font-normal text-ink-3 2xl:inline">· Dammam–Khobar desk</span>
        </div>
        <span className="hidden h-4 w-px bg-line xl:block" aria-hidden />
        <div className="hidden text-13 text-ink-3 xl:block">
          {SHIFT.name} <span className="tabular">{SHIFT.start}–{SHIFT.end}</span>
        </div>
      </div>

      <button
        onClick={() => set({ commandOpen: true })}
        className="flex h-9 w-full max-w-[340px] min-w-[160px] items-center gap-2 rounded-lg border border-line bg-subtle px-3 text-13 text-ink-4 transition-colors hover:border-line-strong hover:bg-surface lg:ml-3"
        aria-label="Search shipments, incidents and places"
      >
        <Search className="size-4" aria-hidden />
        <span className="flex-1 truncate text-left">Search shipments, incidents, places…</span>
        <Kbd>⌘K</Kbd>
      </button>

      <div className="ml-auto flex items-center gap-2">
        <BackendStatus />
        <DemoClock />
        <NotificationBell />
        <Button variant="soft" size="md" onClick={() => set({ assistantOpen: true })} className="hidden md:inline-flex">
          <Sparkles /> Ask Dallal
        </Button>
        <span className="mx-1 h-6 w-px bg-line" aria-hidden />
        <div className="flex items-center gap-2" title={`${people.analyst.name} · ${people.analyst.role}`}>
          <Avatar initials={people.analyst.initials} size={32} />
          <div className="hidden leading-tight 2xl:block">
            <div className="text-13 font-medium">{people.analyst.name}</div>
            <div className="text-2xs text-ink-3">{people.analyst.role}</div>
          </div>
        </div>
      </div>
    </header>
  );
}
