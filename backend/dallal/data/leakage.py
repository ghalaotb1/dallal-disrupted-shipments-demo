"""Target-leakage guards for feature construction.

Three mechanical defences:
  1. Banned fields per task: columns recorded after the prediction instant, or that are the label in disguise.
  2. Point-in-time filtering: `visible_events` returns only events with ts <= as_of (or day_index <= as_of_day).
  3. Audit: `assert_features_clean` fails loudly if a feature frame contains a banned column or a column derived from one.

Tests in tests/test_leakage.py exercise all three on synthetic frames and, when data is present, on real canonical tables.
"""

from __future__ import annotations

import pandas as pd

BANNED: dict[str, set[str]] = {
    # Olist: everything recorded at/after delivery, the promise-relative outcomes, and review (post-delivery).
    "olist_late_delivery_at_handoff": {
        "customer_delivered", "order_delivered_customer_date", "actual_delivery_days", "days_late", "review_score",
        "order_status", "late", "delivered_ts",
    },
    # Amazon: the executed route's quality score and the actual outcome statuses are post-hoc.
    "amazon_package_failed_attempt": {"plan_quality", "route_score", "scan_status", "outcome", "attempt_outcome", "seq_actual"},
    "lade_delivery_task_duration_min": {"delivery_time", "delivery_gps_time", "delivery_gps_lng", "delivery_gps_lat", "done_ts"},
    "lade_pickup_late_vs_window": {"pickup_time", "pickup_gps_time", "pickup_gps_lng", "pickup_gps_lat", "done_ts"},
    "route_deviation_stop_late": {"arrival_offset_s", "seq_actual"},
}
BANNED_SUBSTRINGS = ("label", "target", "outcome")


class LeakageError(AssertionError):
    pass


def banned_columns(task: str, columns: list[str]) -> list[str]:
    banned = BANNED.get(task, set())
    return sorted(c for c in columns if c in banned or any(s in c.lower() for s in BANNED_SUBSTRINGS))


def assert_features_clean(task: str, features: pd.DataFrame) -> None:
    bad = banned_columns(task, list(features.columns))
    if bad:
        raise LeakageError(f"{task}: leaking columns in feature frame: {bad}")


def visible_events(events: pd.DataFrame, *, as_of_ts: pd.Timestamp | None = None, as_of_day: int | None = None) -> pd.DataFrame:
    """Events knowable at the prediction instant.

    * Timestamped events are visible iff ts <= as_of_ts.
    * Untimed (day-only) events are visible iff their day_index is STRICTLY earlier than the prediction day, because we
      cannot know whether a same-day event happened before or after the prediction instant. `as_of_day` is therefore
      required whenever the frame contains untimed events.
    """
    if as_of_ts is None and as_of_day is None:
        raise ValueError("pass as_of_ts and/or as_of_day")
    has_ts = events["ts"].notna()
    keep = pd.Series(False, index=events.index)
    if as_of_ts is not None:
        keep |= has_ts & (events["ts"] <= as_of_ts)
    if as_of_day is not None:
        keep |= ~has_ts & events["day_index"].notna() & (events["day_index"] < as_of_day)
    elif (~has_ts).any():
        raise ValueError("frame has untimed events; as_of_day is required to decide their visibility")
    return events[keep]


def assert_label_after_features(labels: pd.DataFrame) -> None:
    """Every label must resolve strictly after (or, for day-granular sources, no earlier than) its prediction instant."""
    has_ts = labels["as_of_ts"].notna() & labels["available_at_ts"].notna()
    if (labels.loc[has_ts, "available_at_ts"] <= labels.loc[has_ts, "as_of_ts"]).any():
        raise LeakageError("label resolves at or before prediction instant")
    has_d = labels["as_of_day_index"].notna() & labels["available_at_day_index"].notna()
    if (labels.loc[has_d, "available_at_day_index"] < labels.loc[has_d, "as_of_day_index"]).any():
        raise LeakageError("label day precedes prediction day")


def history_rate(df: pd.DataFrame, key: str, label: str, day: str, *, as_of_day: int, window: int | None = None, prior: float = 0.0, prior_n: float = 20.0) -> pd.Series:
    """Smoothed historical positive rate per `key` using ONLY rows with day < as_of_day (strictly earlier days).

    This is the pattern for 'zone/seller historical failure rate' features: computed from the past, shrunk toward `prior`.
    """
    past = df[df[day] < as_of_day]
    if window is not None:
        past = past[past[day] >= as_of_day - window]
    g = past.groupby(key)[label].agg(["sum", "count"])
    return (g["sum"] + prior * prior_n) / (g["count"] + prior_n)


def assert_no_label_proxy(features: pd.DataFrame, y, *, max_single_auc: float = 0.98) -> None:
    """Behavioural leakage guard that does not depend on column names.

    A genuine pre-decision feature of a noisy real-world outcome essentially never predicts it near-perfectly on its own. If
    one does, it is the label (or a deterministic function of it) under another name — e.g. a merge-suffix collision.
    """
    import numpy as np
    from sklearn.metrics import roc_auc_score

    y = np.asarray(y)
    if len(set(y.tolist())) < 2:
        return
    for c in features.columns:
        v = features[c].to_numpy(dtype="float64", na_value=np.nan) if hasattr(features[c], "to_numpy") else features[c]
        m = ~np.isnan(v)
        if m.sum() < 200 or len(set(y[m].tolist())) < 2:
            continue
        a = roc_auc_score(y[m], v[m])
        if max(a, 1 - a) >= max_single_auc:
            raise LeakageError(f"feature '{c}' alone gives AUC {max(a, 1 - a):.3f} >= {max_single_auc}: it is almost certainly the label in disguise")
