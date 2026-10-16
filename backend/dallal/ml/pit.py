"""Point-in-time context for model features: what was KNOWABLE at time t, and nothing later.

A model trained on `past_stat`-style history needs the same quantities at serving time. `PointInTimeStore` is that contract: every query takes
the instant `t` and may only use records whose outcome became available strictly before `t` (the same rule `dallal.ml.features.past_stat` applied when
the training frame was built). `LadeStore` reproduces the LaDe training features exactly from the canonical stream (used for replays and train/serve
parity tests); a production deployment implements the same interface over the operational database. `NullStore` is the honest default: no history -> abstain.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np
import pandas as pd


class PointInTimeStore(Protocol):
    name: str

    def open_tasks(self, courier_id: str, t: pd.Timestamp) -> int | None: ...
    def past_mean_logdur(self, key: str, value: str, t: pd.Timestamp) -> tuple[float, float] | None: ...


class NullStore:
    name = "none"

    def open_tasks(self, courier_id: str, t: pd.Timestamp) -> int | None:
        return None

    def past_mean_logdur(self, key: str, value: str, t: pd.Timestamp) -> tuple[float, float] | None:
        return None


class LadeStore:
    """Per-key sorted arrays over the LaDe task stream. `prior`/`prior_n` are the shrinkage constants recorded in the model card."""

    name = "lade-canonical-stream"

    def __init__(self, stream: pd.DataFrame, prior: float, prior_n: float = 10.0, keys: dict[str, str] | None = None):
        self.prior, self.prior_n = float(prior), float(prior_n)
        keys = keys or {"aoi": "dest_zone_id", "courier": "courier_id", "region": "dest_region"}
        self.arrays: dict[str, dict[str, tuple[np.ndarray, np.ndarray]]] = {}
        av = stream["available_at_ts"].astype("datetime64[ns]").astype("int64").to_numpy()  # explicit ns: a [us] column would silently misalign with Timestamp.value
        ld = stream["log_dur"].to_numpy(dtype="float64")
        for name, col in keys.items():
            grp: dict[str, tuple[np.ndarray, np.ndarray]] = {}
            k = stream[col].to_numpy()
            order = np.argsort(k, kind="stable")
            ks = k[order]
            bounds = np.flatnonzero(np.r_[True, ks[1:] != ks[:-1], True])
            for a, b in zip(bounds[:-1], bounds[1:], strict=False):
                idx = order[a:b]
                o = np.argsort(av[idx], kind="stable")
                grp[str(ks[a])] = (av[idx][o], np.r_[0.0, np.cumsum(ld[idx][o])])
            self.arrays[name] = grp
        acc = stream["as_of_ts"].astype("datetime64[ns]").astype("int64").to_numpy()
        cour = stream["courier_id"].to_numpy()
        self.open: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        order = np.argsort(cour, kind="stable")
        cs = cour[order]
        bounds = np.flatnonzero(np.r_[True, cs[1:] != cs[:-1], True])
        for a, b in zip(bounds[:-1], bounds[1:], strict=False):
            idx = order[a:b]
            self.open[str(cs[a])] = (np.sort(acc[idx]), np.sort(av[idx]))

    def open_tasks(self, courier_id: str, t: pd.Timestamp) -> int | None:
        """Tasks the courier had accepted (<= t) but not completed (done < t), excluding the case task itself, which the store contains."""
        a = self.open.get(str(courier_id))
        if a is None:
            return None
        acc, done = a
        tv = pd.Timestamp(t).value
        return int(max(np.searchsorted(acc, tv, side="right") - 1 - np.searchsorted(done, tv, side="left"), 0))

    def past_mean_logdur(self, key: str, value: str, t: pd.Timestamp) -> tuple[float, float] | None:
        g = self.arrays.get(key, {}).get(str(value))
        n_prior = self.prior_n
        if g is None:  # never-seen key: the shrunk mean is the prior with zero support (same as training)
            return self.prior, 0.0
        av, cs = g
        pos = int(np.searchsorted(av, pd.Timestamp(t).value, side="left"))  # outcomes known strictly before t
        return float((cs[pos] + self.prior * n_prior) / (pos + n_prior)), float(pos)


_LADE: dict[str, Any] = {}


def lade_store(card_extra: dict[str, Any]) -> PointInTimeStore:
    """Build (once) the replay store from the canonical LaDe stream on this machine; NullStore where the data is absent (e.g. a hosted container)."""
    if "s" in _LADE:
        return _LADE["s"]
    try:
        from dallal.ml import features as F

        stream = F.lade_stream("sh")
        _LADE["s"] = LadeStore(stream, card_extra["history_prior_logdur"], card_extra.get("history_prior_n", 10.0), card_extra.get("history_keys"))
    except Exception:  # noqa: BLE001 - no data / no card constants: abstain, never guess
        _LADE["s"] = NullStore()
    return _LADE["s"]
