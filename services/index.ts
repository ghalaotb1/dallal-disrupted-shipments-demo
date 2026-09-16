import { demoAgentService } from "@/services/demo/agentService";
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
export const agentService: AgentService = demoAgentService;
export const assistantService: AssistantService = demoAssistantService;
export const notificationService: NotificationService = demoNotificationService;
