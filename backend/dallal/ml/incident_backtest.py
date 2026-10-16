"""Incident-detector backtest: REAL operational noise + INJECTED surges.

No public dataset labels operational incidents. So we measure the detector the only honest way available:
  * Noise is real: hourly counts of 'slow' delivery completions per region in LaDe-Shanghai (slow = duration above the TRAIN-period P90).
  * False alarms are counted on the untouched real series (any alarm is a false alarm, since no incident is labelled).
  * Detection is measured by injecting synthetic surges (extra slow completions in one region for two hours) into the real series.
The detector is the same rule the agent's `check_incident_context` uses: count >= 3 and z >= 3 against a same-hour-of-day baseline
from the previous 14 days (std floored at 0.35). Results describe detector behaviour on real noise, not real incident frequency.

Two detectors are compared: the naive defaults currently used by the agent's `check_incident_context`, and a quasi-Poisson detector whose
dispersion and alarm threshold are calibrated on an earlier window to a target false-alarm rate, then evaluated on a later window.

Run: python -I -m dallal.ml.incident_backtest
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from dallal.config import PATHS
from dallal.tools.signals import INCIDENT_MIN_COUNT, INCIDENT_Z, STD_FLOOR

BASE_DAYS = 14
MULTS = (1.0, 2.0, 4.0, 8.0, 16.0)
Z_GRID = (3, 4, 5, 6, 8, 10, 15)


def hourly_slow_counts(code: str = "sh", min_total: int = 2000) -> tuple[pd.DataFrame, float]:
    base = PATHS.canonical / "lade"
    lab = pd.read_parquet(base / f"label.delivery_{code}.parquet", columns=["entity_id", "value", "as_of_ts", "available_at_ts"])
    sh = pd.read_parquet(base / f"shipment.delivery_{code}.parquet", columns=["shipment_id", "dest_region"]).rename(columns={"shipment_id": "entity_id"})
    df = lab.merge(sh, on="entity_id")
    cut = df["as_of_ts"].quantile(0.6)  # threshold from the earliest 60% of the timeline only
    thr = float(df.loc[df["as_of_ts"] <= cut, "value"].quantile(0.9))
    df["slow"] = (df["value"] > thr).astype(int)
    df["h"] = df["available_at_ts"].dt.floor("h")  # a slow outcome is observed when the task completes
    keep = df.groupby("dest_region").size()
    df = df[df["dest_region"].isin(keep[keep >= min_total].index)]
    c = df[df.slow == 1].groupby(["dest_region", "h"]).size().unstack(0).fillna(0)
    full = pd.date_range(df["h"].min().floor("D"), df["h"].max().ceil("D"), freq="h")
    return c.reindex(full, fill_value=0).astype(float), thr


def baseline(C: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Same-hour-of-day mean/std over the previous BASE_DAYS days. C: [T, R]."""
    T = C.shape[0]
    stack = np.full((BASE_DAYS, *C.shape), np.nan)
    for k in range(1, BASE_DAYS + 1):
        stack[k - 1, 24 * k:] = C[: T - 24 * k]
    return np.nanmean(stack, axis=0), np.nanstd(stack, axis=0, ddof=1)


def alarms(C: np.ndarray, mean: np.ndarray, std: np.ndarray, *, phi: float | None = None, z_star: float = INCIDENT_Z, min_count: int = INCIDENT_MIN_COUNT) -> np.ndarray:
    """phi=None -> the naive detector used by the agent's defaults (empirical std, floored). Otherwise a quasi-Poisson detector:
    variance = phi * max(mean, 0.5), with phi calibrated on history (counts are overdispersed relative to Poisson)."""
    if phi is None:
        z = (C - mean) / np.maximum(std, STD_FLOOR)
    else:
        z = (C - mean) / np.sqrt(phi * np.maximum(mean, 0.5))
    return (C >= min_count) & (z >= z_star) & ~np.isnan(mean)


