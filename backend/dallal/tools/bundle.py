"""CaseBundle: the agent's window onto operational data, expressed in the canonical tables.

A bundle is a set of canonical-schema DataFrames plus a clock. Fixtures (synthetic or demo) and, later, queries against a
production store both present this same surface, so tools never change. Every accessor filters to `as_of`: the agent can
only see what was knowable at decision time (leakage defence at inference time).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from dallal.data.schema import TABLES, validate_frame


def _ts_cols(table: str) -> list[str]:
    return [n for n, f in TABLES[table].model_fields.items() if "Timestamp" in str(f.annotation)]


@dataclass
class Bundle:
    scenario_id: str
    as_of: pd.Timestamp
    subject_id: str
    trigger: dict[str, Any]
    tables: dict[str, pd.DataFrame]
    expected: dict[str, Any] = field(default_factory=dict)  # evaluation-only; never exposed to tools

    # ── persistence ──
    @classmethod
    def from_json(cls, path: str | Path) -> Bundle:
        raw = json.loads(Path(path).read_text())
        tables = {}
        for name, rows in raw["tables"].items():
            df = pd.DataFrame(rows)
            for c in _ts_cols(name):
                if c in df:
                    df[c] = pd.to_datetime(df[c], utc=False)
            tables[name] = df
        return cls(raw["scenario_id"], pd.Timestamp(raw["as_of"]), raw["subject_id"], raw.get("trigger", {}), tables, raw.get("expected", {}))

    def to_dict(self) -> dict[str, Any]:
        return {"scenario_id": self.scenario_id, "as_of": self.as_of.isoformat(), "subject_id": self.subject_id, "trigger": self.trigger, "expected": self.expected,
                "tables": {n: json.loads(df.to_json(orient="records", date_format="iso")) for n, df in self.tables.items()}}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Bundle:
        tables = {}
        for name, rows in raw["tables"].items():
            df = pd.DataFrame(rows)
            for c in _ts_cols(name):
                if c in df:
                    df[c] = pd.to_datetime(df[c], utc=False)
            tables[name] = df
        return cls(raw["scenario_id"], pd.Timestamp(raw["as_of"]), raw["subject_id"], raw.get("trigger", {}), tables, raw.get("expected", {}))

    def to_json(self, path: str | Path) -> None:
        out = {"scenario_id": self.scenario_id, "as_of": self.as_of.isoformat(), "subject_id": self.subject_id,
               "trigger": self.trigger, "expected": self.expected,
               "tables": {n: json.loads(df.to_json(orient="records", date_format="iso")) for n, df in self.tables.items()}}
        Path(path).write_text(json.dumps(out, indent=1) + "\n")

    def validate(self) -> None:
        for name, df in self.tables.items():
            validate_frame(name, df)

    # ── accessors (all as_of-filtered) ──
    def _t(self, name: str) -> pd.DataFrame:
        return self.tables.get(name, pd.DataFrame())

    def shipment(self, sid: str) -> dict[str, Any]:
        df = self._t("shipment")
        row = df[df["shipment_id"] == sid]
        if row.empty:
            raise KeyError(sid)
        return row.iloc[0].to_dict()

    def shipments(self) -> pd.DataFrame:
        return self._t("shipment")

    def events(self, sid: str) -> pd.DataFrame:
        ev = self._t("event")
        if ev.empty:
            return ev
        e = ev[(ev["shipment_id"] == sid) & (ev["ts"] <= self.as_of)]
        return e.sort_values("ts")

    def all_events(self) -> pd.DataFrame:
        ev = self._t("event")
        return ev[ev["ts"] <= self.as_of] if not ev.empty else ev

    def row(self, table: str, key: str, value: str) -> dict[str, Any] | None:
        df = self._t(table)
        if df.empty:
            return None
        r = df[df[key] == value]
        if "ts" in r:
            r = r[r["ts"] <= self.as_of].sort_values("ts")
        return None if r.empty else r.iloc[-1].to_dict()

    def exception(self, sid: str) -> dict[str, Any] | None:
        df = self._t("exception")
        if df.empty:
            return None
        r = df[(df["shipment_id"] == sid) & (df["recorded_ts"] <= self.as_of)].sort_values("recorded_ts")
        return None if r.empty else r.iloc[-1].to_dict()

    def exceptions(self) -> pd.DataFrame:
        df = self._t("exception")
        return df[df["recorded_ts"] <= self.as_of] if not df.empty else df
