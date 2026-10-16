"""OCEL 2.0 Order Management (RWTH, simulated with CPN Tools) -> canonical tables.

SECONDARY, NOT REAL. Everything this adapter emits is tagged origin=SYNTHETIC with scenario_id "ocel2-order-management-v2"
because the log is the output of a Petri-net simulation. Its role: prove the canonical event/attempt model round-trips a
standard object-centric log, and show the *shape* of repeated failed-delivery loops. Rates are the simulator's, not reality's.
"""

from __future__ import annotations

import json

import pandas as pd

from dallal.data.adapters.base import raw, with_provenance, write_tables
from dallal.data.schema import Origin

SOURCE = "ocel_order_management"
VERSION = "ocel-1.0"
SCENARIO = "ocel2-order-management-v2"
ACTIVITY_MAP = {"send package": "out_for_delivery", "failed delivery": "failed_attempt", "package delivered": "delivered",
                "create package": "created", "place order": None, "confirm order": None, "pay order": None,
                "payment reminder": None, "item out of stock": None, "reorder item": None, "pick item": None}
PROVIDES = {"shipment": {"created_ts"}, "event": {"ts", "ts_quality"}, "attempt": {"attempt_no", "ts", "ts_quality"}}


def build() -> dict[str, pd.DataFrame]:
    with open(raw(SOURCE, "order-management.json")) as fh:
        log = json.load(fh)
    pk_ids = {o["id"] for o in log["objects"] if o["type"] == "packages"}
    ev_rows = []
    for e in log["events"]:
        etype = ACTIVITY_MAP.get(e["type"])
        if etype is None:
            continue
        pkgs = [r["objectId"] for r in e["relationships"] if r["objectId"] in pk_ids]
        for p in pkgs:
            ev_rows.append((e["id"], f"{SOURCE}:{p}", etype, pd.Timestamp(e["time"]).tz_localize(None)))
    ev = pd.DataFrame(ev_rows, columns=["event_id", "shipment_id", "event_type", "ts"]).sort_values(["shipment_id", "ts"])
    ev["event_id"] = ev["event_id"] + ":" + ev["shipment_id"]
    ev["ts_quality"] = "exact"
    ship = ev[ev.event_type == "created"].groupby("shipment_id", as_index=False)["ts"].min().rename(columns={"ts": "created_ts"})
    att = ev[ev.event_type.isin(["failed_attempt", "delivered"])].copy()
    att["attempt_no"] = att.groupby("shipment_id").cumcount() + 1
    att["outcome"] = att["event_type"].map({"failed_attempt": "failed", "delivered": "delivered"})
    att["attempt_id"] = att["shipment_id"] + ":a" + att["attempt_no"].astype(str)
    att = att[["attempt_id", "shipment_id", "attempt_no", "outcome", "ts", "ts_quality"]]

    kw = dict(origin=Origin.SYNTHETIC, source_id=SOURCE, adapter_version=VERSION, scenario_id=SCENARIO)
    tables = {"shipment": with_provenance(ship, **kw), "event": with_provenance(ev, **kw), "attempt": with_provenance(att, **kw)}
    write_tables(SOURCE, tables, PROVIDES)
    return tables
