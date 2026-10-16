"""Initial ML task definitions for Dallal.

Each task states what is predicted, when (as_of), from what, how it is split, and which fields are banned. `status` is honest
about what the available data can support. Baselines for the first four are in dallal.ml.baselines and docs/ml/BASELINES.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MLTask:
    id: str
    question: str
    source: str
    unit: str
    as_of: str
    label: str
    split: str
    metrics: tuple[str, ...]
    banned: tuple[str, ...] = ()
    agent_tool: str | None = None  # which agent tool a trained model would back
    status: str = "baseline"  # baseline | defined | blocked_no_labels
    notes: tuple[str, ...] = field(default_factory=tuple)


TASKS: tuple[MLTask, ...] = (
    MLTask("olist_late_at_handoff", "Will this order be delivered after the promised date, given everything known at carrier hand-off?",
           "olist", "order", "carrier hand-off timestamp", "delivered calendar day > promised calendar day (6.8%)",
           "chronological 65/15/20 on as_of day, 30-day embargo, edge months (<500 labelled) dropped",
           ("pr_auc", "lift@top10%", "recall@top10%", "brier", "ece"), ("customer_delivered", "days_late", "review_score", "order_status"),
           "predict_risk", notes=("Coarse milestones only; trained model cannot see scans.", "Right-censored edge months excluded.")),
    MLTask("amazon_package_failed_attempt", "Will this package have a non-delivered visit on its route, given the plan at departure?",
           "amazon_lmrrc", "package", "planned route departure", "any visit with scan_status != DELIVERED (0.75%)",
           "chronological by service day, 1-day embargo (same-day outcomes invisible to history features)",
           ("pr_auc", "lift@top10%", "recall@top10%", "brier", "ece"), ("route_score", "seq_actual", "scan_status"), "predict_risk",
           notes=("Failure reason is not observed: this is attempt-failure RISK, not diagnosis.",)),
    MLTask("lade_slow_delivery_task", "Will this delivery task take longer than the training-period P90 for its city?",
           "lade", "task", "courier accept time", "duration(accept->deliver) > train P90 (engineered; threshold from train only)",
           "chronological on accept time (65/15/20), city-level",
           ("pr_auc", "lift@top10%", "roc_auc"), ("delivery_time", "delivery_gps_*"), "predict_risk",
           notes=("Proxy for stalled/slow shipments; LaDe has no failure labels.",)),
    MLTask("lade_pickup_late_vs_window", "Will the pickup happen after the promised window ends?", "lade", "pickup task", "courier accept time",
           "pickup_time > time_window_end (0.2-0.5%)", "chronological", ("pr_auc", "recall@top10%"), ("pickup_time", "pickup_gps_*"), "predict_risk",
           status="defined", notes=("Very rare event; baseline deferred until a precision target is agreed with operations.",)),
    MLTask("route_deviation_stop_displaced", "Will this stop be visited out of its planned position?", "route_deviation", "stop", "route plan time",
           "planned index != actual index (54%)", "chronological by week", ("roc_auc", "pr_auc"), ("seq_actual", "arrival_offset_s", "DistanceA"),
           "get_route_context", status="defined", notes=("Canonical stop table currently omits planned distance features; add before baselining.",)),
    MLTask("incident_detection", "Is the current failure rate in this scope a statistically abnormal surge?", "lade (real noise) + injected incidents", "scope x window",
           "end of window", "no real labels: evaluated by injecting synthetic surges into real baselines", "rolling baseline, train-period statistics only",
           ("detection_rate", "detection_delay", "false_alarms_per_scope_week"), (), "check_incident_context", status="baseline",
           notes=("Real noise, synthetic signal: measures detector behaviour, not real incident frequency.",)),
    MLTask("cause_classification", "What is the root cause of this disruption?", "none", "shipment", "decision time", "NOT AVAILABLE: no public root-cause labels",
           "-", (), (), "analyze_disruption", status="blocked_no_labels",
           notes=("The agent uses an expert-assumption Bayesian model; re-estimate from SPL exception + resolution logs when available.",)),
    MLTask("recovery_uplift", "Which action most improves this shipment's outcome?", "none", "shipment x action", "decision time",
           "NOT AVAILABLE: no public action->outcome data", "-", (), (), "rank_recovery_actions", status="blocked_no_labels",
           notes=("Needs randomised low-risk pilot or SPL intervention logs; see ledger contract.",)),
)
