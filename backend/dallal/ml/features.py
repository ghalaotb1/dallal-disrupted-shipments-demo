"""Point-in-time feature construction for the initial ML tasks. Every feature uses only information knowable at `as_of`.

The central helper is `past_stat`: for each row it aggregates a quantity over OTHER rows of the same group whose outcome had
already become available strictly before this row's prediction instant (label `available_at` < row `as_of`). That is the
difference between a legitimate 'seller/zone/courier history' feature and a leak.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dallal.data.adapters.base import read_table
from dallal.data.schema import Origin
from dallal.data.splits import drop_sparse_periods
from dallal.tools.signals import haversine_m


def _num(s: pd.Series) -> np.ndarray:
    return s.astype("int64").to_numpy() if pd.api.types.is_datetime64_any_dtype(s) else s.to_numpy(dtype="float64")


def past_stat(keys: pd.Series, as_of: pd.Series, available_at: pd.Series, value: pd.Series, *, prior: float, prior_n: float = 20.0) -> tuple[np.ndarray, np.ndarray]:
    """Shrunk mean of `value` over earlier-resolved rows of the same key; also returns the support count.

    A row never sees itself or any row whose outcome resolves at or after its own prediction time.
    """
    n = len(keys)
    mean = np.full(n, prior)
    cnt = np.zeros(n)
    k = keys.to_numpy()
    t_as, t_av, v = _num(as_of), _num(available_at), value.to_numpy(dtype="float64")
    order = np.argsort(k, kind="stable")
    ks = k[order]
    bounds = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1], True])
    for a, b in zip(bounds[:-1], bounds[1:], strict=False):
        idx = order[a:b]
        o = np.argsort(t_av[idx], kind="stable")
        av_sorted = t_av[idx][o]
        csum = np.r_[0.0, np.cumsum(v[idx][o])]
        pos = np.searchsorted(av_sorted, t_as[idx], side="left")  # rows with available_at < as_of
        c = pos.astype(float)
        mean[idx] = (csum[pos] + prior * prior_n) / (c + prior_n)
        cnt[idx] = c
    return mean, cnt


def concurrent_open(courier: pd.Series, accept: pd.Series, done: pd.Series) -> np.ndarray:
    """Tasks the same courier had accepted but not completed at this task's accept time (visible at decision time)."""
    out = np.zeros(len(courier))
    c, a, d = courier.to_numpy(), _num(accept), _num(done)
    order = np.argsort(c, kind="stable")
    cs = c[order]
    bounds = np.flatnonzero(np.r_[True, cs[1:] != cs[:-1], True])
    for lo, hi in zip(bounds[:-1], bounds[1:], strict=False):
        idx = order[lo:hi]
        acc, dn = np.sort(a[idx]), np.sort(d[idx])
        t = a[idx]
        out[idx] = np.searchsorted(acc, t, side="right") - 1 - np.searchsorted(dn, t, side="left")  # exclude self, count open
    return np.maximum(out, 0)


def train_prior(y: pd.Series, t: pd.Series, frac: float = 0.6) -> float:
    """Shrinkage prior estimated ONLY from the earliest `frac` of the timeline (a subset of any later train split), never from
    the whole table — otherwise test-period outcomes would leak into every smoothed history feature."""
    tv = _num(t)
    return float(y.to_numpy(dtype="float64")[tv <= np.quantile(tv, frac)].mean())


