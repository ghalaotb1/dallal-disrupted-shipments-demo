"use client";

import { useMemo } from "react";
import { ArrowRight, Network, ShieldCheck, UserCheck, XCircle } from "lucide-react";
import { places } from "@/data/network";
import { cn } from "@/lib/cn";
import { decidePlan, MANAGER_NAME } from "@/lib/ops/agent";
import { setUi, useOps, useOpsUi } from "@/store/ops";
import { Button } from "@/components/common/Button";
import { ReplyDevice } from "@/components/ops/ReplyDevice";
import { SimTag } from "@/components/ops/Chips";
import type { LivePlan } from "@/types/live";

const refLabel = (kind: string, ref: string) => (kind === "pickup" ? (places[ref]?.short ?? ref) : ref);
const sar = (n: number) => `${n < 0 ? "-" : ""}${Math.abs(Math.round(n)).toLocaleString("en-US")}`;
const KIND_STYLE: Record<string, string> = {
  wait: "bg-ok-50 text-ok-700 ring-ok-100",
  spare: "bg-brand-50 text-brand-700 ring-brand-100",
  pickup: "bg-review-50 text-review-700 ring-review-100",
  defer: "bg-warn-50 text-warn-700 ring-warn-100",
  reroute: "bg-brand-50 text-brand-700 ring-brand-100",
};
const KIND_LABEL: Record<string, string> = { wait: "Wait", spare: "Spare courier", pickup: "Pickup point", defer: "Reschedule", reroute: "Reroute" };

