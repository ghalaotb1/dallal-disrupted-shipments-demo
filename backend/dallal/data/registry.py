"""Typed access to registry/datasets.yaml (the dataset decision manifest)."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from dallal.config import PATHS

Decision = Literal["select", "secondary", "reject"]
Evidence = Literal["data", "schema", "card"]
DataKind = Literal["observed", "derived_public", "simulated", "synthetic", "reference", "unknown"]


class FileSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    url: str
    bytes: int | None = None
    sha256: str | None = None
    md5: str | None = None
    group: str | None = None  # "large" files are skipped unless --all is passed


class DatasetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    decision: Decision
    evidence_level: Evidence
    data_kind: DataKind
    homepage: str | None = None
    paper: str | None = None
    license: str | None = None
    redistribution: str | None = None
    pinned_version: str | None = None
    scale: str | None = None
    supports: list[str] = Field(default_factory=list)
    does_not_support: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    reason: str | None = None  # why rejected
    files: list[FileSpec] = Field(default_factory=list)


class Registry(BaseModel):
    version: int
    generated: str
    datasets: list[DatasetSpec]

    def get(self, dataset_id: str) -> DatasetSpec:
        for d in self.datasets:
            if d.id == dataset_id:
                return d
        raise KeyError(f"unknown dataset id: {dataset_id}")

    def by_decision(self, decision: Decision) -> list[DatasetSpec]:
        return [d for d in self.datasets if d.decision == decision]


@lru_cache(maxsize=1)
def load_registry() -> Registry:
    with open(PATHS.registry, encoding="utf-8") as fh:
        reg = Registry.model_validate(yaml.safe_load(fh))
    ids = [d.id for d in reg.datasets]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate dataset ids in registry")
    for d in reg.datasets:
        if d.decision == "reject" and not d.reason:
            raise ValueError(f"rejected dataset {d.id} must state a reason")
        if d.decision == "select" and d.evidence_level != "data":
            raise ValueError(f"selected dataset {d.id} must have been inspected at data level")
        if d.decision == "select" and not (d.license and d.redistribution):
            raise ValueError(f"selected dataset {d.id} must document license and redistribution")
    return reg
