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


class ReplayHub:
    """Serves real held-out LaDe tasks to the agent for the live demo (local only: the canonical tables are not redistributed). Caches the stream and the store."""

    def __init__(self) -> None:
        self.cases: dict[str, pd.Series] = {}
        self._stream: pd.DataFrame | None = None
        self._card = None

    @staticmethod
    def available() -> bool:
        from dallal.config import PATHS

        return (PATHS.canonical / "lade" / "shipment.delivery_sh.parquet").exists()

    def _load(self):
        if self._stream is None:
            from dallal.ml import registry

            self._card = registry.load("lade_slow_task_v1").card
            self._stream = F.lade_stream("sh")
        return self._stream, self._card

    def new_case(self, seed: int = 0, minutes_after: float = 10.0) -> tuple[str, Bundle, dict]:
        stream, card = self._load()
        t_ns = stream["as_of_ts"].astype("datetime64[ns]").astype("int64").to_numpy()
        ok = (stream["value"].to_numpy() > minutes_after) & stream["acc_lat"].notna().to_numpy() & (t_ns >= card.split["cuts"]["test_start"])
        idx = np.flatnonzero(ok)
        row = stream.iloc[int(np.random.default_rng(seed).choice(idx))]
        b = lade_bundle(row, minutes_after)
        cid = f"replay-{seed}"
        self.cases[cid] = row
        meta = {"case_id": cid, "source": "LaDe (Cainiao), Shanghai - real observed tasks, held-out TEST window (after the model's training period)", "not_spl": True,
                "accepted_at": row["as_of_ts"].strftime("%m-%d %H:%M"), "as_of": b.as_of.strftime("%m-%d %H:%M"), "timestamps_note": "LaDe publishes month/day/time but not the year", "slow_threshold_min": card.extra["slow_threshold_min"]}
        return cid, b, meta

    def outcome(self, case_id: str) -> dict:
        _, card = self._load()
        r = self.cases[case_id]
        thr = card.extra["slow_threshold_min"]
        return {"case_id": case_id, "duration_min": float(r["value"]), "slow_threshold_min": thr, "slow": bool(r["value"] > thr), "note": "revealed only after the agent decided; this is the real outcome recorded in the dataset"}


HUB = ReplayHub()