def olist_frame() -> pd.DataFrame:
    sh, ev, lab, nd = (read_table("olist", t) for t in ("shipment", "event", "label", "node"))
    p = ev.pivot_table(index="shipment_id", columns="raw_code", values="ts", aggfunc="first")
    # Rename the label FIRST: shipment also has a `value` column (order price) and a silent merge collision once turned the label
    # into a feature (single-feature AUC 1.000). Labels live in `_label`; nothing else may use that name.
    df = lab[["entity_id", "value", "as_of_ts", "available_at_ts", "as_of_day_index", "available_at_day_index", "origin"]].rename(columns={"entity_id": "shipment_id", "value": "_label"})
    df = df.merge(sh, on="shipment_id", suffixes=("_lab", "")).join(p, on="shipment_id")
    df = df.merge(nd[["node_id", "lat", "lng", "region"]].rename(columns={"node_id": "origin_node_id", "lat": "s_lat", "lng": "s_lng", "region": "seller_state"}), on="origin_node_id", how="left")
    attrs = pd.json_normalize(df["attrs"])
    x = pd.DataFrame(index=df.index)
    x["lead_days_at_handoff"] = (df["promised_end_ts"] - df["carrier_handoff"]).dt.total_seconds() / 86400
    x["purchase_to_approval_h"] = (df["payment_approved"] - df["purchase"]).dt.total_seconds() / 3600
    x["approval_to_handoff_h"] = (df["carrier_handoff"] - df["payment_approved"]).dt.total_seconds() / 3600
    x["promised_total_days"] = (df["promised_end_ts"] - df["purchase"]).dt.total_seconds() / 86400
    x["distance_km"] = [haversine_m(a, b, c, d) / 1000 if not np.isnan([a, b, c, d]).any() else np.nan
                        for a, b, c, d in zip(df["s_lat"], df["s_lng"], df["dest_lat"], df["dest_lng"], strict=True)]
    x["same_state"] = (df["seller_state"] == df["dest_region"]).astype(float)
    x["value"], x["weight_g"] = df["value"], df["weight_g"]
    x["freight_value"], x["n_items"] = attrs["freight_value"].values, attrs["n_items"].values
    x["handoff_hour"], x["handoff_dow"] = df["carrier_handoff"].dt.hour, df["carrier_handoff"].dt.dayofweek
    prior = train_prior(df["_label"], df["as_of_ts"])
    for key, name in (("origin_node_id", "seller"), ("dest_region", "dest_state"), ("dest_zone_id", "dest_zip")):
        m, c = past_stat(df[key].fillna("na"), df["as_of_ts"], df["available_at_ts"], df["_label"], prior=prior, prior_n=30.0)
        x[f"{name}_past_late_rate"], x[f"{name}_past_n"] = m, c
    x["_y"], x["_t"], x["_origin"], x["_month"] = df["_label"].values, df["as_of_day_index"].values, df["origin_lab"].values, df["as_of_ts"].dt.to_period("M").astype(str).values
    return x


def amazon_frame() -> pd.DataFrame:
    sh, lab, rt, st, att = (read_table("amazon_lmrrc", t) for t in ("shipment", "label", "route", "stop", "attempt"))
    df = lab[["entity_id", "value", "as_of_day_index", "available_at_day_index", "origin"]].rename(columns={"entity_id": "shipment_id", "value": "_label"})
    df = df.merge(sh[["shipment_id", "stop_id", "route_id", "origin_node_id", "promised_start_ts", "promised_end_ts", "dest_zone_id", "dest_lat", "dest_lng", "volume_cm3"]], on="shipment_id")
    df = df.merge(rt[["route_id", "n_stops", "capacity", "planned_departure_ts"]], on="route_id", how="left")
    df = df.merge(st[["stop_id", "planned_service_s"]], on="stop_id", how="left")
    df["pk_at_stop"] = df.groupby("stop_id")["shipment_id"].transform("size")
    df["pk_on_route"] = df.groupby("route_id")["shipment_id"].transform("size")
    x = pd.DataFrame(index=df.index)
    x["volume_cm3"], x["planned_service_s"], x["pk_at_stop"], x["pk_on_route"] = df["volume_cm3"], df["planned_service_s"], df["pk_at_stop"], df["pk_on_route"]
    x["n_stops"], x["capacity"] = df["n_stops"], df["capacity"]
    x["load_ratio"] = df["pk_on_route"] / df["n_stops"]
    x["has_window"] = df["promised_end_ts"].notna().astype(float)
    x["window_h"] = (df["promised_end_ts"] - df["promised_start_ts"]).dt.total_seconds() / 3600
    x["dep_hour"], x["dep_dow"] = df["planned_departure_ts"].dt.hour, df["planned_departure_ts"].dt.dayofweek
    x["svc_per_pkg"] = df["planned_service_s"] / df["pk_at_stop"]
    day = df["as_of_day_index"].astype(float)
    prior = train_prior(df["_label"], day)
    for key, name in (("dest_zone_id", "zone"), ("origin_node_id", "station")):
        m, c = past_stat(df[key].fillna("na"), day, day, df["_label"], prior=prior, prior_n=50.0)  # same-day outcomes are NOT visible
        x[f"{name}_past_fail_rate"], x[f"{name}_past_n"] = m, c
    x["_y"], x["_t"], x["_origin"] = df["_label"].values, df["as_of_day_index"].values, df["origin"].values
    return x


