"""Does a sequence model beat a strong tabular baseline on LaDe slow-task risk?  (decision experiment, not a product)

Information given to every contender is the same: the 5 context features, the shrunk aoi/courier/region history, and the courier's
last K resolved tasks (duration and recency - only tasks whose outcome was known before this task's as_of).
    tabular_hgb          HistGradientBoosting on context + history                       (the model Dallal ships)
    tabular_hgb_lags     the same + the K lag durations / gaps as explicit columns        (strong tabular use of the sequence)
    gru_sequence         GRU over the K-step courier sequence, concatenated with the standardised tabular vector -> MLP
Adoption rule, fixed beforehand: the sequence model replaces the tabular one only if it beats the best tabular contender by >= 5%
relative VALID PR-AUC and the margin holds on TEST. Otherwise tabular stays (cheaper, no serving-time sequence store).

Run: python -I -m dallal.ml.sequence   -> docs/ml/sequence_experiment.json
"""

from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
import torch
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score
from torch import nn

from dallal.config import PATHS
from dallal.data.splits import time_split
from dallal.ml import features as F
from dallal.ml.metrics import binary_report

K = 16
BASE = ["hour", "dow", "aoi_type", "open_tasks_courier", "accept_dist_m", "aoi_past_logdur", "aoi_past_n", "courier_past_logdur", "courier_past_n", "region_past_logdur", "region_past_n"]


def courier_sequences(stream: pd.DataFrame, rows: np.ndarray, k: int = K) -> tuple[np.ndarray, np.ndarray]:
    """For each requested stream row: the courier's previous `k` tasks resolved strictly before that row's as_of.

    Returns (seq [n,k,2] = (log duration, log1p hours since that outcome became known), mask [n,k]); oldest first.
    """
    cour = stream["courier_id"].to_numpy()
    as_i = stream["as_of_ts"].astype("int64").to_numpy()
    av = stream["available_at_ts"].astype("int64").to_numpy()
    ld = stream["log_dur"].to_numpy(dtype="float64")
    want = np.zeros(len(stream), dtype=bool)
    want[rows] = True
    slot = np.full(len(stream), -1)
    slot[rows] = np.arange(len(rows))
    seq = np.zeros((len(rows), k, 2), dtype="float32")
    mask = np.zeros((len(rows), k), dtype="float32")
    order = np.argsort(cour, kind="stable")
    cs = cour[order]
    bounds = np.flatnonzero(np.r_[True, cs[1:] != cs[:-1], True])
    ns_per_hour = 3.6e12
    for a, b in zip(bounds[:-1], bounds[1:], strict=False):
        idx = order[a:b]
        o = np.argsort(av[idx], kind="stable")
        av_sorted = av[idx][o]
        ld_sorted = ld[idx][o]
        targets = idx[want[idx]]
        if not len(targets):
            continue
        pos = np.searchsorted(av_sorted, as_i[targets], side="left")  # outcomes known strictly before as_of
        for step in range(k):  # step 0 = oldest of the last k
            j = pos - k + step
            ok = j >= 0
            jj = np.where(ok, j, 0)
            s = slot[targets]
            seq[s, step, 0] = np.where(ok, ld_sorted[jj], 0.0)
            seq[s, step, 1] = np.where(ok, np.log1p(np.maximum(as_i[targets] - av_sorted[jj], 0) / ns_per_hour), 0.0)
            mask[s, step] = ok.astype("float32")
    return seq, mask


class GruNet(nn.Module):
    def __init__(self, n_tab: int, hidden: int = 32):
        super().__init__()
        self.gru = nn.GRU(3, hidden, batch_first=True)
        self.head = nn.Sequential(nn.Linear(hidden + n_tab, 64), nn.ReLU(), nn.Dropout(0.1), nn.Linear(64, 1))

    def forward(self, seq: torch.Tensor, mask: torch.Tensor, tab: torch.Tensor) -> torch.Tensor:
        h = self.gru(torch.cat([seq, mask.unsqueeze(-1)], dim=-1))[1][-1]
        return self.head(torch.cat([h, tab], dim=-1)).squeeze(-1)


