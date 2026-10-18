import { cn } from "@/lib/cn";
import { HEALTH } from "@/components/common/status";
import type { ShipmentHealth } from "@/types/domain";

export function HealthChip({ health, className, label }: { health: ShipmentHealth; className?: string; label?: string }) {
  const h = HEALTH[health];
  const Icon = h.icon;
  return (
    <span className={cn("inline-flex h-[22px] items-center gap-1 rounded-full px-2 text-xs font-medium whitespace-nowrap ring-1 ring-inset [&_svg]:size-3.5", h.chip, className)}>
      <Icon aria-hidden strokeWidth={2.25} />
      {label ?? h.label}
    </span>
  );
}

export function SimTag({ className }: { className?: string }) {
  return <span className={cn("inline-flex h-[18px] items-center rounded px-1 text-[10px] font-semibold tracking-wide text-ink-4 uppercase ring-1 ring-line ring-inset", className)}>Sim</span>;
}

export function Dot({ health, className }: { health: ShipmentHealth; className?: string }) {
  return <span className={cn("inline-block size-2 shrink-0 rounded-full", HEALTH[health].dot, className)} aria-hidden />;
}
