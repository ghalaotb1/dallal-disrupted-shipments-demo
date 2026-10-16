"""Convenience entry point: `dallal-api` starts the server (uvicorn)."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run("dallal.api.app:app", host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8000")), log_level="info")


if __name__ == "__main__":
    main()
