import { fmtTime } from "@/lib/time";
import { HEALTH } from "@/components/common/status";
import { parcelHealth, summarize } from "@/lib/ops/derive";
import { CAUSE, findings } from "@/lib/ops/narrative";
import { clockNow } from "@/store/ops";
import type { AssistantMessage, OpsWorld, Parcel } from "@/types/ops";

type Answer = Pick<AssistantMessage, "text" | "links">;

export const SUGGESTIONS = ["What needs attention?", "Why is DL-20655 delayed?", "What did Dallal do today?", "ما الذي يحتاج إلى انتباه؟", "لماذا فشل تسليم الطرد DL-20417؟", "هل هناك شيء ينتظر المدير؟"];

/**
 * Answers computed from the live operation (drivers, parcels, Dallal's runs and plans). A rule-based query layer, not a language model:
 * it never states anything the screens do not show.
 */
export function ask(query: string, w: OpsWorld): Answer {
  const q = query.toLowerCase();
  const now = clockNow(w.clock);
  const rows = summarize(w, now);
  const parcelOf = (id: string): Parcel | undefined => w.parcels[id.toUpperCase()];
  const idMatch = /dl-\d{5}/i.exec(query)?.[0];
  const driverRow = rows.find((r) => q.includes(r.driver.name.toLowerCase()) || q.includes(r.driver.nameAr) || q.includes(r.driver.vehicle.toLowerCase()));

  if (idMatch) {
    const p = parcelOf(idMatch);
    if (!p) return { text: `I can't find ${idMatch.toUpperCase()} in today's routes.` };
    const d = w.drivers[p.driverId];
    const h = parcelHealth(p, d, now);
    const link = { label: p.id, sub: d.name, target: { kind: "parcel" as const, id: p.id } };
    if (/why|cause|reason|delay|fail|problem|لماذا|سبب|تأخر|فشل|مشكل/.test(q)) {
      const run = Object.values(w.runs).filter((r) => r.ui.shipmentId === p.id).sort((a, b) => b.ui.startedAt - a.ui.startedAt)[0];
      if (run) {
        const cause = CAUSE[String(run.decision.top_cause)] ?? "unknown";
        const post = typeof run.decision.posterior === "number" ? ` (${Math.round(run.decision.posterior * 100)}%)` : "";
        const ev = findings(run).filter((f) => f.tone !== "ok").slice(0, 3).map((f) => `• ${f.label}: ${f.text}`).join("\n");
        return { text: `${p.id}: most likely ${cause.toLowerCase()}${post}.${ev ? `\n${ev}` : ""}`, links: [link] };
      }
      return { text: `${p.id}: ${p.exception ? `${p.exception.label} at ${fmtTime(p.exception.recordedAt)}` : p.headline ?? HEALTH[h].label}. Open it to see Dallal's analysis.`, links: [link] };
    }
    return { text: `${p.id} · ${d.name} (${d.vehicle}), stop ${p.seq} · ${p.address.district}. ${HEALTH[h].label}${p.headline ? ` - ${p.headline}` : ""}.`, links: [link] };
  }

  if (/manager|approv|waiting|escalat|supervisor|مدير|موافق|اعتماد|تصعيد/.test(q)) {
    const plans = Object.values(w.plans).filter((p) => p.status === "ready");
    const esc = Object.values(w.runs).filter((r) => r.decision.type === "escalate" && w.parcels[r.ui.shipmentId]?.state === "awaiting_manager");
    if (!plans.length && !esc.length) return { text: "Nothing is waiting for the manager." };
    const c = w.cases.find((x) => plans.some((p) => p.plan_id === x.planId));
    return { text: `${plans.length + esc.length} waiting for the manager${plans.length ? `: one plan for ${Object.keys(plans[0].solution.per_parcel).length} parcels on ${c?.affectedDriverIds.length ?? "several"} drivers` : ""}.`, links: c ? [{ label: c.label, sub: "Open case", target: { kind: "case", id: c.scenario } }] : undefined };
  }

  if (/most|worst|rank|which route|which driver|أكثر|أسوأ|أي مسار|أي سائق/.test(q)) {
    const top = [...rows].map((r) => ({ r, n: r.disrupted + r.atRisk + r.review })).filter((x) => x.n > 0).sort((a, b) => b.n - a.n).slice(0, 4);
    if (!top.length) return { text: "No route has open issues." };
    return { text: top.map((x) => `${x.r.driver.name}: ${x.n} parcel${x.n > 1 ? "s" : ""} with issues`).join("\n"), links: top.map((x) => ({ label: x.r.driver.name, sub: x.r.driver.vehicle, target: { kind: "driver" as const, id: x.r.driver.id } })) };
  }

  if (/attention|need|problem|issue|risk|disrupt|wrong|open|انتباه|مشاكل|مشكلة|تحتاج|مفتوح|متعثر/.test(q) && !driverRow) {
    const open = w.cases.filter((c) => !["prevented", "recovered"].includes(w.parcels[c.parcelId].state));
    if (!open.length) return { text: "Everything is on track." };
    return { text: `${open.length} open case${open.length > 1 ? "s" : ""}:\n${open.map((c) => `• ${c.label} · ${c.problem.detail}`).join("\n")}`, links: open.map((c) => ({ label: c.label, sub: c.problem.detail, target: { kind: "case" as const, id: c.scenario } })) };
  }

  if (driverRow) {
    const r = driverRow;
    const issues = r.disrupted + r.atRisk + r.review;
    return { text: `${r.driver.name} (${r.driver.vehicle}): ${r.done} of ${r.total} done${issues ? `, ${issues} with issues` : ", on track"}${r.nextStop ? `. Next: ${r.nextStop.address.district}` : ""}.`, links: [{ label: r.driver.name, sub: r.driver.vehicle, target: { kind: "driver", id: r.driver.id } }] };
  }

  if (/dallal|today|did|handled|resolved|summary|happen|status|situation|دلال|دلّال|اليوم|ملخص|حالة|وضع|ماذا/.test(q)) {
    const resolved = Object.values(w.parcels).filter((p) => p.state === "prevented" || p.state === "recovered").length;
    const total = rows.reduce((n, r) => n + r.total, 0);
    const done = rows.reduce((n, r) => n + r.done, 0);
    const recent = w.events.slice(0, 4).map((e) => `• ${fmtTime(e.at)} ${e.text}`).join("\n");
    return { text: `${done} of ${total} parcels done · ${resolved} resolved by Dallal · ${w.cases.length} case${w.cases.length > 1 ? "s" : ""} today.${recent ? `\n${recent}` : ""}` };
  }

  if (/done|delivered|progress|how many/.test(q)) {
    const total = rows.reduce((n, r) => n + r.total, 0);
    const done = rows.reduce((n, r) => n + r.done, 0);
    return { text: `${done} of ${total} parcels are done across ${rows.length} drivers.` };
  }

  return { text: "Try asking about a parcel (DL-20417), a driver (Salem), or what needs attention." };
}
