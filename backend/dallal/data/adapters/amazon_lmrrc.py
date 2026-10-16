"""Amazon Last Mile Routing Research Challenge 2021 (training routes) -> canonical tables.

Provides REAL stop/package-level delivery outcomes: scan_status in {DELIVERED, DELIVERY_ATTEMPTED, REJECTED},
route and zone structure, optional promised time window, planned service time, package dimensions, and (for training
routes) the actual visit sequence. It does NOT provide: attempt timestamps, attempt counts, failure reasons, recipient
data. `failure_reason` therefore stays null. `route_score` (High/Medium/Low) is a *post-hoc* quality rating of the
executed route and is stored as `plan_quality` only so that the leakage guard can ban it from pre-dispatch features.

Repeated attempts are REAL here: ~1.4k packages are attempted at one stop and delivered (or re-attempted) at another
stop of the same route. `attempt_no` follows the actual visit order for training routes and is null for evaluation routes
(no actual sequence published). The 3,072 evaluation routes are NOT used: their package_data carries no scan_status.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from dallal.data.adapters.base import raw, with_provenance, write_tables
from dallal.data.schema import Origin

SOURCE = "amazon_lmrrc"
VERSION = "amazon-1.0"
METRO = {"DLA": "Los Angeles", "DBO": "Boston", "DSE": "Seattle", "DCH": "Chicago", "DAU": "Austin"}
STATUS_TO_OUTCOME = {"DELIVERED": "delivered", "DELIVERY_ATTEMPTED": "failed", "REJECTED": "rejected"}
STATUS_TO_EVENT = {"DELIVERED": "delivered", "DELIVERY_ATTEMPTED": "failed_attempt", "REJECTED": "rejected"}

PROVIDES = {
    "node": {"name", "city", "region"},
    "route": {"node_id", "service_date", "day_index", "planned_departure_ts", "n_stops", "capacity", "plan_quality"},
    "stop": {"route_id", "seq_actual", "lat", "lng", "zone_id", "planned_service_s"},
    "shipment": {"stop_id", "route_id", "origin_node_id", "promised_start_ts", "promised_end_ts", "dest_lat", "dest_lng",
                 "dest_zone_id", "volume_cm3", "day_index"},
    "event": {"ts", "ts_quality", "day_index", "raw_code", "node_id"},
    "attempt": {"stop_id", "attempt_no", "outcome", "ts_quality", "failure_reason"},
}


def _load(package_file: str, route_file: str, seq_file: str | None, split: str) -> dict[str, pd.DataFrame]:
    with open(raw(SOURCE, route_file)) as fh:
        routes_raw = json.load(fh)
    with open(raw(SOURCE, package_file)) as fh:
        pk_raw = json.load(fh)
    seqs = {}
    if seq_file:
        with open(raw(SOURCE, seq_file)) as fh:
            seqs = json.load(fh)

    r_rows, s_rows, n_rows = [], [], {}
    for rid, r in routes_raw.items():
        date = r["date_YYYY_MM_DD"]
        dep = pd.Timestamp(f"{date} {r['departure_time_utc']}")
        route_id = f"{SOURCE}:{rid}"
        node_id = f"{SOURCE}:station:{r['station_code']}"
        n_rows[node_id] = r["station_code"]
        actual = seqs.get(rid, {}).get("actual", {})
        r_rows.append((route_id, node_id, date, dep, len(r["stops"]), r["executor_capacity_cm3"], r.get("route_score")))
        for code, st in r["stops"].items():
            if st["type"] != "Dropoff":
                continue
            s_rows.append((f"{route_id}:{code}", route_id, actual.get(code), st["lat"], st["lng"], st["zone_id"]))

    routes = pd.DataFrame(r_rows, columns=["route_id", "node_id", "service_date", "planned_departure_ts", "n_stops",
                                           "capacity", "plan_quality"])
    d0 = pd.Timestamp("2018-07-01")
    routes["day_index"] = (pd.to_datetime(routes["service_date"]) - d0).dt.days
    stops = pd.DataFrame(s_rows, columns=["stop_id", "route_id", "seq_actual", "lat", "lng", "zone_id"])
    stops["seq_actual"] = stops["seq_actual"].astype("Int64")

    p_rows = []
    for rid, stops_d in pk_raw.items():
        route_id = f"{SOURCE}:{rid}"
        for code, pkgs in stops_d.items():
            stop_id = f"{route_id}:{code}"
            for pid, p in pkgs.items():
                tw = p["time_window"]
                d = p["dimensions"]
                p_rows.append((f"{SOURCE}:{pid}", stop_id, route_id, tw["start_time_utc"], tw["end_time_utc"],
                               p["planned_service_time_seconds"], d["depth_cm"] * d["height_cm"] * d["width_cm"],
                               p["scan_status"]))
    pk = pd.DataFrame(p_rows, columns=["shipment_id", "stop_id", "route_id", "w0", "w1", "svc", "vol", "status"])
    for c in ("w0", "w1"):
        pk[c] = pd.to_datetime(pk[c], errors="coerce")
    stops = stops.merge(pk.groupby("stop_id", as_index=False)["svc"].sum().rename(columns={"svc": "planned_service_s"}),
                        on="stop_id", how="left")
    stop_xy = stops.set_index("stop_id")[["lat", "lng", "zone_id"]]
    pk = pk.join(stop_xy, on="stop_id")
    pk = pk.join(routes.set_index("route_id")[["node_id", "day_index"]], on="route_id")

    # A package can appear at several stops of the same route (1,422 of ~1.46M in training): attempted at one stop,
    # delivered at another. That is real repeated-attempt behaviour, so: one shipment per package, one attempt per visit.
    pk["attempt_id"] = pk["shipment_id"] + ":" + pk["stop_id"].str.rsplit(":", n=1).str[-1]
    seq = stops.set_index("stop_id")["seq_actual"]
    pk["seq"] = pk["stop_id"].map(seq)
    pk = pk.sort_values(["shipment_id", "seq", "stop_id"], na_position="last")
    pk["attempt_no"] = pk.groupby("shipment_id").cumcount() + 1 if split == "training" else pd.NA
    multi = pk.groupby("shipment_id")["stop_id"].transform("size") > 1
    pk.loc[~multi, "attempt_no"] = 1 if split == "training" else pd.NA  # a single visit is attempt 1 by definition
    final = pk.sort_values(["shipment_id", "status"], key=lambda c: c.eq("DELIVERED") if c.name == "status" else c)
    final = final.groupby("shipment_id", as_index=False).last()  # prefers the DELIVERED visit (True sorts last)
    shipment = pd.DataFrame({
        "shipment_id": final["shipment_id"], "stop_id": final["stop_id"], "route_id": final["route_id"],
        "origin_node_id": final["node_id"], "promised_start_ts": final["w0"], "promised_end_ts": final["w1"],
        "dest_lat": final["lat"], "dest_lng": final["lng"],
        "dest_zone_id": SOURCE + ":zone:" + final["zone_id"].astype("string"),
        "volume_cm3": final["vol"], "day_index": final["day_index"],
    })
    event = pd.DataFrame({
        "event_id": pk["attempt_id"] + ":outcome", "shipment_id": pk["shipment_id"],
        "event_type": pk["status"].map(STATUS_TO_EVENT), "ts": pd.NaT, "ts_quality": "day_only",
        "day_index": pk["day_index"], "raw_code": pk["status"], "node_id": pk["node_id"],
    })
    attempt = pd.DataFrame({
        "attempt_id": pk["attempt_id"], "shipment_id": pk["shipment_id"], "stop_id": pk["stop_id"],
        "attempt_no": pk["attempt_no"].astype("Int64"), "outcome": pk["status"].map(STATUS_TO_OUTCOME),
        "ts_quality": "unknown",
    })
    nodes = pd.DataFrame({"node_id": list(n_rows), "kind": "hub", "name": list(n_rows.values())})
    nodes["city"] = nodes["name"].str[:3].map(METRO)
    nodes["region"] = nodes["city"]

    kw = dict(origin=Origin.OBSERVED, source_id=SOURCE, adapter_version=VERSION)
    routes = with_provenance(routes, record_id_col=None, **kw)
    routes["source_record_id"] = routes["route_id"].str.removeprefix(f"{SOURCE}:")
    stops = with_provenance(stops, **kw)
    stops["source_record_id"] = stops["stop_id"]
    shipment = with_provenance(shipment, **kw)
    shipment["source_record_id"] = shipment["shipment_id"].str.removeprefix(f"{SOURCE}:")
    event = with_provenance(event, **kw)
    attempt = with_provenance(attempt, **kw)
    nodes = with_provenance(nodes, **kw)
    routes["split_hint"] = split  # not a canonical column; dropped below
    routes = routes.drop(columns=["split_hint"])
    return {"node": nodes, "route": routes, "stop": stops, "shipment": shipment, "event": event, "attempt": attempt}


def build() -> None:
    train = _load("package_data.json", "route_data.json", "actual_sequences.json", "training")
    write_tables(SOURCE, train, PROVIDES, part="training")
