"""Central configuration: filesystem layout and environment-driven settings. No secrets live here."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


@dataclass(frozen=True)
class Paths:
    root: Path = BACKEND_ROOT
    registry: Path = BACKEND_ROOT / "registry" / "datasets.yaml"
    lock: Path = BACKEND_ROOT / "registry" / "datasets.lock.json"
    data: Path = Path(os.environ.get("DALLAL_DATA_DIR", BACKEND_ROOT / ".data"))
    fixtures: Path = BACKEND_ROOT / "fixtures"
    traces: Path = BACKEND_ROOT / "evals" / "traces"
    docs: Path = REPO_ROOT / "docs"

    @property
    def raw(self) -> Path:
        return self.data / "raw"

    @property
    def canonical(self) -> Path:
        return self.data / "canonical"

    @property
    def artifacts(self) -> Path:
        return BACKEND_ROOT / "artifacts"


PATHS = Paths()

# Anthropic key is read from the environment only; never from files in the repo.
ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
DEFAULT_LLM_MODEL = os.environ.get("DALLAL_LLM_MODEL", "claude-sonnet-5-5")
