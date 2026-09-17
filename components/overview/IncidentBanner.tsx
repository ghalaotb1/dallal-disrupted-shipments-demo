"use client";

import Link from "next/link";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, MapPinned, Siren } from "lucide-react";
import { plural } from "@/lib/format";
import { fmtRelative } from "@/lib/time";
import { useDemoNow } from "@/hooks/useDemoNow";
import { useKpis } from "@/hooks/useWorldData";
import { focusMap } from "@/store/ui";
import { SeverityBadge } from "@/components/common/Badges";
import { Button } from "@/components/common/Button";

export function IncidentBanner() {
  const { criticalIncident: inc } = useKpis();
  const now = useDemoNow(15_000);
  return (
    <AnimatePresence initial={false}>
      {inc ? (
        <motion.section
          key={inc.id}
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.45, ease: [0.2, 0.8, 0.2, 1] }}
          className="overflow-hidden"
          aria-live="polite"
        >
          <div className="relative flex flex-wrap items-center gap-x-4 gap-y-2 overflow-hidden rounded-xl border border-crit-200 bg-gradient-to-r from-crit-50 via-crit-50 to-surface px-4 py-3">
            <span className="relative flex size-10 shrink-0 items-center justify-center">
              <span className="absolute inset-0 animate-pulse-ring rounded-full bg-crit-500/30" aria-hidden />
              <span className="relative flex size-10 items-center justify-center rounded-full bg-crit-600 text-white shadow-marker">
                <Siren className="size-5" aria-hidden />
              </span>
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-crit-700">1 operational incident detected</span>
                <span className="text-sm font-semibold text-ink">
                  · {inc.title}
                </span>
                <SeverityBadge severity={inc.severity} />
                <span className="text-xs text-ink-3">{fmtRelative(inc.detectedAt, now)}</span>
              </div>
              <p className="mt-0.5 text-13 text-ink-2">
                <span className="font-semibold text-ink">{plural(inc.affected.length, "shipment failure")}</span> share one cause: {inc.subtitle}.{" "}
                {inc.exposed.length ? (
                  <>
                    <span className="font-semibold text-warn-700">{plural(inc.exposed.length, "more shipment")}</span> {inc.exposed.length === 1 ? "is" : "are"} exposed.{" "}
                  </>
                ) : null}
                <span className="text-ink-3">One response instead of {inc.affected.length + inc.exposed.length} separate alerts.</span>
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <Button size="sm" variant="secondary" onClick={() => focusMap({ kind: "incident", id: inc.id })}>
                <MapPinned /> Show on map
              </Button>
              <Link href={`/incidents/${inc.id}`} className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-crit-600 px-3 text-13 font-medium text-white shadow-[0_1px_2px_rgb(15_30_54/0.2)] hover:bg-crit-700">
                Open incident <ArrowRight className="size-4" />
              </Link>
            </div>
          </div>
        </motion.section>
      ) : null}
    </AnimatePresence>
  );
}
