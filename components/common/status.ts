import {
  CircleCheck,
  CircleDot,
  OctagonAlert,
  PackageCheck,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
  UserRoundSearch,
  type LucideIcon,
} from "lucide-react";
import type { RiskLevel, Severity, ShipmentHealth } from "@/types/domain";

/** Single source of truth for status color, icon and wording across queue, map and cards. */
export const HEALTH: Record<ShipmentHealth, { label: string; icon: LucideIcon; chip: string; text: string; dot: string; map: string; soft: string }> = {
  on_track: { label: "On track", icon: CircleDot, chip: "bg-ok-50 text-ok-700 ring-ok-100", text: "text-ok-700", dot: "bg-ok-500", map: "#1f9d55", soft: "bg-ok-50" },
  at_risk: { label: "At risk", icon: TriangleAlert, chip: "bg-warn-50 text-warn-700 ring-warn-100", text: "text-warn-700", dot: "bg-warn-500", map: "#e38b06", soft: "bg-warn-50" },
  disrupted: { label: "Disrupted", icon: OctagonAlert, chip: "bg-crit-50 text-crit-700 ring-crit-100", text: "text-crit-700", dot: "bg-crit-500", map: "#df3b30", soft: "bg-crit-50" },
  review: { label: "Human review", icon: UserRoundSearch, chip: "bg-review-50 text-review-700 ring-review-100", text: "text-review-700", dot: "bg-review-500", map: "#7456e0", soft: "bg-review-50" },
  recovering: { label: "Recovering", icon: RefreshCw, chip: "bg-brand-50 text-brand-700 ring-brand-100", text: "text-brand-700", dot: "bg-brand-500", map: "#2f6be6", soft: "bg-brand-50" },
  recovered: { label: "Recovered", icon: CircleCheck, chip: "bg-ok-50 text-ok-700 ring-ok-100", text: "text-ok-700", dot: "bg-ok-500", map: "#1f9d55", soft: "bg-ok-50" },
  prevented: { label: "Failure prevented", icon: ShieldCheck, chip: "bg-ok-50 text-ok-700 ring-ok-100", text: "text-ok-700", dot: "bg-ok-500", map: "#1f9d55", soft: "bg-ok-50" },
  delivered: { label: "Delivered", icon: PackageCheck, chip: "bg-muted text-ink-3 ring-line", text: "text-ink-3", dot: "bg-ink-4", map: "#8a97aa", soft: "bg-muted" },
};

export const TRAVELED_COLOR = "#a7b4c6";

export const RISK: Record<RiskLevel, { label: string; text: string; bar: string; segments: number }> = {
  low: { label: "Low", text: "text-ok-700", bar: "bg-ok-500", segments: 1 },
  elevated: { label: "Elevated", text: "text-warn-700", bar: "bg-warn-500", segments: 2 },
  high: { label: "High", text: "text-crit-600", bar: "bg-crit-500", segments: 3 },
  critical: { label: "Critical", text: "text-crit-700", bar: "bg-crit-600", segments: 4 },
};

export const SEVERITY: Record<Severity, { label: string; chip: string; dot: string; ring: string }> = {
  low: { label: "Low", chip: "bg-muted text-ink-2 ring-line", dot: "bg-ink-4", ring: "ring-line" },
  medium: { label: "Medium", chip: "bg-warn-50 text-warn-700 ring-warn-100", dot: "bg-warn-500", ring: "ring-warn-200" },
  high: { label: "High", chip: "bg-crit-50 text-crit-700 ring-crit-100", dot: "bg-crit-500", ring: "ring-crit-200" },
  critical: { label: "Critical", chip: "bg-crit-600 text-white ring-crit-600", dot: "bg-crit-600", ring: "ring-crit-300" },
};

export const TONE_TEXT = { info: "text-brand-700", ok: "text-ok-700", warn: "text-warn-700", crit: "text-crit-700", review: "text-review-700" } as const;
export const TONE_SOFT = { info: "bg-brand-50", ok: "bg-ok-50", warn: "bg-warn-50", crit: "bg-crit-50", review: "bg-review-50" } as const;
