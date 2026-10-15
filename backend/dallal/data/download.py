"""Reproducible dataset fetcher: streaming, resumable, verified, and recorded in a lock file.

Downloads land in backend/.data/raw/<dataset_id>/ (git-ignored). Each file's sha256 is written to
registry/datasets.lock.json so a second machine can verify it fetched byte-identical data.
Downloaded files are treated as untrusted data: they are only ever parsed, never executed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import time
from pathlib import Path

import requests

from dallal.config import PATHS
from dallal.data.registry import DatasetSpec, FileSpec, load_registry

log = logging.getLogger("dallal.data.download")
CHUNK = 1 << 20
UA = {"User-Agent": "dallal-data-fetch/0.1 (+hackathon research; contact: repo owner)"}


def raw_path(dataset_id: str, filename: str) -> Path:
    return PATHS.raw / dataset_id / filename


def _hash(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _read_lock() -> dict:
    if PATHS.lock.exists():
        return json.loads(PATHS.lock.read_text())
    return {}


def _write_lock(lock: dict) -> None:
    PATHS.lock.parent.mkdir(parents=True, exist_ok=True)
    PATHS.lock.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")


def _curl(url: str, part: Path) -> None:
    """Fallback transport: some CDNs (e.g. Mendeley) reject python-requests at the edge but serve curl."""
    if not shutil.which("curl"):
        raise RuntimeError("curl not available for fallback download")
    subprocess.run(
        ["curl", "-sS", "--fail", "-L", "-C", "-", "-A", UA["User-Agent"], "--retry", "3", "-o", str(part), url],
        check=True,
    )


def _stream(url: str, dest: Path) -> None:
    """Download with resume support into dest.part, then atomically rename."""
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, 5):
        have = part.stat().st_size if part.exists() else 0
        headers = dict(UA)
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with requests.get(url, headers=headers, stream=True, timeout=60, allow_redirects=True) as r:
                if r.status_code == 416:  # already complete
                    break
                r.raise_for_status()
                mode = "ab" if (have and r.status_code == 206) else "wb"
                with open(part, mode) as fh:
                    for chunk in r.iter_content(CHUNK):
                        fh.write(chunk)
            break
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 403:
                log.warning("403 from %s via requests; retrying with curl", url)
                _curl(url, part)
                break
            log.warning("download attempt %d failed for %s: %s", attempt, url, exc)
            time.sleep(2 * attempt)
        except (requests.RequestException, OSError) as exc:
            log.warning("download attempt %d failed for %s: %s", attempt, url, exc)
            time.sleep(2 * attempt)
    else:
        raise RuntimeError(f"giving up on {url}")
    part.rename(dest)


def fetch_file(spec: DatasetSpec, f: FileSpec, lock: dict, force: bool = False) -> Path:
    dest = raw_path(spec.id, f.name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    key = f"{spec.id}/{f.name}"
    if dest.exists() and not force:
        log.info("have %s", key)
    else:
        log.info("fetching %s <- %s", key, f.url)
        _stream(f.url, dest)
    size = dest.stat().st_size
    sha = _hash(dest, "sha256")
    if f.sha256 and sha != f.sha256:
        dest.unlink()
        raise RuntimeError(f"sha256 mismatch for {key}: got {sha}, registry says {f.sha256}")
    if f.md5 and _hash(dest, "md5") != f.md5:
        dest.unlink()
        raise RuntimeError(f"md5 mismatch for {key}")
    # Amazon/other sizes in the registry are approximate (rounded MB) unless a hash is pinned.
    if f.bytes and not (f.sha256 or f.md5) and abs(size - f.bytes) > max(0.02 * f.bytes, 50_000):
        log.warning("size of %s is %d, registry expected ~%d", key, size, f.bytes)
    prior = lock.get(key)
    if prior and prior["sha256"] != sha:
        log.warning("%s changed upstream since lock was written (%s -> %s)", key, prior["sha256"][:12], sha[:12])
    lock[key] = {"sha256": sha, "bytes": size, "url": f.url}
    return dest


def fetch_dataset(dataset_id: str, include_large: bool = False, force: bool = False) -> list[Path]:
    spec = load_registry().get(dataset_id)
    if spec.decision == "reject":
        raise ValueError(f"{dataset_id} is rejected ({spec.reason}); refusing to fetch")
    if not spec.files:
        raise ValueError(f"{dataset_id} has no downloadable files in the registry")
    lock = _read_lock()
    out = []
    for f in spec.files:
        if f.group == "large" and not include_large:
            log.info("skip large file %s (pass --all to include)", f.name)
            continue
        out.append(fetch_file(spec, f, lock, force))
        _write_lock(lock)
    return out


def verify_dataset(dataset_id: str) -> dict[str, bool]:
    """Compare on-disk files with the committed lock (used on a fresh machine after fetch)."""
    spec = load_registry().get(dataset_id)
    lock = _read_lock()
    res = {}
    for f in spec.files:
        p = raw_path(spec.id, f.name)
        entry = lock.get(f"{spec.id}/{f.name}")
        res[f.name] = bool(p.exists() and entry and _hash(p, "sha256") == entry["sha256"])
    return res
