"""Reproducible EDA / data-quality profile of every canonical source. Writes docs/data/EDA.md + eda_summary.json.

Run:  python -I -m dallal.data.eda
All numbers in the dataset decision report come from this module, not from hand-copied notebooks.
"""

from __future__ import annotations

import io
import json
import zipfile

import numpy as np
import pandas as pd

from dallal.config import PATHS
from dallal.data.adapters.base import read_table


def _q(s: pd.Series, qs=(0.1, 0.5, 0.9, 0.99)) -> dict[str, float]:
    return {f"p{int(q * 100)}": round(float(s.quantile(q)), 2) for q in qs}


def olist() -> dict:
    sh, ev, lab = read_table("olist", "shipment"), read_table("olist", "event"), read_table("olist", "label")
    out = {"orders": len(sh), "labelled_orders": len(lab), "late_rate": round(lab["value"].mean(), 4)}
    p = ev.pivot_table(index="shipment_id", columns="raw_code", values="ts", aggfunc="first")
    d = p.dropna(subset=["customer_delivered"])
    out["delivered_with_timestamp"] = len(d)
    out["late_rate_strict_timestamp_definition"] = round(float((d["customer_delivered"] > sh.set_index("shipment_id").loc[d.index, "promised_end_ts"]).mean()), 4)
    out["handoff_before_approval_frac"] = round(float((d["carrier_handoff"] < d["payment_approved"]).mean()), 4)
    out["delivered_before_handoff_frac"] = round(float((d["customer_delivered"] < d["carrier_handoff"]).mean()), 4)
    m = lab.assign(month=lab["as_of_ts"].dt.to_period("M").astype(str)).groupby("month")["value"].agg(["mean", "size"])
    out["late_rate_by_month"] = {k: round(float(v), 4) for k, v in m["mean"].items()}
    out["worst_months"] = {k: round(float(v), 4) for k, v in m["mean"].nlargest(3).items()}
    out["handoff_to_deliver_days"] = _q((d["customer_delivered"] - d["carrier_handoff"]).dt.total_seconds() / 86400)
    promised = sh.set_index("shipment_id").loc[d.index, "promised_end_ts"]
    out["promised_lead_days"] = _q((promised - d["purchase"]).dt.total_seconds() / 86400)
    out["dest_geo_missing"] = round(float(sh["dest_lat"].isna().mean()), 4)
    return out


def amazon() -> dict:
    att, sh, rt, lab = (read_table("amazon_lmrrc", t) for t in ("attempt", "shipment", "route", "label"))
    out = {"routes": len(rt), "packages": len(sh), "visits": len(att), "outcomes": att["outcome"].value_counts().to_dict()}
    out["packages_with_failed_visit_rate"] = round(float(lab["value"].mean()), 5)
    multi = att.groupby("shipment_id").size()
    out["packages_visited_at_multiple_stops"] = int((multi > 1).sum())
    out["multi_stop_pattern_top"] = att[att.shipment_id.isin(multi[multi > 1].index)].sort_values(["shipment_id", "attempt_no"]).groupby("shipment_id")["outcome"].agg("->".join).value_counts().head(4).to_dict()
    out["time_window_coverage"] = round(float(sh["promised_end_ts"].notna().mean()), 4)
    route_of = sh.set_index("shipment_id")["route_id"]
    meta = rt.set_index("route_id")[["service_date", "node_id"]]
    d = lab.assign(route_id=lab["entity_id"].map(route_of)).join(meta, on="route_id")
    out["failed_rate_by_week"] = {k: round(float(v), 5) for k, v in d.groupby(pd.to_datetime(d["service_date"]).dt.to_period("W").astype(str))["value"].mean().items()}
    out["failed_rate_by_station_top"] = {k: round(float(v), 5) for k, v in d.groupby("node_id")["value"].mean().nlargest(4).items()}
    out["days_covered"] = int(rt["service_date"].nunique())
    out["route_quality_distribution"] = rt["plan_quality"].value_counts().to_dict()
    return out


