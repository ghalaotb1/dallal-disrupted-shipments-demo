"""Evaluation metrics for rare-event risk models: ranking, lift and calibration — never accuracy."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score


def ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error with equal-mass bins."""
    order = np.argsort(p)
    y, p = y[order], p[order]
    chunks = np.array_split(np.arange(len(p)), bins)
    return float(sum(len(c) / len(p) * abs(y[c].mean() - p[c].mean()) for c in chunks if len(c)))


def binary_report(y: np.ndarray, p: np.ndarray, top_frac: float = 0.1) -> dict[str, float]:
    k = max(1, int(len(p) * top_frac))
    top = np.argsort(-p)[:k]
    base = float(y.mean())
    return {
        "n": int(len(y)), "prevalence": round(base, 5), "roc_auc": round(float(roc_auc_score(y, p)), 4),
        "pr_auc": round(float(average_precision_score(y, p)), 4), "pr_auc_lift_over_prevalence": round(float(average_precision_score(y, p)) / base, 2),
        f"precision@top{int(top_frac * 100)}%": round(float(y[top].mean()), 4), f"recall@top{int(top_frac * 100)}%": round(float(y[top].sum() / max(y.sum(), 1)), 4),
        f"lift@top{int(top_frac * 100)}%": round(float(y[top].mean() / base), 2), "brier": round(float(brier_score_loss(y, p)), 5),
        "brier_prevalence_baseline": round(float(brier_score_loss(y, np.full_like(p, base))), 5), "ece": round(ece(y, p), 5),
    }