def _fit_gru(seq, mask, tab, y, tr, va, te, epochs: int = 6, seed: int = 0):
    torch.manual_seed(seed)
    net = GruNet(tab.shape[1])
    opt = torch.optim.Adam(net.parameters(), lr=2e-3)
    lossf = nn.BCEWithLogitsLoss()
    S, M, T, Y = (torch.as_tensor(a) for a in (seq, mask, tab, y.astype("float32")))

    def predict(idx: np.ndarray) -> np.ndarray:
        net.eval()
        out = []
        with torch.no_grad():
            for i in range(0, len(idx), 8192):
                b = idx[i:i + 8192]
                out.append(torch.sigmoid(net(S[b], M[b], T[b])).numpy())
        return np.concatenate(out)

    best, best_state, curve = -1.0, None, []
    rng = np.random.default_rng(seed)
    for ep in range(epochs):
        net.train()
        perm = rng.permutation(tr)
        for i in range(0, len(perm), 1024):
            b = perm[i:i + 1024]
            opt.zero_grad()
            lossf(net(S[b], M[b], T[b]), Y[b]).backward()
            opt.step()
        pv = predict(va)
        ap = float(average_precision_score(y[va], pv))
        curve.append({"epoch": ep + 1, "valid_pr_auc": round(ap, 4), "valid_roc_auc": round(float(roc_auc_score(y[va], pv)), 4)})
        if ap > best:
            best, best_state = ap, {k: v.clone() for k, v in net.state_dict().items()}
    net.load_state_dict(best_state)
    return predict(va), predict(te), curve


def main() -> None:
    t0 = time.time()
    stream = F.lade_stream("sh")
    x = F.lade_frame("sh", sample=400_000)
    sp = time_split(x, "_t", origin_col="_origin")
    thr = float(np.quantile(x["_dur"].to_numpy()[sp.train], 0.9))
    y = (x["_dur"].to_numpy() > thr).astype(int)
    seq, mask = courier_sequences(stream, x["_row"].to_numpy())
    # tabular vector standardised with TRAIN statistics only
    tab = x[BASE].fillna(0.0).to_numpy(dtype="float32")
    mu, sd = tab[sp.train].mean(0), tab[sp.train].std(0) + 1e-6
    tab = (tab - mu) / sd
    seq[..., 0] = np.where(mask > 0, seq[..., 0] - 5.0, 0.0)  # centre log durations roughly; mask carries presence
    seq[..., 1] = seq[..., 1] / 5.0
    tr, va, te = sp.train, sp.valid, sp.test
    out: dict = {"task": "lade_slow_delivery_task (Shanghai)", "k_lags": K, "n": {"train": int(len(tr)), "valid": int(len(va)), "test": int(len(te))}, "contenders": {}}

    def hgb(cols_extra: np.ndarray | None):
        a = x[BASE].to_numpy(dtype="float64")
        if cols_extra is not None:
            a = np.hstack([a, cols_extra])
        m = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06, max_leaf_nodes=31, l2_regularization=1.0, random_state=0).fit(a[tr], y[tr])
        return m.predict_proba(a[va])[:, 1], m.predict_proba(a[te])[:, 1]

    lag = np.where(mask[..., None] > 0, seq, np.nan).reshape(len(x), -1)
    results = {"tabular_hgb": hgb(None), "tabular_hgb_lags": hgb(lag)}
    pv, pt, curve = _fit_gru(seq, mask, tab, y, tr, va, te)
    results["gru_sequence"] = (pv, pt)
    for name, (pv, pt) in results.items():
        out["contenders"][name] = {"valid": binary_report(y[va], pv), "test": binary_report(y[te], pt)}
    out["gru_valid_curve"] = curve
    base_valid = max(out["contenders"][n]["valid"]["pr_auc"] for n in ("tabular_hgb", "tabular_hgb_lags"))
    base_name = max(("tabular_hgb", "tabular_hgb_lags"), key=lambda n: out["contenders"][n]["valid"]["pr_auc"])
    g = out["contenders"]["gru_sequence"]
    wins_valid = g["valid"]["pr_auc"] >= 1.05 * base_valid
    wins_test = g["test"]["pr_auc"] >= 1.05 * out["contenders"][base_name]["test"]["pr_auc"]
    out["decision"] = {"best_tabular_on_valid": base_name, "sequence_beats_by_5pct_on_valid": bool(wins_valid), "holds_on_test": bool(wins_test),
                       "adopt_sequence_model": bool(wins_valid and wins_test),
                       "reading": "Sequence adopted." if wins_valid and wins_test else "Tabular retained: the sequence model did not clear the pre-registered margin on both windows."}
    out["seconds"] = round(time.time() - t0, 1)
    p = PATHS.docs / "ml" / "sequence_experiment.json"
    p.write_text(json.dumps(out, indent=2) + "\n")
    for n, v in out["contenders"].items():
        print(n, "valid pr/roc", v["valid"]["pr_auc"], v["valid"]["roc_auc"], "| test pr/roc", v["test"]["pr_auc"], v["test"]["roc_auc"])
    print(out["decision"])


if __name__ == "__main__":
    main()
