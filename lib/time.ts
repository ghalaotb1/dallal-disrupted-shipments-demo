import type { DemoTime } from "@/types/domain";

/** The simulated operating day. All scenario times are expressed in Riyadh time. */
export const DEMO_DAY = "2026-09-16";
export const DEMO_TZ = "Asia/Riyadh";
/** Scenario clock speed: one real second advances the operations clock by this many seconds. */
export const DEMO_TIME_SCALE = 10;
export const SHIFT = { name: "Afternoon shift", start: "12:00", end: "20:00" };

const MIN = 60_000;

/** Demo timestamp for a wall-clock time on the demo day (or `dayOffset` days before/after). */
export function at(hhmm: string, dayOffset = 0): DemoTime {
  const [h, m, s = "0"] = hhmm.split(":");
  const base = Date.parse(`${DEMO_DAY}T00:00:00+03:00`);
  return base + dayOffset * 86_400_000 + Number(h) * 3_600_000 + Number(m) * MIN + Number(s) * 1000;
}

export const SCENARIO_START = at("15:10");

const timeFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: DEMO_TZ });
const timeSecFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: DEMO_TZ });
const dayFmt = new Intl.DateTimeFormat("en-US", { day: "numeric", month: "short", timeZone: DEMO_TZ });
const weekdayFmt = new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: DEMO_TZ });

export const fmtTime = (t: DemoTime) => timeFmt.format(t);
export const fmtTimeSec = (t: DemoTime) => timeSecFmt.format(t);
/** "Wed 16 Sep" */
export const fmtDate = (t: DemoTime) => {
  const [month, day] = dayFmt.format(t).split(" ");
  return `${weekdayFmt.format(t)} ${day} ${month}`;
};

/** "15:10" today, "14 Sep, 17:40" on other days. */
export function fmtDayTime(t: DemoTime, now: DemoTime) {
  if (sameDay(t, now)) return fmtTime(t);
  const [month, day] = dayFmt.format(t).split(" ");
  return `${day} ${month}, ${fmtTime(t)}`;
}

export function sameDay(a: DemoTime, b: DemoTime) {
  return dayFmt.format(a) === dayFmt.format(b);
}

export function fmtDuration(ms: number) {
  const total = Math.max(0, Math.round(ms / MIN));
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

export function fmtRelative(t: DemoTime, now: DemoTime) {
  const diff = t - now;
  const abs = Math.abs(diff);
  if (abs < MIN) return diff <= 0 ? "just now" : "in <1 min";
  const d = fmtDuration(abs);
  return diff < 0 ? `${d} ago` : `in ${d}`;
}

export function fmtWindow(w: { start: DemoTime; end: DemoTime }) {
  return `${fmtTime(w.start)}–${fmtTime(w.end)}`;
}
