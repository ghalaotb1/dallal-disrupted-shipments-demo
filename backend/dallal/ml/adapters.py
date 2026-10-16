"""Adapters: canonical operational bundle -> a trained model's feature row, or an explicit, coded ABSTENTION.

Principles (they are what makes the bridge responsible rather than merely convenient):
  1. Domain gate. A model scores only records from the source system it was trained on (`card.valid_domains`) and only OBSERVED/ENGINEERED data. A
     demo, synthetic or other-country record is refused even if its numbers happen to fall inside the training ranges.
  2. Point in time. Every feature is computed as of the instant the model was trained to predict at (e.g. task acceptance), using only rows with
     `ts <= as_of` from the bundle and `available_at < t` from the point-in-time store. The label's own information is never an input.
  3. Target not yet determined. If the outcome is already known or already decided (task delivered, or longer than the slow threshold), the model abstains.
  4. No imputation. Any missing input is an abstention naming it. The registry additionally abstains outside the training range.
Every result is machine-readable: status, code, detail, missing[] - and shown to operators next to the heuristic they fall back to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import pandas as pd

from dallal.ml.pit import NullStore, PointInTimeStore
from dallal.tools.bundle import Bundle
from dallal.tools.signals import haversine_m

REAL_ORIGINS = {"observed", "engineered"}


@dataclass
class Outcome:
    features: dict[str, float] | None = None
    code: str = "ok"  # ok | domain_mismatch | no_shipment | missing_input | target_known | target_decided | no_point_in_time_store | not_bridged
    detail: str = ""
    missing: list[str] = field(default_factory=list)
    as_of_used: str | None = None  # the instant the features describe (<= bundle.as_of)

    @property
    def ok(self) -> bool:
        return self.features is not None


def abstain(code: str, detail: str, missing: list[str] | None = None) -> Outcome:
    return Outcome(None, code, detail, missing or [])


class Adapter(Protocol):
    model_id: str

    def build(self, world: Bundle, shipment_id: str, card: Any, store: PointInTimeStore) -> Outcome: ...


def _domain_gate(row: dict[str, Any], card: Any) -> Outcome | None:
    src, origin = str(row.get("source_id")), str(row.get("origin"))
    if not card.valid_domains:
        return abstain("not_bridged", f"{card.model_id} has no valid scoring domain: its inputs are not available from an operational bundle")
    if src not in card.valid_domains or origin not in REAL_ORIGINS:
        return abstain("domain_mismatch", f"{card.model_id} was trained on {card.valid_domains} real data; this case is source={src}, origin={origin}")
    return None


class LadeSlowTaskAdapter:
    model_id = "lade_slow_task_v1"

    def build(self, world: Bundle, shipment_id: str, card: Any, store: PointInTimeStore) -> Outcome:
        try:
            row = world.shipment(shipment_id)
        except KeyError:
            return abstain("no_shipment", "shipment not in the bundle")
        g = _domain_gate(row, card)
        if g:
            return g
        ev = world.events(shipment_id)  # already filtered to ts <= as_of
        acc = ev[ev["event_type"] == "accepted"]
        if acc.empty:
            return abstain("missing_input", "no 'accepted' event at or before as_of", ["accepted_event"])
        if (ev["event_type"] == "delivered").any():
            return abstain("target_known", "the task is already delivered: its duration is known, nothing to predict")
        a = acc.iloc[0]
        t = pd.Timestamp(a["ts"])
        thr = float(card.extra.get("slow_threshold_min", 1e9))
        elapsed = (world.as_of - t).total_seconds() / 60.0
        if elapsed > thr:
            return abstain("target_decided", f"{elapsed:.0f} min since acceptance already exceeds the slow threshold ({thr:.0f} min): the event this model predicts has happened")
        missing = [k for k, v in (("dest_zone_type", row.get("dest_zone_type")), ("dest_zone_id", row.get("dest_zone_id")), ("dest_region", row.get("dest_region")), ("courier_id", row.get("courier_id")),
                                  ("accept_lat", a.get("lat")), ("accept_lng", a.get("lng")), ("dest_lat", row.get("dest_lat")), ("dest_lng", row.get("dest_lng"))) if v is None or pd.isna(v)]
        if missing:
            return abstain("missing_input", "required inputs absent: " + ", ".join(missing), missing)
        if isinstance(store, NullStore):
            return abstain("no_point_in_time_store", "no point-in-time history store is configured (needs resolved-task history and courier workload as of acceptance)", ["history", "open_tasks"])
        open_n = store.open_tasks(str(row["courier_id"]), t)
        hist = {k: store.past_mean_logdur(k, str(row[c]), t) for k, c in (("aoi", "dest_zone_id"), ("courier", "courier_id"), ("region", "dest_region"))}
        if open_n is None or any(v is None for v in hist.values()):
            return abstain("missing_input", "the point-in-time store has no record for this courier", ["open_tasks" if open_n is None else "history"])
        try:
            zone_type = float(row["dest_zone_type"])
        except (TypeError, ValueError):
            return abstain("missing_input", "dest_zone_type is not numeric", ["dest_zone_type"])
        f = {"hour": float(t.hour), "dow": float(t.dayofweek), "aoi_type": zone_type, "open_tasks_courier": float(open_n),
             "accept_dist_m": float(haversine_m(float(a["lat"]), float(a["lng"]), float(row["dest_lat"]), float(row["dest_lng"])))}
        for k in ("aoi", "courier", "region"):
            f[f"{k}_past_logdur"], f[f"{k}_past_n"] = hist[k]  # type: ignore[misc]
        return Outcome(f, as_of_used=t.isoformat())


class AmazonFailedAttemptAdapter:
    model_id = "amazon_failed_attempt_v1"

    def build(self, world: Bundle, shipment_id: str, card: Any, store: PointInTimeStore) -> Outcome:
        try:
            row = world.shipment(shipment_id)
        except KeyError:
            return abstain("no_shipment", "shipment not in the bundle")
        g = _domain_gate(row, card)
        if g:
            return g
        routes, stops, ships = world.tables.get("route"), world.tables.get("stop"), world.shipments()
        if routes is None or stops is None or routes.empty or stops.empty:
            return abstain("missing_input", "the route plan (route and stop tables) is not in the bundle", ["route_plan"])
        r = routes[routes["route_id"] == row.get("route_id")]
        s = stops[stops["stop_id"] == row.get("stop_id")]
        if r.empty or s.empty:
            return abstain("missing_input", "this shipment's route or stop is not in the plan", ["route", "stop"])
        r, s = r.iloc[0], s.iloc[0]
        dep = r.get("planned_departure_ts")
        if dep is None or pd.isna(dep) or pd.Timestamp(dep) > world.as_of:
            return abstain("missing_input", "planned departure is unknown or after as_of (the plan was not yet known)", ["planned_departure_ts"])
        need = {"volume_cm3": row.get("volume_cm3"), "planned_service_s": s.get("planned_service_s"), "n_stops": r.get("n_stops"), "capacity": r.get("capacity")}
        missing = [k for k, v in need.items() if v is None or pd.isna(v)]
        if missing:
            return abstain("missing_input", "required plan inputs absent: " + ", ".join(missing), missing)
        pk_stop = int((ships["stop_id"] == row["stop_id"]).sum())
        pk_route = int((ships["route_id"] == row["route_id"]).sum())
        pe, ps = row.get("promised_end_ts"), row.get("promised_start_ts")
        has_w = pe is not None and not pd.isna(pe)
        window_h = float((pd.Timestamp(pe) - pd.Timestamp(ps)).total_seconds() / 3600) if has_w and ps is not None and not pd.isna(ps) else 0.0
        d = pd.Timestamp(dep)
        f = {"volume_cm3": float(need["volume_cm3"]), "planned_service_s": float(need["planned_service_s"]), "pk_at_stop": float(pk_stop), "pk_on_route": float(pk_route), "n_stops": float(need["n_stops"]),
             "capacity": float(need["capacity"]), "load_ratio": pk_route / float(need["n_stops"]), "has_window": float(has_w), "window_h": window_h, "dep_hour": float(d.hour), "dep_dow": float(d.dayofweek),
             "svc_per_pkg": float(need["planned_service_s"]) / pk_stop}
        return Outcome(f, as_of_used=d.isoformat())


class OlistAdapter:
    """Deliberately not bridged: the model needs payment-approval timestamps, freight value and item counts that an operational parcel bundle does not carry."""

    model_id = "olist_late_at_handoff_v1"

    def build(self, world: Bundle, shipment_id: str, card: Any, store: PointInTimeStore) -> Outcome:
        return abstain("not_bridged", "needs e-commerce order fields (payment approval time, freight value, item count) that SPL-style parcel data does not provide")


ADAPTERS: dict[str, Adapter] = {a.model_id: a for a in (LadeSlowTaskAdapter(), AmazonFailedAttemptAdapter(), OlistAdapter())}
