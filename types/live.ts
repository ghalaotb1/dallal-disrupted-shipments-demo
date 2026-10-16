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
  env?: string;
  execution?: { mode: string; note: string };
  whatsapp?: { mode: string; send_requires_supervisor_approval: boolean; real_send_enabled: boolean };
  llm?: { backend: string; available: boolean; interpreter_active: boolean; interpreter_model: string; planner: string; models?: string[]; endpoint?: string; note?: string };
  ml?: { models: string[]; agent_scoring: string };
  persistence?: { db: string; backups: boolean; last_backup?: string | null; backup_error?: string | null };
  auth?: { api_key_required: boolean; roles: string };
  response_learning?: { enabled: boolean; prior_strength: number; learned: Record<string, { p_response: number; median_latency_min: number }> };
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
  interpretation?: { answer_id?: string | null; confidence?: number; method?: string; needs_review?: boolean; details?: { llm_suggestion?: { answer_id: string; confidence: number; model: string; note?: string } } } | null;
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

export interface LiveModelSummary {
  model_id: string;
  task_id: string;
  target: string;
  source: string;
  licence: string;
  algorithm: string;
  calibration: string;
  features: string[];
  split: { train: number; valid: number; test: number; train_prevalence: number; valid_prevalence: number; test_prevalence: number };
  test: { n: number; prevalence: number; roc_auc: number; pr_auc: number; "lift@top10%": number; brier: number; brier_prevalence_baseline: number; ece: number };
  test_auc_95ci: [number, number];
  trained_at: string;
  sha256: string;
  origin: string;
}

export interface LiveModelCard {
  model_id: string;
  features: { name: string; lo: number; hi: number; describe: string }[];
  caveats: string[];
  base_rate_valid: number;
  band_thresholds: { elevated: number; high: number };
  metrics: {
    test_calibration: { mean_predicted: number; observed: number; ece_uncalibrated_raw: number; ece_calibrated: number; reliability_deciles: { n: number; mean_predicted: number; observed: number }[] };
    valid_trials: Record<string, { valid_pr_auc: number; valid_roc_auc: number; n_features: number }>;
    chosen: { estimator: string; feature_set: string };
  };
  baselines: Record<string, { test_roc_auc: number; test_pr_auc: number }>;
}

export interface LiveScore {
  model_id: string;
  abstained: boolean;
  probability?: number;
  band?: string;
  lift_over_base_rate?: number;
  base_rate_source: number;
  reason?: string;
  features_outside_range?: string[];
  note?: string;
}

export interface LiveReplay {
  model_id: string;
  sample: string;
  sample_base_rate: number;
  rows: { features: Record<string, number>; probability: number | null; band: string | null; abstained: boolean; outcome: number }[];
}

export interface LiveReplay2 {
  case_id: string;
  label: string;
  source: string;
  accepted_at: string;
  as_of: string;
  timestamps_note: string;
  slow_threshold_min: number;
  steps: { tool: string; summary: string; facts: string[]; outcome: string | null; why: string; top: [string, number][] }[];
  risk: { source: string | null; band: string | null; probability: number | null; level: string | null; meta?: { features_as_of?: string; base_rate_source?: number; test_roc_auc?: number; trained_models_considered?: { model: string; status: string; code: string; detail?: string }[]; why_heuristic?: string } | null };
  decision: { type: string; headline: string; rationale: string; watch?: boolean; top_cause?: string; posterior?: number };
}

export interface LiveReplayOutcome {
  case_id: string;
  duration_min: number;
  slow_threshold_min: number;
  slow: boolean;
  note: string;
}
