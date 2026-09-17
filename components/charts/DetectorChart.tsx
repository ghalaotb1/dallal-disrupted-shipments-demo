"use client";

import { Bar, BarChart, CartesianGrid, Cell, LabelList, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Incident } from "@/types/domain";

const GRAY = "#c3ccd8";
const CRIT = "#df3b30";

/**
 * Emphasis form: past windows are context (gray), the current window is the point (critical),
 * with the detector threshold (mean + k·σ) drawn as a labelled reference line.
 */
export function DetectorChart({ detector, height = 168 }: { detector: Incident["detector"]; height?: number }) {
  const threshold = detector.baselineMean + detector.threshold * Math.max(detector.baselineStd, 0.35);
  const data = detector.series.map((p) => ({ ...p, fill: p.current ? CRIT : GRAY }));
  const max = Math.max(threshold + 1, ...data.map((d) => d.count)) + 0.5;
  return (
    <figure className="m-0">
      <div style={{ height }} aria-hidden>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 18, right: 8, bottom: 0, left: -18 }} barCategoryGap={4}>
            <CartesianGrid vertical={false} stroke="#e8edf3" />
            <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: "#e2e8f0" }} tick={{ fill: "#637186", fontSize: 10.5 }} interval="preserveStartEnd" minTickGap={10} />
            <YAxis allowDecimals={false} domain={[0, Math.ceil(max)]} tickLine={false} axisLine={false} tick={{ fill: "#637186", fontSize: 10.5 }} width={36} />
            <Tooltip cursor={{ fill: "rgba(15,30,54,0.05)" }} content={<DetectorTooltip mean={detector.baselineMean} />} />
            <ReferenceLine
              y={threshold}
              stroke={CRIT}
              strokeDasharray="4 3"
              strokeWidth={1.25}
              ifOverflow="extendDomain"
              label={{ value: `threshold ${threshold.toFixed(1)}`, position: "insideTopLeft", fill: "#9c2018", fontSize: 10.5, offset: 6 }}
            />
            <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false}>
              {data.map((d) => (
                <Cell key={d.label} fill={d.fill} />
              ))}
              <LabelList dataKey="count" position="top" content={({ x, y, width, value, index }) => (data[index as number]?.current ? <text x={Number(x) + Number(width) / 2} y={Number(y) - 5} textAnchor="middle" fontSize={11} fontWeight={600} fill="#0f1e36">{String(value)}</text> : null)} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="sr-only">
        Failures per {detector.window} window. Baseline mean {detector.baselineMean.toFixed(2)}, standard deviation {detector.baselineStd.toFixed(2)}, threshold {threshold.toFixed(2)}. Current window {detector.observed}.
        <table>
          <thead>
            <tr>
              <th>Window</th>
              <th>Failures</th>
            </tr>
          </thead>
          <tbody>
            {detector.series.map((p) => (
              <tr key={p.label}>
                <td>{p.label}</td>
                <td>{p.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </figcaption>
    </figure>
  );
}

function DetectorTooltip({ active, payload, mean }: { active?: boolean; payload?: { payload: { label: string; count: number; current?: boolean } }[]; mean: number }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs shadow-float">
      <div className="text-15 font-semibold text-ink tabular">{p.count}</div>
      <div className="text-ink-3">
        {p.current ? "Current window" : `Window from ${p.label}`} · baseline {mean.toFixed(1)}
      </div>
    </div>
  );
}
