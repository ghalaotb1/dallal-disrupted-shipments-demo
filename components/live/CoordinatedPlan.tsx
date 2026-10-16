"use client";

import { useCallback, useEffect, useState } from "react";
import { Network, RefreshCw, ShieldCheck, XCircle } from "lucide-react";
import { cn } from "@/lib/cn";
import { analystName } from "@/lib/live/payload";
import { planApi } from "@/lib/live/client";
import { buildPlanSnapshot } from "@/lib/live/plan";
import { Button } from "@/components/common/Button";
import { SimTag } from "@/components/common/Badges";
import { InquiryCard } from "@/components/live/InquiryCard";
import { LiveTag } from "@/components/live/LiveTags";
import { applyPlanToWorld } from "@/services/live/planEffects";
import { setPlan, useLive } from "@/store/live";

const STATUS: Record<string, { label: string; cls: string }> = {
  awaiting_evidence: { label: "Waiting for the dispatcher", cls: "bg-review-50 text-review-700 ring-review-200" },
  ready: { label: "Ready for supervisor approval", cls: "bg-brand-25 text-brand-700 ring-brand-200" },
  executed_simulated: { label: "Executed (simulated)", cls: "bg-ok-50 text-ok-700 ring-ok-200" },
  rejected: { label: "Rejected", cls: "bg-muted text-ink-3 ring-line" },
};

const sar = (n: number) => `${n >= 0 ? "" : "-"}${Math.abs(n).toFixed(0)}`;

