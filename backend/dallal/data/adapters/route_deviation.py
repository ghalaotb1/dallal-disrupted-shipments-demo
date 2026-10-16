"""Planned-vs-actual last-mile routes (Molde; Norway/Denmark) -> canonical tables.

One workbook row = one stop visit with its planned index, actual index, arrival offset and time window. Times are
minutes from the route's earliest timestep (no wall clock), so windows/arrivals are stored as *offsets* in seconds.

Data-quality finding (see EDA): 3,049 rows carry sentinel-scale time values (~1.28e7 minutes, i.e. decades). They are kept
as stops (the planned/actual sequence is still valid) but their arrival/window offsets are nulled and the count is logged.

Route instance key: the source reuses `Route ID` across days/weeks, so a canonical route is
(Country, Week ID, Day of Week, Route ID).
"""

from __future__ import annotations

import logging

import pandas as pd

from dallal.data.adapters.base import raw, with_provenance, write_tables
from dallal.data.schema import Origin

log = logging.getLogger("dallal.data.adapter.route_deviation")
SOURCE = "route_deviation"
VERSION = "route-deviation-1.0"
SENTINEL_MIN = 24 * 60  # routes are planned inside a working day; anything beyond a day is an encoding artefact

PROVIDES = {
    "courier": set(),
    "route": {"courier_id", "n_stops"},
    "stop": {"route_id", "seq_planned", "seq_actual", "window_start_offset_s", "window_end_offset_s", "arrival_offset_s",
             "lat", "lng", "zone_id"},
    "shipment": {"stop_id", "route_id", "courier_id", "dest_zone_id", "dest_region", "attrs"},
}


def build() -> None:
    d = pd.read_excel(raw(SOURCE, "routes_performance.xlsx"))
    d.columns = [c.strip() for c in d.columns]
    rid = (SOURCE + ":c" + d["Country"].astype(str) + ":w" + d["Week ID"].astype(str) + ":" + d["Day of Week"].str[:3]
           + ":r" + d["Route ID"].astype(str))
    d["route_id"] = rid
    d["stop_key"] = rid + ":s" + d["Stop ID"].astype(str) + ":p" + d["IndexP"].astype(str)
    dup = d["stop_key"].duplicated().sum()
    if dup:
        log.warning("%d duplicate (route, stop, planned index) rows kept with a row suffix", dup)
        d["stop_key"] = d["stop_key"] + ":" + d.groupby("stop_key").cumcount().astype(str)

    bad = (d[["Arrived Time", "Earliest Time", "Latest Time"]].max(axis=1) > SENTINEL_MIN)
    log.info("sentinel-scale time rows nulled: %d of %d", int(bad.sum()), len(d))
    sec = lambda c: (d[c] * 60.0).where(~bad)  # noqa: E731

    stops = pd.DataFrame({
        "stop_id": d["stop_key"], "route_id": d["route_id"], "seq_planned": d["IndexP"], "seq_actual": d["IndexA"],
        "window_start_offset_s": sec("Earliest Time"), "window_end_offset_s": sec("Latest Time"),
        "arrival_offset_s": sec("Arrived Time"),
    })
    routes = (d.groupby("route_id").agg(courier=("Driver ID", "first"), n=("Stop ID", "size")).reset_index()
              .rename(columns={"courier": "courier_id", "n": "n_stops"}))
    routes["courier_id"] = SOURCE + ":driver" + routes["courier_id"].astype(str)
    deliveries = d[d["Delivery"] == 1]
    shipment = pd.DataFrame({
        "shipment_id": SOURCE + ":" + deliveries["stop_key"].str.removeprefix(f"{SOURCE}:"),
        "stop_id": deliveries["stop_key"], "route_id": deliveries["route_id"],
        "courier_id": SOURCE + ":driver" + deliveries["Driver ID"].astype(str),
        "dest_zone_id": SOURCE + ":addr" + deliveries["Address ID"].astype(str),
        "dest_region": "country" + deliveries["Country"].astype(str),
    })
    shipment["attrs"] = [{"day_of_week": dow, "week": int(w)} for dow, w in
                         zip(deliveries["Day of Week"], deliveries["Week ID"], strict=True)]
    couriers = pd.DataFrame({"courier_id": routes["courier_id"].unique()})

    kw = dict(origin=Origin.OBSERVED, source_id=SOURCE, adapter_version=VERSION)
    write_tables(SOURCE, {
        "courier": with_provenance(couriers, **kw),
        "route": with_provenance(routes, **kw),
        "stop": with_provenance(stops, **kw),
        "shipment": with_provenance(shipment, **kw),
    }, PROVIDES)
