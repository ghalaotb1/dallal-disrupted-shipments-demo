"use client";

import Link from "next/link";
import { useCallback } from "react";
import { PackageSearch } from "lucide-react";
import { agentService } from "@/services";
import { useDemoNow } from "@/hooks/useDemoNow";
import { useShipmentCase } from "@/hooks/useShipmentCase";
import { useUi } from "@/store/ui";
import { EmptyState } from "@/components/common/Card";
import { AgentPanel } from "@/components/agent/AgentPanel";
import { DecisionBar } from "@/components/shipments/DecisionBar";
import { DiagnosisCard } from "@/components/shipments/DiagnosisCard";
import { JourneyTimeline } from "@/components/shipments/JourneyTimeline";
import { RecoveryActions } from "@/components/shipments/RecoveryActions";
import { ShipmentDetails } from "@/components/shipments/ShipmentDetails";
import { ShipmentHeader } from "@/components/shipments/ShipmentHeader";
import type { RecoveryAction } from "@/types/domain";

export function ShipmentIntelligence({ id }: { id: string }) {
  const c = useShipmentCase(id);
  const now = useDemoNow(1000);
  const set = useUi((x) => x.set);
  const busy = !!c.running;

  const investigate = useCallback(() => {
    if (!busy) void agentService.investigate(id);
  }, [busy, id]);
  const run = useCallback(
    (a: RecoveryAction) => {
      if (!busy) void agentService.execute(id, a.id);
    },
    [busy, id],
  );
  const escalate = useCallback(() => set({ escalation: { target: { type: "shipment", id }, runId: c.investigation?.id } }), [set, id, c.investigation?.id]);

  if (!c.shipment || !c.context) {
    return (
      <div className="p-6">
        <EmptyState
          icon={<PackageSearch />}
          title={`Shipment ${id} not found`}
          body="It may have been delivered and archived in this demo session, or the ID is mistyped."
          action={
            <Link href="/shipments" className="text-13 font-medium text-brand-700 hover:underline">
              Back to shipments
            </Link>
          }
        />
      </div>
    );
  }
  const s = c.shipment;

  return (
    <div className="mx-auto w-full max-w-[1480px] space-y-3 p-3 lg:p-4">
      <ShipmentHeader s={s} now={now} />
      <DecisionBar s={s} investigation={c.investigation} running={c.running} escalation={c.escalation} onInvestigate={investigate} onRun={run} onEscalate={escalate} />
      <div className="grid items-start gap-3 xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="min-w-0 space-y-3">
          <DiagnosisCard shipment={s} run={c.investigation?.diagnosis ? c.investigation : undefined} running={busy} onInvestigate={investigate} stale={c.stale} />
          <RecoveryActions shipment={s} run={c.investigation} busy={busy} onRun={run} onEscalate={escalate} />
          <JourneyTimeline events={c.journey} now={now} />
          <ShipmentDetails s={s} ctx={c.context} />
        </div>
        <div className="xl:sticky xl:top-[72px] xl:flex xl:max-h-[calc(100dvh-88px)] xl:flex-col">
          <AgentPanel investigation={c.investigation} execution={c.execution} running={c.running} onInvestigate={investigate} canInvestigate={!busy && !s.closed} incidentMode={!!s.incident} />
        </div>
      </div>
    </div>
  );
}
