"""Olist Brazilian E-Commerce -> canonical tables.

Provides order-level milestones with real timestamps: purchase, payment approval, hand-off to carrier, delivery to the
customer, and the delivery date PROMISED at checkout (`order_estimated_delivery_date`, a calendar date). Sellers become
SELLER nodes, customers' zip prefixes become destination zones. It provides no scan events, attempts or reasons.

Known data quirks preserved (not "fixed"): ~1.4% of delivered orders show carrier hand-off before payment approval;
~0.02% show delivery before hand-off. They are quantified in the EDA report and the leakage guard treats hand-off as
available only when its own timestamp has passed.
"""

from __future__ import annotations

import pandas as pd

from dallal.data.adapters.base import raw, with_provenance, write_tables
from dallal.data.schema import Origin

SOURCE = "olist"
VERSION = "olist-1.0"

PROVIDES = {
    "node": {"name", "city", "region", "lat", "lng"},
    "shipment": {"origin_node_id", "created_ts", "promised_end_ts", "dest_lat", "dest_lng", "dest_zone_id", "dest_region",
                 "value", "weight_g", "day_index", "attrs"},
    "event": {"ts", "ts_quality", "day_index", "raw_code", "node_id"},
}


def build() -> None:
    orders = pd.read_csv(raw(SOURCE, "olist_orders_dataset.csv"), parse_dates=[
        "order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
        "order_delivered_customer_date", "order_estimated_delivery_date"])
    items = pd.read_csv(raw(SOURCE, "olist_order_items_dataset.csv"))
    cust = pd.read_csv(raw(SOURCE, "olist_customers_dataset.csv"), dtype={"customer_zip_code_prefix": str})
    sell = pd.read_csv(raw(SOURCE, "olist_sellers_dataset.csv"), dtype={"seller_zip_code_prefix": str})
    prod = pd.read_csv(raw(SOURCE, "olist_products_dataset.csv"))
    geo = pd.read_csv(raw(SOURCE, "olist_geolocation_dataset.csv"), dtype={"geolocation_zip_code_prefix": str})
    # Olist geolocation has many readings per prefix, a few outside Brazil; clip to Brazil's bounding box then average.
    geo = geo[geo.geolocation_lat.between(-34, 6) & geo.geolocation_lng.between(-74, -34)]
    zxy = geo.groupby("geolocation_zip_code_prefix")[["geolocation_lat", "geolocation_lng"]].mean()

    first_seller = items.sort_values(["order_id", "order_item_id"]).groupby("order_id")["seller_id"].first()
    agg = items.merge(prod[["product_id", "product_weight_g"]], on="product_id", how="left").groupby("order_id").agg(
        value=("price", "sum"), freight=("freight_value", "sum"), n_items=("order_item_id", "max"),
        weight_g=("product_weight_g", "sum"))
    df = (orders.merge(cust[["customer_id", "customer_zip_code_prefix", "customer_state", "customer_city"]], on="customer_id", how="left")
          .join(first_seller.rename("seller_id"), on="order_id").join(agg, on="order_id"))
    df = df.join(zxy.rename(columns={"geolocation_lat": "dest_lat", "geolocation_lng": "dest_lng"}), on="customer_zip_code_prefix")
    d0 = pd.Timestamp("2016-09-01")
    day = lambda s: (s.dt.normalize() - d0).dt.days.astype("Int64")  # noqa: E731

    sid = SOURCE + ":" + df["order_id"]
    shipment = pd.DataFrame({
        "shipment_id": sid, "origin_node_id": SOURCE + ":seller:" + df["seller_id"].astype("string"),
        "created_ts": df["order_purchase_timestamp"], "promised_end_ts": df["order_estimated_delivery_date"],
        "dest_lat": df["dest_lat"], "dest_lng": df["dest_lng"],
        "dest_zone_id": SOURCE + ":zip:" + df["customer_zip_code_prefix"].astype("string"),
        "dest_region": df["customer_state"], "value": df["value"], "weight_g": df["weight_g"],
        "day_index": day(df["order_purchase_timestamp"]),
    })
    shipment["attrs"] = [
        {"freight_value": None if pd.isna(f) else float(f), "n_items": None if pd.isna(n) else int(n),
         "order_status": st}
        for f, n, st in zip(df["freight"], df["n_items"], df["order_status"], strict=True)
    ]
    ev_specs = [
        ("created", "order_purchase_timestamp", "purchase"),
        ("scan", "order_approved_at", "payment_approved"),
        ("handoff_to_carrier", "order_delivered_carrier_date", "carrier_handoff"),
        ("delivered", "order_delivered_customer_date", "customer_delivered"),
    ]
    events = []
    for etype, col, raw_code in ev_specs:
        m = df[col].notna()
        events.append(pd.DataFrame({
            "event_id": sid[m] + ":" + raw_code, "shipment_id": sid[m], "event_type": etype, "ts": df.loc[m, col],
            "ts_quality": "exact", "day_index": day(df.loc[m, col]), "raw_code": raw_code,
            "node_id": (SOURCE + ":seller:" + df.loc[m, "seller_id"].astype("string")) if etype == "handoff_to_carrier" else None,
        }))
    events = pd.concat(events, ignore_index=True)

    sellers = sell.join(zxy, on="seller_zip_code_prefix")
    nodes = pd.DataFrame({
        "node_id": SOURCE + ":seller:" + sellers["seller_id"], "kind": "seller", "name": sellers["seller_id"].str[:8],
        "city": sellers["seller_city"], "region": sellers["seller_state"],
        "lat": sellers["geolocation_lat"], "lng": sellers["geolocation_lng"],
    })

    kw = dict(origin=Origin.OBSERVED, source_id=SOURCE, adapter_version=VERSION)
    shipment = with_provenance(shipment, **kw)
    shipment["source_record_id"] = df["order_id"].values
    events = with_provenance(events, **kw)
    nodes = with_provenance(nodes, **kw)
    write_tables(SOURCE, {"node": nodes, "shipment": shipment, "event": events}, PROVIDES)
