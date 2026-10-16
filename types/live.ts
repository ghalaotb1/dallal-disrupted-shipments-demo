/** Contracts for the live Dallal backend (see backend/dallal/api). Everything here is produced by the backend, never by the browser. */

export interface LiveMeta {
  service: string;
  engine: string;
  decision_mode: string;
  whatsapp_mode: "sandbox" | "cloud";
  real_delivery_possible: boolean;
  time_scale: number;
  policy: string;
  utility: string;
  inquiry_catalogue: string;
  model_basis: string;
  assumptions: string[];
  notice: string;
}

export interface LiveMessage {
  direction: "in" | "out";
  status: string;
  kind: string;
  mode: string;
  wamid?: string | null;
  text?: string | null;
  buttons: { id: string; title: string }[];
  at: number;
  interpretation?: { answer_id?: string | null; confidence?: number; method?: string; needs_review?: boolean } | null;
}

export interface LiveInquiry {
  inquiry_id: string;
  run_id: string;
  subject_id: string;
  spec: string;
  target: string;
  scope: string;
  status: "awaiting" | "answered" | "timed_out" | "needs_review" | "opted_out" | "send_refused" | string;
  delivery_mode: "sandbox" | "cloud" | string;
  question: string;
  question_en?: string;
  answers: { id: string; title: string; title_en?: string }[];
  outcome: string | null;
  asked_real: number;
  deadline_real: number;
  answered_real: number | null;
  net_voi: number | null;
  p_response: number | null;
  real_delivery: boolean;
  messages: LiveMessage[];
}

export interface LiveEvent {
  id: number;
  ts: number;
  kind: string;
  subject_id: string | null;
  run_id: string | null;
  payload: Record<string, unknown>;
}

export interface LiveRunMeta {
  engine: string;
  planner: string;
  model_basis: string;
  data_origin: string | null;
  scenario_id: string | null;
  decision: { type?: string; reason?: string; action?: string; top_cause?: string; posterior?: number; p_systemic?: number; expected_utility?: number; decision_stability?: number; chosen_option?: string };
  utility_table: { option: string; eu: number; approval: string; delay_min: number; cost: number }[];
  virtual_minutes: number;
  whatsapp_mode?: string;
  inquiries: LiveInquiry[];
}

/** Compact snapshot of one shipment sent to the backend (the browser owns the simulated physical world). */
export interface LiveCase {
  now: number;
  trigger: { kind: string; detail?: string };
  shipment: {
    id: string;
    service: string;
    payment: { type: "Prepaid" } | { type: "COD"; amountSar: number };
    valueSar: number;
    merchant: string;
    recipientName: string;
    destLat: number;
    destLng: number;
    originId: string;
    originName: string;
    originLat: number;
    originLng: number;
    corridorId: string;
    courier?: { id: string; vehicle: string };
    createdAt: number;
    window: { start: number; end: number };
    exception?: { code: string; label: string; recordedAt: number };
    altRoute: boolean;
  };
  journey: { at: number; title: string; detail?: string; source: string; tone: string; code?: string }[];
  context: unknown;
  vehicle?: { lat: number; lng: number; stationarySince?: number };
  corridorBaseline?: { mean: number; std: number };
  peers: { id: string; corridorId: string; originId: string; exceptionAt?: number; code?: string; delivered?: boolean }[];
}

export interface LivePlan {
  plan_id: string;
  status: "awaiting_evidence" | "ready" | "executed_simulated" | "rejected" | string;
  incident: { id?: string; scope?: string; scope_id?: string };
  p_long_prior: number;
  p_long: number;
  evidence: {
    asked: boolean;
    reason: string;
    p_response: number;
    expected_latency_min: number;
    contactable: boolean;
    voi: { gross: number; cost: number; net: number; plan_now_objective: number; committed_now?: Record<string, string> };
    by_answer: Record<string, { p: number; posterior_long?: number; objective: number }>;
    answer?: { id: string | null; elapsed_min?: number; posterior_long?: number; note?: string };
  };
  solution: {
    assignments: Record<string, string>;
    reroute_vans: string[];
    spares_used: string[];
    objective: number;
    solve_ms: number;
    per_parcel: Record<string, { option: string; text: string; expected_utility: number }>;
    committed_now: Record<string, string>;
  };
  comparison: {
    coordinated_utility: number;
    independent_utility: number;
    gain: number;
    independent_capacity_requests_over_cap: number;
    independent_conflicting_van_decisions: number;
    messages_coordinated: number;
    messages_independent_equivalent: number;
    assumption: string;
  };
  approval: { required: string; why: string };
  executed?: { parcel: string; action_id: string; option: string }[];
  inquiries: LiveInquiry[];
  live: { backend: boolean; whatsapp_mode: string; scored_with: string };
}

export interface PlanSnapshot {
  incidentId: string;
  scope: string;
  scopeId: string;
  now: number;
  belief: { pLong: number };
  dispatcherContactable: boolean;
  parcels: { id: string; van: string; value: number; slackMin: number; remainingMin: number; service: string; exposed: boolean; pickupOk: boolean; reachable: boolean }[];
  resources: {
    spares: { id: string; etaMin: number; capacity: number }[];
    pickups: { id: string; travelMin: number; capacity: number; online: boolean }[];
    alt: { available: boolean; extraMin: number };
  };
}
