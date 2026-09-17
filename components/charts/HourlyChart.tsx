"use client";

import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const SERIES = { exceptions: { label: "Exceptions & risk flags", color: "#2f6be6" }, recovered: { label: "Recovered or prevented", color: "#14a37f" } } as const;

/** Two series on one count axis: columns for new exceptions, a line for recoveries (different marks = secondary encoding). */
export function HourlyChart({ data }: { data: { hour: string; exceptions: number; recovered: number }[] }) {
  return (
    <figure className="m-0">
      <div className="mb-1 flex flex-wrap gap-3 text-2xs text-ink-2" aria-hidden>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2 rounded-t-[2px]" style={{ background: SERIES.exceptions.color }} /> {SERIES.exceptions.label}
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="16" height="8">
            <line x1="0" y1="4" x2="16" y2="4" stroke={SERIES.recovered.color} strokeWidth="2" />
            <circle cx="8" cy="4" r="3" fill={SERIES.recovered.color} stroke="#fff" strokeWidth="1.5" />
          </svg>
          {SERIES.recovered.label}
        </span>
      </div>
      <div className="h-[150px]" aria-hidden>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={data} margin={{ top: 6, right: 6, bottom: 0, left: -22 }} barCategoryGap="28%">
            <CartesianGrid vertical={false} stroke="#e8edf3" />
            <XAxis dataKey="hour" tickLine={false} axisLine={{ stroke: "#e2e8f0" }} tick={{ fill: "#8a97aa", fontSize: 10.5 }} tickFormatter={(h: string) => h.slice(0, 2)} />
            <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "#8a97aa", fontSize: 10.5 }} width={34} />
            <Tooltip cursor={{ fill: "rgba(15,30,54,0.05)" }} content={<HourTooltip />} />
            <Bar dataKey="exceptions" fill={SERIES.exceptions.color} radius={[4, 4, 0, 0]} maxBarSize={18} isAnimationActive={false} />
            <Line dataKey="recovered" stroke={SERIES.recovered.color} strokeWidth={2} dot={{ r: 3.5, fill: SERIES.recovered.color, stroke: "#fff", strokeWidth: 2 }} activeDot={{ r: 5, stroke: "#fff", strokeWidth: 2 }} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <table className="sr-only">
        <caption>Exceptions and recoveries by hour</caption>
        <thead>
          <tr>
            <th>Hour</th>
            <th>{SERIES.exceptions.label}</th>
            <th>{SERIES.recovered.label}</th>
          </tr>
        </thead>
        <tbody>
          {data.map((d) => (
            <tr key={d.hour}>
              <td>{d.hour}</td>
              <td>{d.exceptions}</td>
              <td>{d.recovered}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

function HourTooltip({ active, payload }: { active?: boolean; payload?: { payload: { hour: string; exceptions: number; recovered: number } }[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-lg border border-line bg-surface px-2.5 py-1.5 text-xs shadow-float">
      <div className="mb-1 text-2xs text-ink-4">{d.hour}–{String(Number(d.hour.slice(0, 2)) + 1).padStart(2, "0")}:00</div>
      <div className="flex items-center gap-2">
        <span className="inline-block h-0.5 w-3" style={{ background: SERIES.exceptions.color }} />
        <span className="font-semibold text-ink tabular">{d.exceptions}</span>
        <span className="text-ink-3">{SERIES.exceptions.label}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="inline-block h-0.5 w-3" style={{ background: SERIES.recovered.color }} />
        <span className="font-semibold text-ink tabular">{d.recovered}</span>
        <span className="text-ink-3">{SERIES.recovered.label}</span>
      </div>
    </div>
  );
}
