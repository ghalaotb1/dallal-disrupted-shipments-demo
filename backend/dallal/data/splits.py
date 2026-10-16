"""Time-aware, entity-aware, origin-aware splitting.

Rules enforced here (each one comes from a measured finding in docs/data/DATASET_DECISION_REPORT.md):
  * Splits are by time, never random: Amazon's failure rate drifted 0.99% -> 0.56% in six weeks and Olist's late rate
    ranges 1.5% -> 20% by month.
  * An embargo gap separates train from test so labels that resolve after the cut cannot leak into training.
  * Only OBSERVED rows may appear in a held-out split. SYNTHETIC/DEMO rows are rejected from validation/test by raising.
  * Sparse, right-censored edge periods can be excluded (Olist 2016-12 and 2018-09).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


class SplitError(ValueError):
    pass


@dataclass(frozen=True)
class Split:
    train: np.ndarray  # integer positions into the frame
    valid: np.ndarray
    test: np.ndarray
    cuts: dict[str, float]


def time_split(
    df: pd.DataFrame,
    time_col: str,
    *,
    valid_frac: float = 0.15,
    test_frac: float = 0.2,
    embargo: float = 0.0,
    origin_col: str = "origin",
) -> Split:
    """Chronological train/valid/test split on a numeric or datetime column.

    `embargo` is in the same unit as `time_col` (days for day-index columns, Timedelta for datetimes) and is removed
    between consecutive blocks. Raises if any non-observed row would land in valid/test.
    """
    t = df[time_col]
    if t.isna().any():
        raise SplitError(f"{time_col} contains nulls; drop or impute explicitly before splitting")
    tv = t.astype("int64").to_numpy() if np.issubdtype(t.dtype, np.datetime64) else t.to_numpy(dtype=float)
    emb = float(embargo.value) if isinstance(embargo, pd.Timedelta) else float(embargo)
    q_test = np.quantile(tv, 1 - test_frac)
    q_valid = np.quantile(tv, 1 - test_frac - valid_frac)
    train = np.flatnonzero(tv < q_valid - emb)
    valid = np.flatnonzero((tv >= q_valid) & (tv < q_test - emb))
    test = np.flatnonzero(tv >= q_test)
    if origin_col in df:
        o = df[origin_col].astype(str).to_numpy()
        for name, idx in (("valid", valid), ("test", test)):
            bad = set(o[idx]) - {"observed", "engineered"}
            if bad:
                raise SplitError(f"{name} split would contain non-observed origins {sorted(bad)}")
    if not (len(train) and len(valid) and len(test)):
        raise SplitError("empty split; check fractions/embargo")
    return Split(train, valid, test, {"valid_start": float(q_valid), "test_start": float(q_test), "embargo": emb})


def drop_sparse_periods(df: pd.DataFrame, period_col: str, min_rows: int) -> pd.DataFrame:
    """Remove periods with fewer than `min_rows` rows (right-censored edges of a collection window)."""
    counts = df.groupby(period_col)[period_col].transform("size")
    return df[counts >= min_rows]


def group_disjoint(df: pd.DataFrame, group_col: str, split: Split) -> dict[str, float]:
    """Report entity overlap between train and test (e.g. couriers/routes). Informational: overlap is realistic for
    couriers (they recur) but must be known when interpreting results."""
    g = df[group_col].to_numpy()
    tr, te = set(g[split.train]), set(g[split.test])
    return {"test_groups": len(te), "seen_in_train_frac": round(len(te & tr) / max(len(te), 1), 4)}
