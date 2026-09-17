"use client";

import { useMemo } from "react";
import { useWorld } from "@/store/world";
import type { AgentRun } from "@/types/domain";

/** Everything the Shipment Intelligence screen needs, derived from the shared world. */
export function useShipmentCase(id: string) {
  const shipment = useWorld((w) => w.shipments[id]);
  const journey = useWorld((w) => w.journeys[id]);
  const context = useWorld((w) => w.contexts[id]);
  const runsMap = useWorld((w) => w.agentRuns);
  const escalations = useWorld((w) => w.escalations);
  const incident = useWorld((w) => (shipment?.incident ? w.incidents[shipment.incident.id] : undefined));

  return useMemo(() => {
    const runs = Object.values(runsMap)
      .filter((r) => r.shipmentId === id)
      .sort((a, b) => a.startedAt - b.startedAt);
    const investigation = [...runs].reverse().find((r) => r.mode === "investigation");
    const execution = [...runs].reverse().find((r) => r.mode === "execution" && (!investigation || r.startedAt >= investigation.startedAt));
    const running: AgentRun | undefined = runs.find((r) => r.status === "running");
    const escalation = escalations.find((e) => e.target.type === "shipment" && e.target.id === id);
    const resolvedByAction = !!execution && (shipment?.health === "prevented" || shipment?.health === "recovered" || shipment?.health === "recovering");
    const stale = !!investigation?.finishedAt && !!shipment && shipment.lastEventAt > investigation.finishedAt + 60_000 && !running && !resolvedByAction && !shipment.closed && shipment.agent.state !== "awaiting_supervisor";
    return { shipment, journey: journey ?? [], context, runs, investigation, execution, running, escalation, incident, stale, resolvedByAction };
  }, [id, shipment, journey, context, runsMap, escalations, incident]);
}
