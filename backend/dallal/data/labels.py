"""Engineered labels derived from OBSERVED canonical tables.

Every label row states when a prediction would be made (`as_of_*`) and when the outcome becomes knowable
(`available_at_*`). Thresholds that depend on the data distribution (e.g. "slow task = above the training P90") are
deliberately NOT baked in here: continuous outcomes are stored raw and binarised inside the ML layer using
training-period statistics only. That keeps the label table free of test-period information.
"""

from __future__ import annotations

import pandas as pd

from dallal.data.adapters.base import read_table, with_provenance, write_tables
from dallal.data.schema import Origin

VERSION = "labels-1.0"
DAY0 = {"olist": pd.Timestamp("2016-09-01"), "lade": pd.Timestamp("2000-01-01")}


def _finish(df: pd.DataFrame, source: str) -> pd.DataFrame:
    for c in ("as_of_ts", "available_at_ts"):
        if c not in df:
            df[c] = pd.NaT
    for c in ("as_of_day_index", "available_at_day_index"):
        if c not in df:
            df[c] = pd.array([pd.NA] * len(df), dtype="Int64")
    return with_provenance(df, origin=Origin.ENGINEERED, source_id=source, adapter_version=VERSION)


def olist_late_delivery() -> pd.DataFrame:
    """late = delivered calendar day > promised calendar day. Predicted at carrier hand-off.

    Rows whose hand-off is missing or not strictly before delivery are excluded (they cannot be a prediction made
    before the outcome). 8.11% would be 'late' under a strict timestamp comparison; the promise is a date, so same-day
    delivery counts as on time (6.77%).
    """
    sh = read_table("olist", "shipment")[["shipment_id", "promised_end_ts"]]
    ev = read_table("olist", "event")
    p = ev.pivot_table(index="shipment_id", columns="raw_code", values="ts", aggfunc="first")
    df = sh.merge(p, left_on="shipment_id", right_index=True)
    df = df.dropna(subset=["carrier_handoff", "customer_delivered"])
    df = df[df["carrier_handoff"] < df["customer_delivered"]]
    out = pd.DataFrame({
        "label_id": "olist:late:" + df["shipment_id"], "task": "olist_late_delivery_at_handoff", "entity_type": "shipment",
        "entity_id": df["shipment_id"],
        "value": (df["customer_delivered"].dt.normalize() > df["promised_end_ts"].dt.normalize()).astype(float),
        "as_of_ts": df["carrier_handoff"], "available_at_ts": df["customer_delivered"],
        "as_of_day_index": (df["carrier_handoff"].dt.normalize() - DAY0["olist"]).dt.days.astype("Int64"),
        "available_at_day_index": (df["customer_delivered"].dt.normalize() - DAY0["olist"]).dt.days.astype("Int64"),
        "definition": "late = date(delivered_customer) > date(estimated_delivery); as_of = carrier hand-off; v1",
    })
    return _finish(out, "olist")


def amazon_package_failed_attempt() -> pd.DataFrame:
    """1 if the package had at least one non-delivered visit on its route. Predicted at planned route departure."""
    att = read_table("amazon_lmrrc", "attempt")
    sh = read_table("amazon_lmrrc", "shipment")[["shipment_id", "route_id", "day_index"]]
    rt = read_table("amazon_lmrrc", "route")[["route_id", "planned_departure_ts"]]
    y = (att.assign(bad=(att["outcome"] != "delivered")).groupby("shipment_id", as_index=False)["bad"].max())
    df = y.merge(sh, on="shipment_id").merge(rt, on="route_id")
    out = pd.DataFrame({
        "label_id": "amazon:failed:" + df["shipment_id"], "task": "amazon_package_failed_attempt", "entity_type": "shipment",
        "entity_id": df["shipment_id"], "value": df["bad"].astype(float), "as_of_ts": df["planned_departure_ts"],
        "as_of_day_index": df["day_index"].astype("Int64"), "available_at_day_index": df["day_index"].astype("Int64"),
        "definition": "any visit with scan_status != DELIVERED; as_of = planned route departure, outcome known same day; v1",
    })
    return _finish(out, "amazon_lmrrc")


