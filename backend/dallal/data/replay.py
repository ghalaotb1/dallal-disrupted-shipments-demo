"""Real-data replay cases: canonical Bundles built from real LaDe tasks, as the agent would see them shortly after acceptance.

Local only (needs the canonical tables; the sources forbid redistribution). The bundle carries just the case's own records - shipment row and the
`accepted` event, both observed - at `as_of = accept + minutes_after`. Workload and resolved-task history are NOT in the bundle: they come from the
point-in-time store, exactly as they would from an operational database.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from dallal.ml import features as F
from dallal.tools.bundle import Bundle


def lade_bundle(row: pd.Series, minutes_after: float = 10.0) -> Bundle:
    sid = str(row["shipment_id"])
    t = pd.Timestamp(row["as_of_ts"])
    ship = pd.DataFrame([{"shipment_id": sid, "courier_id": row["courier_id"], "dest_lat": row["dest_lat"], "dest_lng": row["dest_lng"], "dest_zone_id": row["dest_zone_id"],
                          "dest_zone_type": row["dest_zone_type"], "dest_region": row["dest_region"], "service_level": "delivery", "origin": "observed", "source_id": "lade",
                          "adapter_version": "lade-1.0", "scenario_id": None}])
    ev = pd.DataFrame([{"event_id": f"{sid}:accepted", "shipment_id": sid, "event_type": "accepted", "ts": t, "courier_id": row["courier_id"], "lat": row["acc_lat"], "lng": row["acc_lng"],
                        "origin": "observed", "source_id": "lade", "adapter_version": "lade-1.0"}])
    return Bundle(f"lade-replay:{sid}", t + pd.Timedelta(minutes=minutes_after), sid, {"kind": "slow_task_watch"}, {"shipment": ship, "event": ev})


def lade_replay(n: int, seed: int = 0, minutes_after: float = 10.0, test_start_ns: float | None = None, thr_min: float | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(cases, stream): `n` random LaDe tasks from the held-out TEST window that are still open at as_of (duration > minutes_after)."""
    stream = F.lade_stream("sh")
    t_ns = stream["as_of_ts"].astype("int64").to_numpy()
    ok = (stream["value"].to_numpy() > minutes_after) & stream["acc_lat"].notna().to_numpy()
    if test_start_ns is not None:
        ok &= t_ns >= test_start_ns
    idx = np.flatnonzero(ok)
    pick = np.random.default_rng(seed).choice(idx, size=min(n, len(idx)), replace=False)
    cases = stream.iloc[np.sort(pick)].copy()
    cases["_row"] = np.sort(pick)
    if thr_min is not None:
        cases["slow"] = (cases["value"] > thr_min).astype(int)
    return cases.reset_index(drop=True), stream