def lade() -> dict:
    out = {}
    for c in ("jl", "yt", "cq", "sh", "hz"):
        lab = pd.read_parquet(PATHS.canonical / "lade" / f"label.delivery_{c}.parquet", columns=["value", "as_of_day_index"])
        out[f"delivery_{c}"] = {"tasks": len(lab), "days": int(lab["as_of_day_index"].nunique()), "duration_min": _q(lab["value"])}
    for c in ("jl", "yt"):
        lab = pd.read_parquet(PATHS.canonical / "lade" / f"label.pickup_{c}.parquet", columns=["task", "value"])
        late = lab[lab.task == "lade_pickup_late_vs_window"]["value"]
        out[f"pickup_{c}"] = {"tasks": int((lab.task == "lade_pickup_task_duration_min").sum()), "late_vs_window_rate": round(float(late.mean()), 5), "late_count": int(late.sum())}
    sh = pd.read_parquet(PATHS.canonical / "lade" / "shipment.delivery_sh.parquet", columns=["courier_id", "dest_zone_id"])
    out["shanghai_couriers"], out["shanghai_aois"] = int(sh["courier_id"].nunique()), int(sh["dest_zone_id"].nunique())
    out["failure_labels_available"] = False
    return out


def route_deviation() -> dict:
    st, lab, sh = read_table("route_deviation", "stop"), read_table("route_deviation", "label"), read_table("route_deviation", "shipment")
    out = {"routes": int(st["route_id"].nunique()), "stops": len(st), "delivery_stops": len(sh), "drivers": int(sh["courier_id"].nunique())}
    out["sentinel_time_rows_nulled"] = int(st["arrival_offset_s"].isna().sum())
    for t in ("route_deviation_stop_late", "route_deviation_stop_displaced"):
        out[t + "_rate"] = round(float(lab[lab.task == t]["value"].mean()), 4)
    out["stops_moved_share_of_routes_with_any_move"] = round(float(st.assign(m=st.seq_planned != st.seq_actual).groupby("route_id")["m"].any().mean()), 4)
    return out


def ocel() -> dict:
    att = read_table("ocel_order_management", "attempt")
    n = att.groupby("shipment_id").size()
    fails = att[att.outcome == "failed"].groupby("shipment_id").size().reindex(n.index, fill_value=0)
    return {"packages": len(n), "failed_events": int((att.outcome == "failed").sum()), "packages_with_a_failure": int((fails > 0).sum()),
            "max_failures_on_one_package": int(fails.max()), "origin": "SYNTHETIC (CPN simulation) — shape reference only"}


def spl() -> dict:
    n = read_table("spl_open_data", "node")
    return {"branches": len(n), "with_valid_coords": int(n["lat"].notna().sum()), "regions": n["region"].value_counts().to_dict()}


def dataco() -> dict:
    d = pd.read_csv(PATHS.raw / "dataco" / "DataCoSupplyChainDataset.csv", encoding="latin-1")
    return {"rows": len(d), "late_delivery_risk_rate": round(float(d["Late_delivery_risk"].mean()), 4),
            "label_equals_status_late_delivery": bool((d["Late_delivery_risk"] == (d["Delivery Status"] == "Late delivery")).all()),
            "agreement_with_real_gt_scheduled": round(float(((d["Days for shipping (real)"] > d["Days for shipment (scheduled)"]).astype(int) == d["Late_delivery_risk"]).mean()), 4)}


def cargo2000() -> dict:
    c = pd.read_csv(io.BytesIO(zipfile.ZipFile(PATHS.raw / "cargo2000" / "cargo2000.zip").read("c2k_data_comma.csv")))
    late = (c["o_dlv_e"] > c["o_dlv_p"])
    return {"rows": len(c), "columns": c.shape[1], "final_delivery_slower_than_planned_rate": round(float(late.mean()), 4), "missing_cell_rate": round(float(c.isna().mean().mean()), 4)}


def run() -> dict:
    res = {k: f() for k, f in {"olist": olist, "amazon_lmrrc": amazon, "lade": lade, "route_deviation": route_deviation,
                                "ocel_order_management": ocel, "spl_open_data": spl, "dataco": dataco, "cargo2000": cargo2000}.items()}
    PATHS.docs.joinpath("data").mkdir(parents=True, exist_ok=True)
    (PATHS.docs / "data" / "eda_summary.json").write_text(json.dumps(res, indent=2, default=str) + "\n")
    return res


if __name__ == "__main__":
    print(json.dumps(run(), indent=2, default=str))
