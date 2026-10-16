"""SPL (Saudi Post) open data -> Node table (real Saudi branch network). REFERENCE data: no shipments or events."""

from __future__ import annotations

import pandas as pd

from dallal.data.adapters.base import raw, with_provenance, write_tables
from dallal.data.schema import Origin

SOURCE = "spl_open_data"
VERSION = "spl-1.0"
PROVIDES = {"node": {"name", "city", "region", "lat", "lng"}}
# Saudi Arabia bounding box (generous) used to reject mis-keyed coordinates rather than trust them.
LAT_RANGE, LNG_RANGE = (15.0, 33.0), (34.0, 56.0)


def build() -> pd.DataFrame:
    areas = pd.read_excel(raw(SOURCE, "area.xlsx"))
    cities = pd.read_excel(raw(SOURCE, "cities.xlsx"))
    off = pd.read_excel(raw(SOURCE, "offices.xlsx"))
    off = off.rename(columns={"رقم المنطقة": "area_id", "رمز المدينة": "city_id", "رقم الفرع": "branch_no",
                              "اسم الفرع": "name_ar", "اسم الفرع انجليزي": "name_en", "الحي": "district",
                              "X_Google": "lng", "Y_Google": "lat"})
    areas = areas.rename(columns={"رمز المنطقة": "area_id", "EN_NAME": "area_en"})[["area_id", "area_en"]]
    cities = cities.rename(columns={"City_Id": "city_id", "City_Name_En": "city_en", "AdminArea_Id": "area_id"})
    off = off.merge(areas, on="area_id", how="left").merge(cities[["city_id", "area_id", "city_en"]], on=["city_id", "area_id"], how="left")
    for c in ("lat", "lng"):
        off[c] = pd.to_numeric(off[c], errors="coerce")
    ok = off.lat.between(*LAT_RANGE) & off.lng.between(*LNG_RANGE)
    off.loc[~ok, ["lat", "lng"]] = None
    nodes = pd.DataFrame({
        "node_id": SOURCE + ":office:" + off["area_id"].astype(str) + "-" + off["city_id"].astype(str) + "-" + off["branch_no"].astype(str),
        "kind": "branch", "name": off["name_en"].fillna(off["name_ar"]), "city": off["city_en"], "region": off["area_en"],
        "lat": off["lat"], "lng": off["lng"],
    })
    nodes = with_provenance(nodes, origin=Origin.OBSERVED, source_id=SOURCE, adapter_version=VERSION)
    write_tables(SOURCE, {"node": nodes}, PROVIDES)
    return nodes
