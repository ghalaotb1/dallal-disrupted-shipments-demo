"use client";

import { places } from "@/data/network";
import { cn } from "@/lib/cn";
import { progressOf } from "@/services/logic/movement";
import { HEALTH, TRAVELED_COLOR } from "@/components/common/status";
import type { Shipment } from "@/types/domain";

/** Mini route bar that mirrors the map: travelled segment muted, remaining segment in status color. */
export function RouteProgress({ s, now, className, showLabel }: { s: Shipment; now: number; className?: string; showLabel?: boolean }) {
  if (s.movement.mode === "facility") {
    return (
      <span className={cn("flex items-center gap-1.5 truncate text-2xs text-ink-3", className)}>
        <span className="inline-block h-1.5 w-6 rounded-full border border-dashed border-ink-5" aria-hidden />
        At {places[s.movement.facilityId!].short}
      </span>
    );
  }
  const p = Math.max(0, Math.min(1, progressOf(s, now)));
  const color = HEALTH[s.health].map;
  const held = s.movement.holdAtM !== undefined && s.health !== "on_track";
  return (
    <span className={cn("flex min-w-0 items-center gap-2", className)} aria-label={`${Math.round(p * 100)}% of route complete`}>
      <span className="relative h-[5px] min-w-12 flex-1 rounded-full" style={{ background: `${color}33` }}>
        <span className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-1000 ease-linear" style={{ width: `${p * 100}%`, background: TRAVELED_COLOR }} />
        <span
          className={cn("absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-white transition-[left] duration-1000 ease-linear", held && "animate-pulse")}
          style={{ left: `${p * 100}%`, background: color }}
        />
      </span>
      {showLabel ? <span className="text-2xs text-ink-3 tabular">{Math.round(p * 100)}%</span> : null}
    </span>
  );
}
