import { demoAgentService } from "@/services/demo/agentService";
import { liveAgentService } from "@/services/live/liveAgentService";
import { getLive } from "@/store/live";
import { demoAssistantService } from "@/services/demo/assistantService";
import { demoIncidentService } from "@/services/demo/incidentService";
import { demoNotificationService } from "@/services/demo/notificationService";
import { demoRiskService } from "@/services/demo/riskService";
import { demoShipmentService } from "@/services/demo/shipmentService";
import type { AgentService, AssistantService, IncidentService, NotificationService, RiskService, ShipmentService } from "@/services/contracts";

/**
 * Service registry. Swap these bindings for API-backed adapters in the next
 * phase (e.g. `apiShipmentService`) — components import only from here.
 */
export const shipmentService: ShipmentService = demoShipmentService;
export const riskService: RiskService = demoRiskService;
export const incidentService: IncidentService = demoIncidentService;
/**
 * Agent: the live backend when it is reachable, otherwise the in-browser prototype. The decision is made per call so the app keeps
 * working (and says "Simulated") when the backend is down or not configured.
 */
export const agentService: AgentService = {
  investigate: (id) => (getLive().status === "connected" ? liveAgentService.investigate(id) : demoAgentService.investigate(id)),
  execute: (id, actionId, opts) => (getLive().status === "connected" ? liveAgentService.execute(id, actionId, opts) : demoAgentService.execute(id, actionId, opts)),
};
export const assistantService: AssistantService = demoAssistantService;
export const notificationService: NotificationService = demoNotificationService;