def calibrate(C: np.ndarray, mean: np.ndarray, std: np.ndarray, lo: int, hi: int, target_fa: float) -> dict:
    """Fit dispersion and pick the smallest z* whose false-alarm rate on the CALIBRATION window is <= target (per scope-week)."""
    m = mean[lo:hi]
    ok = ~np.isnan(m)
    resid2 = (C[lo:hi][ok] - m[ok]) ** 2
    phi = float(resid2.sum() / np.maximum(m[ok], 0.5).sum())
    weeks = C.shape[1] * (hi - lo) / (24 * 7)
    for z in (3, 3.5, 4, 5, 6, 8, 10, 15, 20):
        fa = alarms(C[lo:hi], m, std[lo:hi], phi=phi, z_star=z).sum() / weeks
        if fa <= target_fa:
            return {"phi": round(phi, 3), "z_star": z, "calibration_false_alarms_per_scope_week": round(float(fa), 4)}
    return {"phi": round(phi, 3), "z_star": 20, "calibration_false_alarms_per_scope_week": round(float(fa), 4)}


def inject_eval(C, mean, std, A_clean, det_kwargs, t0, T, R, scope_mean, terciles, seed, n_inject=300):
    rng = np.random.default_rng(seed)
    out = {}
    for mult in MULTS:
        hits, delays, by_size = [], [], {"small": [], "medium": [], "large": []}
        for _ in range(n_inject):
            r = int(rng.integers(R))
            t = int(rng.integers(t0 + 1, T - 6))
            lam = max(float(mean[t, r]) if not np.isnan(mean[t, r]) else 0.0, 0.5)
            extra = rng.poisson(max(3.0, mult * lam), size=2)  # surge over two consecutive hours (>=3 extra slow completions)
            Cx = C[t - 1: t + 5, r].copy()
            Cx[1:3] += extra
            ax = alarms(Cx[:, None], mean[t - 1: t + 5, r][:, None], std[t - 1: t + 5, r][:, None], **det_kwargs)[:, 0]
            det = ax & ~A_clean[t - 1: t + 5, r]  # an alarm already firing on the clean series is not a detection of the injection
            hits.append(bool(det.any()))
            if det.any():
                delays.append(int(np.argmax(det)) - 1)
            size = "small" if scope_mean[r] <= terciles[0] else "medium" if scope_mean[r] <= terciles[1] else "large"
            by_size[size].append(hits[-1])
        out[f"{mult:g}x_local_baseline"] = {"detection_rate": round(float(np.mean(hits)), 3), "median_delay_hours": float(np.median(delays)) if delays else None,
                                            "detection_rate_by_scope_size": {k: round(float(np.mean(v)), 3) if v else None for k, v in by_size.items()}}
    return out


def run(seed: int = 0, target_fa: float = 0.1) -> dict:
    counts, thr = hourly_slow_counts()
    C = counts.to_numpy()
    T, R = C.shape
    mean, std = baseline(C)
    lo, hi, t0 = int(T * 0.3), int(T * 0.6), int(T * 0.6)  # calibrate on [30%,60%), evaluate on the last 40%
    weeks_test = R * (T - t0) / (24 * 7)
    scope_mean = np.nanmean(mean[t0:], axis=0)
    terciles = np.quantile(scope_mean, [1 / 3, 2 / 3])
    cal = calibrate(C, mean, std, lo, hi, target_fa)
    res = {"scopes": R, "hours_evaluated": T - t0, "slow_threshold_min_train_p90": round(thr, 1), "calibration": cal,
           "note": "alarms on the untouched real series are all counted as false alarms (no incident labels exist); surges are synthetic"}
    for name, kw in (("naive_agent_defaults", {}), ("calibrated_quasi_poisson", {"phi": cal["phi"], "z_star": cal["z_star"]})):
        A = alarms(C, mean, std, **kw)
        res[name] = {"false_alarms_per_scope_week": round(float(A[t0:].sum() / weeks_test), 4),
                     "injected": inject_eval(C, mean, std, A, kw, t0, T, R, scope_mean, terciles, seed)}
    curve = []  # operating curve of the quasi-Poisson detector: threshold -> (false alarms, detection by surge size)
    for z in Z_GRID:
        kw = {"phi": cal["phi"], "z_star": z}
        A = alarms(C, mean, std, **kw)
        inj = inject_eval(C, mean, std, A, kw, t0, T, R, scope_mean, terciles, seed, n_inject=200)
        curve.append({"z_star": z, "false_alarms_per_scope_week": round(float(A[t0:].sum() / weeks_test), 4),
                      "detection_rate": {k: v["detection_rate"] for k, v in inj.items()}})
    res["operating_curve_quasi_poisson"] = curve
    return res


def main() -> None:
    res = run()
    p = PATHS.docs / "ml" / "incident_backtest.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
