"""Cainiao LaDe -> canonical tables.

What LaDe can provide: courier task timing (accept -> deliver/pickup), GPS at those instants, stop location,
AOI/region context, and (pickup only) the promised time window. It provides NO failure/attempt labels and NO
failure reasons: delivery rows exist only for completed tasks. Those canonical columns are therefore never filled.

Timestamps are published as "MM-DD HH:MM:SS" with no year. We attach an arbitrary leap year (2000) so arithmetic
works and mark every timestamp TsQuality.YEARLESS; the `ds` column (MMDD) gives a valid ordering within the
six-month span (no year wrap occurs: ds is 501..1031).
"""

from __future__ import annotations

import pandas as pd

from dallal.data.adapters.base import raw, with_provenance, write_tables
from dallal.data.schema import Origin

SOURCE = "lade"
VERSION = "lade-1.0"
DUMMY_YEAR = "2000-"
CITIES = {"jl": "Jilin", "yt": "Yantai", "cq": "Chongqing", "sh": "Shanghai", "hz": "Hangzhou"}

PROVIDES = {
    "shipment": {"courier_id", "dest_lat", "dest_lng", "dest_zone_id", "dest_zone_type", "dest_region", "day_index",
                 "promised_start_ts", "promised_end_ts", "service_level"},
    "event": {"ts", "ts_quality", "day_index", "courier_id", "lat", "lng"},
    "courier": set(),
}


def _ts(s: pd.Series) -> pd.Series:
    return pd.to_datetime(DUMMY_YEAR + s.astype("string"), format="%Y-%m-%d %H:%M:%S", errors="coerce")


def _day_index(ts: pd.Series) -> pd.Series:
    return (ts.dt.normalize() - pd.Timestamp("2000-01-01")).dt.days.astype("Int64")


def build_city(kind: str, code: str) -> dict[str, pd.DataFrame]:
    """kind in {'delivery','pickup'}; code in CITIES."""
    df = pd.read_csv(raw(SOURCE, f"{kind}_{code}.csv"))
    city = CITIES[code]
    tag = "D" if kind == "delivery" else "P"
    sid = f"{SOURCE}:{tag}:{code}:" + df["order_id"].astype(str)
    accept = _ts(df["accept_time"])
    done_col = "delivery_time" if kind == "delivery" else "pickup_time"
    done = _ts(df[done_col])
    gps_lng = df["delivery_gps_lng" if kind == "delivery" else "pickup_gps_lng"]
    gps_lat = df["delivery_gps_lat" if kind == "delivery" else "pickup_gps_lat"]
    courier = f"{SOURCE}:{code}:" + df["courier_id"].astype(str)

    shipment = pd.DataFrame({
        "shipment_id": sid,
        "courier_id": courier,
        "dest_lat": df["lat"], "dest_lng": df["lng"],
        "dest_zone_id": f"{SOURCE}:{code}:aoi" + df["aoi_id"].astype(str),
        "dest_zone_type": df["aoi_type"].astype(str),
        "dest_region": f"{SOURCE}:{code}:region" + df["region_id"].astype(str),
        "day_index": _day_index(accept),
        "service_level": "pickup" if kind == "pickup" else "delivery",
    })
    if kind == "pickup":
        shipment["promised_start_ts"] = _ts(df["time_window_start"])
        shipment["promised_end_ts"] = _ts(df["time_window_end"])
    shipment["source_native_id"] = df["order_id"]
    shipment["city"] = city

    ev_accept = pd.DataFrame({
        "event_id": sid + ":accepted", "shipment_id": sid, "event_type": "accepted", "ts": accept,
        "ts_quality": "yearless", "day_index": _day_index(accept), "courier_id": courier,
        "lat": df["accept_gps_lat"], "lng": df["accept_gps_lng"],
    })
    ev_done = pd.DataFrame({
        "event_id": sid + (":delivered" if kind == "delivery" else ":picked_up"), "shipment_id": sid,
        "event_type": "delivered" if kind == "delivery" else "picked_up", "ts": done, "ts_quality": "yearless",
        "day_index": _day_index(done), "courier_id": courier, "lat": gps_lat, "lng": gps_lng,
    })
    events = pd.concat([ev_accept, ev_done], ignore_index=True)
    couriers = pd.DataFrame({"courier_id": courier.unique()})

    kw = dict(origin=Origin.OBSERVED, source_id=SOURCE, adapter_version=VERSION)
    shipment = with_provenance(shipment.drop(columns=["source_native_id", "city"]), record_id_col=None, **kw)
    shipment["source_record_id"] = df["order_id"].astype(str).values
    events = with_provenance(events, **kw)
    events["source_record_id"] = events["shipment_id"].str.rsplit(":", n=1).str[-1]
    couriers = with_provenance(couriers, **kw)
    return {"shipment": shipment, "event": events, "courier": couriers}


def build(include: tuple[str, ...] = ("delivery_jl", "delivery_yt", "pickup_jl", "pickup_yt")) -> None:
    for spec in include:
        kind, code = spec.split("_")
        write_tables(SOURCE, build_city(kind, code), PROVIDES, part=spec)