def lade_stream(code: str = "sh") -> pd.DataFrame:
    """The LaDe task stream sorted by as_of (row position = `_row` in `lade_frame`)."""
    from dallal.config import PATHS

    base = PATHS.canonical / "lade"
    sh = pd.read_parquet(base / f"shipment.delivery_{code}.parquet", columns=["shipment_id", "courier_id", "dest_zone_id", "dest_zone_type", "dest_region", "dest_lat", "dest_lng"])
    ev = pd.read_parquet(base / f"event.delivery_{code}.parquet", columns=["shipment_id", "event_type", "ts", "lat", "lng"])
    acc = ev[ev.event_type == "accepted"].set_index("shipment_id")
    lab = pd.read_parquet(base / f"label.delivery_{code}.parquet", columns=["entity_id", "value", "as_of_ts", "available_at_ts", "origin"]).rename(columns={"entity_id": "shipment_id"})
    df = lab.merge(sh, on="shipment_id").join(acc[["lat", "lng"]].rename(columns={"lat": "acc_lat", "lng": "acc_lng"}), on="shipment_id")
    df["log_dur"] = np.log1p(df["value"])
    return df.sort_values("as_of_ts").reset_index(drop=True)


def lade_frame(code: str = "sh", sample: int | None = 400_000, seed: int = 0) -> pd.DataFrame:
    df = lade_stream(code)
    x = pd.DataFrame(index=df.index)
    x["hour"], x["dow"] = df["as_of_ts"].dt.hour, df["as_of_ts"].dt.dayofweek
    x["aoi_type"] = pd.to_numeric(df["dest_zone_type"], errors="coerce")
    x["open_tasks_courier"] = concurrent_open(df["courier_id"], df["as_of_ts"], df["available_at_ts"])
    ok = df["acc_lat"].notna()
    x["accept_dist_m"] = np.where(ok, [haversine_m(a, b, c, d) if o else np.nan for a, b, c, d, o in zip(df["acc_lat"], df["acc_lng"], df["dest_lat"], df["dest_lng"], ok, strict=True)], np.nan)
    prior = train_prior(df["log_dur"], df["as_of_ts"])
    for key, name in (("dest_zone_id", "aoi"), ("courier_id", "courier"), ("dest_region", "region")):
        m, c = past_stat(df[key], df["as_of_ts"], df["available_at_ts"], df["log_dur"], prior=prior, prior_n=10.0)
        x[f"{name}_past_logdur"], x[f"{name}_past_n"] = m, c
    x["_dur"], x["_t"], x["_origin"] = df["value"].values, df["as_of_ts"].astype("int64").values, df["origin"].values
    x["_row"] = np.arange(len(x))  # position in the as_of-sorted stream (lets sequence features be aligned after sampling)
    if sample and len(x) > sample:
        x = x.sample(sample, random_state=seed).sort_values("_t").reset_index(drop=True)  # sampling AFTER history features: they used the full stream
    return x


def keep_dense_months(df: pd.DataFrame, min_rows: int = 500) -> pd.DataFrame:
    return drop_sparse_periods(df, "_month", min_rows)


__all__ = ["Origin", "amazon_frame", "concurrent_open", "keep_dense_months", "lade_frame", "lade_stream", "olist_frame", "past_stat"]