def lade_task_duration(kind: str, code: str) -> pd.DataFrame:
    """Accept -> completion minutes (continuous). Binarise with training-period quantiles in the ML layer."""
    part = f"{kind}_{code}"
    ev = pd.read_parquet(_part("lade", "event", part), columns=["shipment_id", "event_type", "ts", "day_index"])
    acc = ev[ev.event_type == "accepted"].set_index("shipment_id")
    done = ev[ev.event_type.isin(["delivered", "picked_up"])].set_index("shipment_id")
    df = acc[["ts", "day_index"]].join(done[["ts", "day_index"]], lsuffix="_a", rsuffix="_d", how="inner").reset_index()
    mins = (df["ts_d"] - df["ts_a"]).dt.total_seconds() / 60
    df = df[mins > 0]  # zero/negative durations: outcome not strictly after the prediction instant
    out = pd.DataFrame({
        "label_id": "lade:dur:" + df["shipment_id"], "task": f"lade_{kind}_task_duration_min", "entity_type": "shipment",
        "entity_id": df["shipment_id"], "value": ((df["ts_d"] - df["ts_a"]).dt.total_seconds() / 60).values,
        "as_of_ts": df["ts_a"], "available_at_ts": df["ts_d"],
        "as_of_day_index": df["day_index_a"], "available_at_day_index": df["day_index_d"],
        "definition": "minutes from courier accept to completion (continuous; rows with duration <= 0 dropped); v1",
    })
    return _finish(out, "lade")


def lade_pickup_late(code: str) -> pd.DataFrame:
    """1 if pickup happened after the promised window end. Real observed window violation (rare: ~0.2% in Jilin)."""
    part = f"pickup_{code}"
    sh = pd.read_parquet(_part("lade", "shipment", part), columns=["shipment_id", "promised_end_ts", "day_index"])
    ev = pd.read_parquet(_part("lade", "event", part), columns=["shipment_id", "event_type", "ts", "day_index"])
    acc = ev[ev.event_type == "accepted"].set_index("shipment_id")["ts"]
    pk = ev[ev.event_type == "picked_up"].set_index("shipment_id")["ts"]
    df = sh.join(acc.rename("acc"), on="shipment_id").join(pk.rename("pk"), on="shipment_id").dropna(subset=["acc", "pk"])
    df = df[df.acc < df.pk]
    out = pd.DataFrame({
        "label_id": "lade:pwv:" + df["shipment_id"], "task": "lade_pickup_late_vs_window", "entity_type": "shipment",
        "entity_id": df["shipment_id"], "value": (df["pk"] > df["promised_end_ts"]).astype(float),
        "as_of_ts": df["acc"], "available_at_ts": df["pk"],
        "as_of_day_index": df["day_index"], "available_at_day_index": (df["pk"].dt.normalize() - DAY0["lade"]).dt.days.astype("Int64"),
        "definition": "late = pickup_time > time_window_end; as_of = courier accept; v1",
    })
    return _finish(out, "lade")


def route_deviation_labels() -> dict[str, pd.DataFrame]:
    st = read_table("route_deviation", "stop")
    sh = read_table("route_deviation", "shipment")[["shipment_id", "stop_id", "attrs"]]
    dow = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
    df = sh.merge(st, on="stop_id", suffixes=("", "_st"))
    wk = df["attrs"].map(lambda a: a["week"])
    dw = df["attrs"].map(lambda a: dow[a["day_of_week"][:3]])
    day = (wk * 7 + dw).astype("Int64")
    ok = df["arrival_offset_s"].notna() & df["window_end_offset_s"].notna()
    late = df[ok]
    out_late = pd.DataFrame({
        "label_id": "rd:late:" + late["shipment_id"], "task": "route_deviation_stop_late", "entity_type": "shipment",
        "entity_id": late["shipment_id"], "value": (late["arrival_offset_s"] > late["window_end_offset_s"]).astype(float),
        "as_of_day_index": day[ok].values, "available_at_day_index": day[ok].values,
        "definition": "arrival offset > latest window offset (rows with sentinel-scale times excluded); v1",
    })
    moved = pd.DataFrame({
        "label_id": "rd:moved:" + df["shipment_id"], "task": "route_deviation_stop_displaced", "entity_type": "shipment",
        "entity_id": df["shipment_id"], "value": (df["seq_planned"] != df["seq_actual"]).astype(float),
        "as_of_day_index": day.values, "available_at_day_index": day.values,
        "definition": "planned stop index != actual stop index; v1",
    })
    return {"late": _finish(out_late, "route_deviation"), "displaced": _finish(moved, "route_deviation")}


def _part(source: str, table: str, part: str):
    from dallal.config import PATHS

    return PATHS.canonical / source / f"{table}.{part}.parquet"


def build_all(lade_cities: tuple[str, ...] = ("jl", "yt", "cq", "sh", "hz"), pickup_cities: tuple[str, ...] = ("jl", "yt")) -> None:
    write_tables("olist", {"label": olist_late_delivery()}, {}, part="")
    write_tables("amazon_lmrrc", {"label": amazon_package_failed_attempt()}, {}, part="training")
    for c in lade_cities:
        write_tables("lade", {"label": lade_task_duration("delivery", c)}, {}, part=f"delivery_{c}")
    for c in pickup_cities:
        write_tables("lade", {"label": pd.concat([lade_task_duration("pickup", c), lade_pickup_late(c)], ignore_index=True)}, {}, part=f"pickup_{c}")
    rd = route_deviation_labels()
    write_tables("route_deviation", {"label": pd.concat(rd.values(), ignore_index=True)}, {})