/** The joint recovery plan for a shared disruption, grouped by the driver who carries each parcel. */
export function PlanCard({ planId, mode }: { planId: string; mode: "operator" | "manager" }) {
  const plan = useOps((s) => s.plans[planId]);
  const parcels = useOps((s) => s.parcels);
  const drivers = useOps((s) => s.drivers);
  const before = useOps((s) => s.planBefore[planId]);
  const busy = useOpsUi((s) => s.busy === "plan");
  const groups = useMemo(() => {
    if (!plan) return [];
    const by: Record<string, string[]> = {};
    for (const pid of Object.keys(plan.solution.per_parcel)) (by[parcels[pid]?.driverId ?? "?"] ??= []).push(pid);
    return Object.entries(by).map(([d, ids]) => ({ driver: drivers[d], ids: ids.sort((a, b) => (parcels[a]?.seq ?? 0) - (parcels[b]?.seq ?? 0)) }));
  }, [plan, parcels, drivers]);
  if (!plan) return null;
  const total = Object.keys(plan.solution.per_parcel).length;
  const answered = plan.status !== "awaiting_evidence";
  const changed = answered && before ? Object.entries(plan.solution.per_parcel).filter(([k, v]) => before[k] && before[k] !== v.option).map(([k]) => k) : [];
  const cmp = plan.comparison;
  const q = plan.inquiries[0];
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Network className="size-4 text-brand-600" aria-hidden />
        <h3 className="text-sm font-semibold text-ink">
          One plan for {total} parcels on {groups.length} drivers
        </h3>
        <StatusPill plan={plan} />
      </div>

      <p className="text-xs leading-5 text-ink-2">
        Spare couriers and pickup capacity are shared, so Dallal chooses every parcel&apos;s option <b>together</b>. Chance the blockage is long: <b>{Math.round(plan.p_long_prior * 100)}%</b>
        {answered && plan.p_long !== plan.p_long_prior ? (
          <>
            {" "}
            <ArrowRight className="inline size-3" aria-hidden /> <b>{Math.round(plan.p_long * 100)}%</b> after the dispatcher answered
          </>
        ) : null}
        .
      </p>

      {q ? (
        <div className="space-y-1.5">
          <p className="text-xs text-ink-3">
            {plan.evidence.asked ? (
              <>
                <b className="text-ink">One question</b> to the dispatcher covers all {total} parcels (instead of {cmp.messages_independent_equivalent} separate messages). Worth asking: +{plan.evidence.voi.net.toFixed(0)} SAR-eq net, {Math.round(plan.evidence.p_response * 100)}% chance of a reply.
              </>
            ) : null}
          </p>
          {mode === "operator" || q.status !== "awaiting" ? <ReplyDevice inquiry={q} plan={planId} suggested="blocked_long" /> : <p className="rounded-lg bg-muted px-3 py-2 text-xs text-ink-3">Waiting for the dispatcher&apos;s answer.</p>}
        </div>
      ) : null}

      {answered && before ? (
        <p className="rounded-lg bg-brand-25 px-3 py-2 text-xs text-ink-2 ring-1 ring-brand-100">
          The dispatcher&apos;s answer changed the plan for <b>{changed.length}</b> of {total} parcels
          {changed.length ? ` (${changed.slice(0, 3).map((k) => `${k.replace("DL-", "")}: ${(before[k] ?? "").split(":")[0]} → ${plan.solution.per_parcel[k].option.split(":")[0]}`).join(", ")}${changed.length > 3 ? "…" : ""})` : ""}.
        </p>
      ) : null}

      <div className="space-y-2">
        {groups.map(({ driver, ids }) => (
          <div key={driver?.id ?? "?"} className="overflow-hidden rounded-lg border border-line">
            <div className="flex items-center gap-2 bg-subtle px-3 py-1.5 text-xs">
              <span className="flex size-5 items-center justify-center rounded-full bg-ink text-[10px] font-semibold text-white">{driver?.name[0]}</span>
              <b className="text-ink">{driver?.name}</b>
              <span className="font-mono text-ink-4">{driver?.vehicle}</span>
              <span className="ml-auto text-ink-3">{ids.length} parcels</span>
            </div>
            <ul className="divide-y divide-line-soft">
              {ids.map((pid) => {
                const v = plan.solution.per_parcel[pid];
                const kind = v.option.split(":")[0];
                const flipped = changed.includes(pid);
                return (
                  <li key={pid} className="flex items-center gap-2 px-3 py-1.5 text-xs">
                    <span className="w-[64px] shrink-0 font-mono whitespace-nowrap text-ink-4">{pid}</span>
                    <span className="min-w-0 flex-1 truncate text-ink-2">{parcels[pid]?.address.district}</span>
                    <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset", KIND_STYLE[kind] ?? "bg-muted text-ink-3 ring-line")}>
                      {KIND_LABEL[kind] ?? kind}
                      {v.option.includes(":") ? ` ${refLabel(kind, v.option.split(":")[1])}` : ""}
                    </span>
                    {flipped ? <span className="shrink-0 text-[10px] font-semibold text-brand-700">changed</span> : null}
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>

      <p className="text-xs leading-5 text-ink-3">
        Expected value <b className="text-ink">{sar(cmp.coordinated_utility)}</b> planned together vs <b className="text-ink">{sar(cmp.independent_utility)}</b> handling each parcel on its own. Spare couriers, pickup points and promise windows are demo assumptions <SimTag />.
      </p>

      {plan.status === "ready" ? (
        mode === "manager" ? (
          <div className="rounded-xl border border-review-200 bg-review-50 p-3">
            <p className="text-xs text-review-700">
              <b>Why a manager?</b> {plan.approval.why}. Policy requires supervisor approval for group actions.
            </p>
            <div className="mt-2.5 flex flex-wrap gap-2">
              <Button variant="review" size="md" loading={busy} onClick={() => decidePlan(planId, "approve")}>
                <ShieldCheck /> Approve plan
              </Button>
              <Button variant="secondary" size="md" disabled={busy} onClick={() => decidePlan(planId, "reject")}>
                <XCircle /> Reject
              </Button>
              <span className="self-center text-xs text-ink-3">as {MANAGER_NAME}</span>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-3 rounded-xl border border-review-200 bg-review-50 p-3">
            <UserCheck className="size-5 shrink-0 text-review-600" aria-hidden />
            <p className="flex-1 text-xs text-review-700">
              <b>Waiting for the manager.</b> A group plan needs supervisor approval; an operator cannot approve it.
            </p>
            <Button size="sm" variant="review" onClick={() => setUi({ role: "manager" })}>
              Open manager view
            </Button>
          </div>
        )
      ) : null}
      {plan.status === "executed_simulated" ? (
        <p className="rounded-lg bg-ok-50 px-3 py-2 text-xs text-ok-700 ring-1 ring-ok-100">
          Approved and executed <b>in simulation</b>: {summary(plan)}. {plan.executed?.length ?? total} actions are in the ledger; delivery outcomes are still pending.
        </p>
      ) : null}
      {plan.status === "rejected" ? <p className="rounded-lg bg-muted px-3 py-2 text-xs text-ink-3">The manager rejected this plan. Nothing was executed.</p> : null}
    </div>
  );
}

function summary(plan: LivePlan): string {
  const c: Record<string, number> = {};
  for (const v of Object.values(plan.solution.per_parcel)) c[v.option.split(":")[0]] = (c[v.option.split(":")[0]] ?? 0) + 1;
  return Object.entries(c).map(([k, n]) => `${n} ${k === "spare" ? "to spare couriers" : k === "pickup" ? "to pickup points" : k === "wait" ? "wait for the lane" : k === "defer" ? "rescheduled" : k}`).join(", ");
}

function StatusPill({ plan }: { plan: LivePlan }) {
  const map: Record<string, { t: string; c: string }> = {
    awaiting_evidence: { t: "Asking the dispatcher", c: "bg-review-50 text-review-700 ring-review-200" },
    ready: { t: "Needs manager approval", c: "bg-review-50 text-review-700 ring-review-200" },
    executed_simulated: { t: "Executed (simulated)", c: "bg-ok-50 text-ok-700 ring-ok-200" },
    rejected: { t: "Rejected", c: "bg-muted text-ink-3 ring-line" },
  };
  const s = map[plan.status] ?? { t: plan.status, c: "bg-muted text-ink-3 ring-line" };
  return <span className={cn("ml-auto rounded-full px-2 py-0.5 text-[11px] font-medium ring-1", s.c)}>{s.t}</span>;
}