/** Network-level recovery for a shared-cause incident: one question, one joint plan, one supervisor decision. */
export function CoordinatedPlan({ incidentId }: { incidentId: string }) {
  const connected = useLive((s) => s.status === "connected");
  const plan = useLive((s) => s.plans[incidentId]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const before = useLive((s) => s.planBefore[incidentId]);
  const changed = plan && plan.status !== "awaiting_evidence" && before ? Object.entries(plan.solution.per_parcel).filter(([k, v]) => before[k] !== v.option) : [];

  const create = useCallback(async () => {
    setBusy(true);
    setErr(null);
    try {
      setPlan(incidentId, await planApi.create(buildPlanSnapshot(incidentId)));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "request failed");
    } finally {
      setBusy(false);
    }
  }, [incidentId]);

  const refresh = useCallback(async () => {
    if (plan) setPlan(incidentId, await planApi.get(plan.plan_id));
  }, [incidentId, plan]);

  // Keep the plan current while it waits for a reply that may arrive through the webhook.
  useEffect(() => {
    if (!plan || plan.status !== "awaiting_evidence") return;
    const t = setInterval(() => void refresh().catch(() => undefined), 4000);
    return () => clearInterval(t);
  }, [plan, refresh]);

  async function decide(decision: "approve" | "reject") {
    if (!plan) return;
    setBusy(true);
    setErr(null);
    try {
      const next = await planApi.decide(plan.plan_id, { decision, by: analystName, role: "supervisor" });
      setPlan(incidentId, next);
      applyPlanToWorld(incidentId, next);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "request failed");
    } finally {
      setBusy(false);
    }
  }

  if (!connected) {
    return (
      <section className="rounded-xl border border-dashed border-line bg-surface px-5 py-4 shadow-card">
        <div className="flex items-center gap-2 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">
          <Network className="size-3.5" aria-hidden /> Coordinated network recovery
        </div>
        <p className="mt-1 text-xs text-ink-3">Needs the Dallal backend (not connected). The group response below is the in-browser demo planner.</p>
      </section>
    );
  }

  const st = plan ? (STATUS[plan.status] ?? { label: plan.status, cls: "bg-muted text-ink-3 ring-line" }) : null;
  const cmp = plan?.comparison;
  return (
    <section className="rounded-xl border border-brand-200 bg-surface shadow-card" aria-labelledby="coord-title">
      <header className="rounded-t-xl bg-brand-25 px-5 pt-4 pb-3">
        <div className="flex flex-wrap items-center gap-2 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">
          <Network className="size-3.5" aria-hidden /> Coordinated network recovery <LiveTag /> <SimTag />
          {st ? <span className={cn("ml-auto rounded-full px-1.5 py-px text-[10.5px] font-medium tracking-normal normal-case ring-1", st.cls)}>{st.label}</span> : null}
        </div>
        <h2 id="coord-title" className="mt-1 text-15 font-semibold text-ink">
          {plan ? `Joint plan for ${Object.keys(plan.solution.per_parcel).length} shipments` : "Plan all shipments together, not one by one"}
        </h2>
        <p className="mt-0.5 text-xs text-ink-2">
          Spare couriers, pickup capacity and van reroutes are shared across the incident, so options are chosen jointly. Spare/pickup resources are demo assumptions.
        </p>
      </header>

      <div className="space-y-3 px-5 py-3">
        {!plan ? (
          <Button size="sm" variant="primary" disabled={busy} onClick={create}>
            <RefreshCw className={cn(busy && "animate-spin")} /> Plan with the backend
          </Button>
        ) : (
          <>
            <p className="text-xs text-ink-2">
              P(blockage is long): <b>{Math.round(plan.p_long_prior * 100)}%</b>
              {plan.p_long !== plan.p_long_prior ? <> → <b>{Math.round(plan.p_long * 100)}%</b> after the answer</> : null}
              {plan.evidence.asked ? (
                <> · one shared question to the dispatcher, net value {plan.evidence.voi.net >= 0 ? "+" : ""}{plan.evidence.voi.net.toFixed(1)} SAR-eq, {Math.round(plan.evidence.p_response * 100)}% chance of a reply</>
              ) : (
                <> · not asking: {plan.evidence.reason}</>
              )}
            </p>

            {plan.inquiries.map((q) => (
              <InquiryCard key={q.inquiry_id} inquiry={q} onChanged={refresh} />
            ))}

            {plan.evidence.answer && before ? (
              <p className="rounded-md bg-brand-25 px-2.5 py-1.5 text-xs text-ink-2">
                The dispatcher&apos;s answer changed the decision for <b>{changed.length}</b> of {Object.keys(plan.solution.per_parcel).length} shipments
                {changed.length ? `: ${changed.slice(0, 4).map(([k, v]) => `${k} ${(before[k] ?? "?").split(":")[0]} → ${v.option.split(":")[0]}`).join(", ")}${changed.length > 4 ? "…" : ""}` : " (the plan was already right for both outcomes)"}.
              </p>
            ) : null}

            <ul className="divide-y divide-line-soft rounded-lg border border-line text-xs">
              {Object.entries(plan.solution.per_parcel).map(([pid, v]) => (
                <li key={pid} className="flex items-center gap-2 px-2.5 py-1.5">
                  <span className="font-mono text-ink-3">{pid}</span>
                  <span className="min-w-0 flex-1 truncate text-ink">{v.text}</span>
                  {plan.solution.committed_now[pid] && plan.status === "awaiting_evidence" ? <span className="text-2xs text-ok-700">safe now</span> : null}
                  <span className="font-mono text-ink-3">{sar(v.expected_utility)}</span>
                </li>
              ))}
            </ul>

            {cmp ? (
              <div className="rounded-lg border border-line bg-subtle px-3 py-2 text-xs text-ink-2">
                <p>
                  Expected utility <b>{sar(cmp.coordinated_utility)}</b> coordinated vs <b>{sar(cmp.independent_utility)}</b> if each shipment were handled independently
                  (<b>{cmp.gain >= 0 ? "+" : ""}{sar(cmp.gain)}</b> SAR-eq).
                </p>
                <p className="mt-0.5 text-ink-3">
                  Independent handling would over-book capacity by {cmp.independent_capacity_requests_over_cap} request(s) and make {cmp.independent_conflicting_van_decisions} conflicting van decision(s);
                  {" "}Messages: {cmp.messages_coordinated} coordinated (one shared question plus recipient notices) vs {cmp.messages_independent_equivalent} if every shipment asked on its own. Scored {cmp.assumption.replace(/^scored /, "")}.
                </p>
              </div>
            ) : null}

            {plan.status === "ready" ? (
              <div className="flex flex-wrap items-center gap-2">
                <Button size="sm" variant="primary" disabled={busy} onClick={() => decide("approve")}>
                  <ShieldCheck /> Approve as supervisor
                </Button>
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => decide("reject")}>
                  <XCircle /> Reject
                </Button>
                <span className="text-2xs text-ink-3">{plan.approval.why}</span>
              </div>
            ) : null}
            {plan.status === "executed_simulated" && plan.executed ? (
              <p className="text-xs text-ok-700">{plan.executed.length} actions recorded in the backend ledger (simulated execution).</p>
            ) : null}
          </>
        )}
        {err ? <p className="text-xs text-crit-700">{err}</p> : null}
      </div>
    </section>
  );
}
