"use client";

import { Info, Radar } from "lucide-react";
import { SimTag } from "@/components/common/Badges";
import { Tooltip } from "@/components/common/Tooltip";
import { DetectorChart } from "@/components/charts/DetectorChart";
import type { Incident } from "@/types/domain";

export function IncidentSignals({ incident: inc }: { incident: Incident }) {
  const d = inc.detector;
  return (
    <section className="rounded-xl border border-line bg-surface shadow-card" aria-labelledby="signals-title">
      <header className="px-5 pt-4">
        <div className="flex items-center gap-2 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">
          <Radar className="size-3.5" aria-hidden /> Why Dallal grouped these
        </div>
        <h2 id="signals-title" className="mt-1 text-15 font-semibold text-ink">
          One shared signal, not a coincidence
        </h2>
      </header>
      <dl className="mt-3 divide-y divide-line-soft border-y border-line-soft">
        {inc.signals.map((sig) => (
          <div key={sig.label} className="grid grid-cols-[130px_1fr] gap-3 px-5 py-2">
            <dt className="text-xs text-ink-3">{sig.label}</dt>
            <dd>
              <div className="text-13 font-semibold text-ink">{sig.value}</div>
              <div className="text-xs text-ink-3">{sig.detail}</div>
            </dd>
          </div>
        ))}
      </dl>
      <div className="px-5 pt-3 pb-4">
        <div className="flex items-center justify-between gap-2">
          <div className="text-xs font-semibold text-ink-2">
            Incident detector
            <span className="ml-1.5 font-normal text-ink-3">{d.method}</span>
          </div>
          <Tooltip content="Real statistical logic running on the simulated event stream: failures in the current window are compared with this corridor's rolling baseline. Flag when the count exceeds mean + 3σ.">
            <Info className="size-3.5 cursor-help text-ink-4" aria-label="About the detector" />
          </Tooltip>
        </div>
        <div className="mt-1 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs text-ink-3">
          <span>
            Current window <span className="font-semibold text-ink tabular">{d.observed}</span>
          </span>
          <span>
            Baseline <span className="font-medium text-ink-2 tabular">{d.baselineMean.toFixed(2)} ± {d.baselineStd.toFixed(2)}</span>
          </span>
          <span>
            z-score <span className="font-semibold text-crit-600 tabular">{d.z.toFixed(1)}</span> vs threshold {d.threshold.toFixed(1)}
          </span>
          <SimTag label="simulated events" tip="The detector computation is real; the event stream it runs on is the simulated scenario." />
        </div>
        <div className="mt-2">
          <DetectorChart detector={d} />
        </div>
      </div>
    </section>
  );
}
