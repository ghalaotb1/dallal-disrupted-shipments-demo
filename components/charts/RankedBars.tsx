"use client";

/**
 * Horizontal ranked bars in emphasis form: the leading item in the accent,
 * the rest in de-emphasis gray, values at the bar tips in text tokens.
 */
export function RankedBars({ data, unit }: { data: { label: string; value: number; tone?: string }[]; unit: string }) {
  const max = Math.max(1, ...data.map((d) => d.value));
  return (
    <figure className="m-0">
      <ul className="space-y-1.5" aria-hidden>
        {data.map((d) => {
          const emphasised = d.tone === "brand" || d.tone === "crit";
          return (
            <li key={d.label} className="group grid grid-cols-[minmax(0,42%)_1fr] items-center gap-2" title={`${d.label}: ${d.value} ${unit}`}>
              <span className="truncate text-xs text-ink-2">{d.label}</span>
              <span className="flex items-center gap-1.5">
                <span className="h-3.5 rounded-r-[4px] transition-opacity group-hover:opacity-80" style={{ width: `${Math.max(4, (d.value / max) * 82)}%`, background: emphasised ? (d.tone === "crit" ? "#df3b30" : "#2f6be6") : "#c3ccd8" }} />
                <span className="text-xs font-semibold text-ink tabular">{d.value}</span>
              </span>
            </li>
          );
        })}
      </ul>
      <table className="sr-only">
        <thead>
          <tr>
            <th>Item</th>
            <th>{unit}</th>
          </tr>
        </thead>
        <tbody>
          {data.map((d) => (
            <tr key={d.label}>
              <td>{d.label}</td>
              <td>{d.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
