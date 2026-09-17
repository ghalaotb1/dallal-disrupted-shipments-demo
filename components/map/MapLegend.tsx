"use client";

import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/cn";
import { HEALTH, TRAVELED_COLOR } from "@/components/common/status";
import type { MapVariant } from "@/components/map/routeFeatures";

const ITEMS = [
  { color: HEALTH.on_track.map, label: "On track" },
  { color: HEALTH.at_risk.map, label: "At risk" },
  { color: HEALTH.disrupted.map, label: "Disrupted" },
  { color: HEALTH.review.map, label: "Human review", dashed: true },
  { color: HEALTH.recovering.map, label: "Recovering" },
  { color: TRAVELED_COLOR, label: "Travelled" },
];

/** Compact, collapsible route legend. Status is also carried by marker icons and labels, never color alone. */
export function MapLegend({ variant, compact }: { variant: MapVariant; compact?: boolean }) {
  const [open, setOpen] = useState(!compact);
  return (
    <div className="absolute bottom-7 left-3 z-10 max-w-[calc(100%-24px)]">
      {open ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-line bg-surface/95 py-1.5 pr-1.5 pl-2.5 shadow-card backdrop-blur-sm">
          {ITEMS.map((it) => (
            <span key={it.label} className="flex items-center gap-1.5 text-2xs font-medium text-ink-2">
              <svg width="18" height="6" aria-hidden>
                <line x1="1" y1="3" x2="17" y2="3" stroke={it.color} strokeWidth="3.5" strokeLinecap="round" strokeDasharray={it.dashed ? "3.5 2.5" : undefined} />
              </svg>
              {it.label}
            </span>
          ))}
          {variant !== "shipment" ? (
            <span className="flex items-center gap-1.5 text-2xs font-medium text-ink-2">
              <span className="inline-block size-3 rounded-full border border-dashed border-crit-500 bg-crit-500/10" aria-hidden />
              Incident zone
            </span>
          ) : null}
          <button onClick={() => setOpen(false)} className="rounded p-0.5 text-ink-4 hover:bg-hover hover:text-ink-2" aria-label="Hide legend">
            <ChevronDown className="size-3.5" />
          </button>
        </div>
      ) : (
        <button onClick={() => setOpen(true)} className={cn("flex items-center gap-1 rounded-lg border border-line bg-surface/95 px-2.5 py-1 text-2xs font-semibold text-ink-2 shadow-card")} aria-label="Show legend">
          Legend <ChevronUp className="size-3" />
        </button>
      )}
    </div>
  );
}
