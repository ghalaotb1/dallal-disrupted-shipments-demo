import { HEALTH } from "@/components/common/status";
import type { ShipmentHealth } from "@/types/domain";

const ITEMS: ShipmentHealth[] = ["on_track", "at_risk", "disrupted", "review", "recovering", "prevented"];
const LABEL: Partial<Record<ShipmentHealth, string>> = { review: "Needs manager", prevented: "Resolved" };

export function MapLegend() {
  return (
    <div className="pointer-events-none absolute bottom-7 left-3 z-10 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-surface/95 px-3 py-1.5 text-[11px] text-ink-3 shadow-float backdrop-blur-sm">
      {ITEMS.map((h) => (
        <span key={h} className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-full ring-2 ring-white" style={{ background: HEALTH[h].map }} aria-hidden />
          {LABEL[h] ?? HEALTH[h].label}
        </span>
      ))}
    </div>
  );
}
