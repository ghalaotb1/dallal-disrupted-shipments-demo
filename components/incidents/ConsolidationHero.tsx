"use client";

import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";
import { ArrowRight, Package, Plus, Siren } from "lucide-react";
import { cn } from "@/lib/cn";
import { plural } from "@/lib/format";
import { HEALTH } from "@/components/common/status";
import type { Incident, Shipment } from "@/types/domain";

/**
 * The incident "wow": many individual failures visibly converge into one
 * operational incident, with the not-yet-failed exposed shipments beside it.
 */
export function ConsolidationHero({ incident: inc, shipments }: { incident: Incident; shipments: Record<string, Shipment> }) {
  const reduce = useReducedMotion();
  const affected = inc.affected.map((id) => shipments[id]).filter(Boolean);
  const exposed = inc.exposed.map((id) => shipments[id]).filter(Boolean);
  const total = affected.length + exposed.length;
  const resolved = inc.status === "resolved";
  const responded = inc.response.state === "applied";
  const delay = (i: number) => (reduce ? 0 : 0.08 * i);

  return (
    <section className="relative overflow-hidden rounded-xl border border-line bg-surface shadow-card" aria-label="Failures consolidated into one incident">
      <div className="grid items-stretch gap-0 lg:grid-cols-[1fr_auto_1.05fr_auto_1fr]">
        <div className="p-5">
          <div className="text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">Would have been</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-[34px] leading-none font-semibold tracking-[-0.03em] text-crit-600">{affected.length}</span>
            <span className="text-13 font-medium text-ink-2">separate failure alerts</span>
          </div>
          <ul className="mt-3 flex flex-wrap gap-1.5">
            {affected.map((s, i) => (
              <motion.li key={s.id} initial={reduce ? false : { opacity: 0, x: -14 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: delay(i), duration: 0.35 }}>
                <Link href={`/shipments/${s.id}`} className={cn("inline-flex items-center gap-1 rounded-md px-1.5 py-1 font-mono text-[11px] font-semibold ring-1 ring-inset hover:brightness-95", HEALTH[s.health].chip)}>
                  <Package className="size-3" aria-hidden />
                  {s.id.slice(3)}
                </Link>
              </motion.li>
            ))}
          </ul>
        </div>

        <Connector reduce={!!reduce} delay={delay(affected.length)} />

        <div className="relative flex flex-col items-center justify-center border-y border-line-soft bg-gradient-to-b from-crit-50/70 to-surface px-6 py-5 text-center lg:border-x lg:border-y-0">
          <motion.span
            initial={reduce ? false : { scale: 0.6, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            transition={{ delay: delay(affected.length) + 0.15, type: "spring", stiffness: 260, damping: 18 }}
            className="relative flex size-14 items-center justify-center"
          >
            {!resolved ? <span className="absolute inset-0 animate-pulse-ring rounded-full bg-crit-500/30" aria-hidden /> : null}
            <span className={cn("relative flex size-14 items-center justify-center rounded-full text-white shadow-marker ring-4 ring-white", resolved ? "bg-ok-600" : "bg-crit-600")}>
              <Siren className="size-7" aria-hidden />
            </span>
          </motion.span>
          <div className="mt-3 text-[26px] leading-none font-semibold tracking-[-0.02em] text-ink">1 operational incident</div>
          <div className="mt-1.5 text-13 text-ink-2">
            {inc.id} · <span className="font-medium">{inc.sharedFactor.label}</span>
          </div>
          <p className="mt-2 max-w-[34ch] text-xs text-ink-3">
            {resolved ? `Resolved with one response covering ${plural(total, "shipment")}.` : responded ? `One group response is recovering ${plural(total, "shipment")}.` : `Fix one shared cause instead of handling ${plural(total, "alert")} one by one.`}
          </p>
        </div>

        <Connector reduce={!!reduce} delay={delay(affected.length) + 0.3} plus />

        <div className="p-5">
          <div className="text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">{responded ? "Protected by the response" : "Likely next"}</div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className={cn("text-[34px] leading-none font-semibold tracking-[-0.03em]", responded ? "text-brand-600" : "text-warn-600")}>{exposed.length}</span>
            <span className="text-13 font-medium text-ink-2">{responded ? "exposed shipments rerouted" : "exposed shipments"}</span>
          </div>
          <ul className="mt-3 flex flex-wrap gap-1.5">
            {exposed.map((s, i) => (
              <motion.li key={s.id} initial={reduce ? false : { opacity: 0, x: 14 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: delay(affected.length + i) + 0.35, duration: 0.35 }}>
                <Link
                  href={`/shipments/${s.id}`}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-md px-1.5 py-1 font-mono text-[11px] font-semibold",
                    responded ? cn("ring-1 ring-inset", HEALTH[s.health].chip) : "border border-dashed border-warn-500 bg-warn-50 text-warn-700 hover:bg-warn-100",
                  )}
                >
                  <Package className="size-3" aria-hidden />
                  {s.id.slice(3)}
                </Link>
              </motion.li>
            ))}
            {!exposed.length ? <li className="text-xs text-ink-3">None — no other shipments are routed through the zone.</li> : null}
          </ul>
          <p className="mt-2 text-2xs text-ink-4">{responded ? "Diverted before they reached the incident zone." : "Not failed yet — their planned route crosses the incident zone."}</p>
        </div>
      </div>
    </section>
  );
}

function Connector({ reduce, delay, plus }: { reduce: boolean; delay: number; plus?: boolean }) {
  return (
    <div className="hidden items-center justify-center px-1 lg:flex" aria-hidden>
      <motion.span initial={reduce ? false : { opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay }} className="flex size-8 items-center justify-center rounded-full border border-line bg-surface text-ink-3 shadow-card">
        {plus ? <Plus className="size-4" /> : <ArrowRight className="size-4" />}
      </motion.span>
    </div>
  );
}
