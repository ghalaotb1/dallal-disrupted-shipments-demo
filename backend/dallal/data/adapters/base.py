"""Adapter contract: map one source into the canonical tables it can legitimately provide."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from dallal.config import PATHS
from dallal.data.schema import TABLES, Origin, SchemaViolation, validate_frame

log = logging.getLogger("dallal.data.adapter")


def with_provenance(
    df: pd.DataFrame,
    *,
    origin: Origin,
    source_id: str,
    adapter_version: str,
    record_id_col: str | None = None,
    scenario_id: str | None = None,
    seed: int | None = None,
) -> pd.DataFrame:
    out = df.copy()
    out["origin"] = origin.value
    out["source_id"] = source_id
    out["source_record_id"] = out[record_id_col].astype(str) if record_id_col else None
    out["adapter_version"] = adapter_version
    out["scenario_id"] = scenario_id
    out["generator_seed"] = seed
    return out


def write_tables(source: str, tables: dict[str, pd.DataFrame], provides: dict[str, set[str]], part: str = "") -> None:
    """Validate against the canonical schema and write parquet under backend/.data/canonical/<source>/."""
    root = PATHS.canonical / source
    root.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        if name not in TABLES:
            raise SchemaViolation(f"{source}: unknown table {name}")
        validate_frame(name, df, provides.get(name))
        fname = f"{name}{('.' + part) if part else ''}.parquet"
        df.to_parquet(root / fname, index=False)
        log.info("%s/%s: %d rows", source, fname, len(df))


def read_table(source: str, table: str) -> pd.DataFrame:
    root = PATHS.canonical / source
    files = sorted(root.glob(f"{table}.parquet")) + sorted(root.glob(f"{table}.*.parquet"))
    if not files:
        raise FileNotFoundError(f"no canonical {table} for {source}; run `dallal-data build {source}`")
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def raw(source: str, name: str) -> Path:
    p = PATHS.raw / source / name
    if not p.exists():
        raise FileNotFoundError(f"{p} missing; run `dallal-data fetch {source}`")
    return p
