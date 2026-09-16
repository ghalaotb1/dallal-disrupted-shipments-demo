import { assessRisk } from "@/services/logic/risk";
import { demoNow, getWorld } from "@/store/world";
import type { RiskService } from "@/services/contracts";

export const demoRiskService: RiskService = {
  async assess(shipmentId) {
    const w = getWorld();
    return assessRisk(w.shipments[shipmentId], w.contexts[shipmentId], demoNow());
  },
};
