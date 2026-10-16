"""Publication-style charts from the committed results (docs/experiments/results/*.csv|json). Colours: validated categorical palette, fixed order per entity, light surface.

Run: python -I -m dallal.eval.charts   -> docs/experiments/charts/*.png (+ .svg)
Every chart title says what it is, its source (real data vs SYNTHETIC simulation), and n.
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from dallal.config import PATHS  # noqa: E402

R = PATHS.docs / "experiments" / "results"
OUT = PATHS.docs / "experiments" / "charts"
BLUE, ORANGE, AQUA, VIOLET, RED, GRAY, INK, INK2 = "#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7", "#e34948", "#9a9a94", "#0b0b0b", "#52514e"
AGENT_COLOR = {"v1_legacy": GRAY, "v2_no_inquiry": BLUE, "v2_infogain": ORANGE, "v2_value": AQUA}
AGENT_LABEL = {"v1_legacy": "Legacy agent (v1)", "v2_no_inquiry": "Database-only (v2)", "v2_infogain": "Information-gain asking", "v2_value": "Decision-value asking"}
STRAT_COLOR = {"independent_naive": GRAY, "independent_strong": ORANGE, "desk_greedy": VIOLET, "independent_inquiry": RED, "coordinated_no_inquiry": BLUE, "coordinated_inquiry": AQUA, "coordinated_inquiry_adaptive": "#0b0b0b"}
STRAT_LABEL = {"independent_naive": "Per-shipment, naive", "independent_strong": "Per-shipment, strong", "desk_greedy": "Human-desk heuristic", "independent_inquiry": "Per-shipment + own questions",
               "coordinated_no_inquiry": "Coordinated", "coordinated_inquiry": "Coordinated + one inquiry", "coordinated_inquiry_adaptive": "Coordinated + inquiry, learned responsiveness"}

plt.rcParams.update({"figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "axes.edgecolor": "#c9c8c2", "axes.labelcolor": INK2, "text.color": INK, "xtick.color": INK2, "ytick.color": INK2,
                     "axes.spines.top": False, "axes.spines.right": False, "font.size": 9.5, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left", "grid.color": "#e6e5df", "grid.linewidth": 0.7,
                     "legend.frameon": False, "savefig.dpi": 200, "savefig.bbox": "tight"})


def _save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png")
    fig.savefig(OUT / f"{name}.svg")
    plt.close(fig)
    print("wrote", OUT / f"{name}.png")


def _rd(name: str) -> pd.DataFrame:
    return pd.read_csv(R / f"{name}.csv")


def pretty(s: str) -> str:
    return s.replace("_", " ")


def chart_single_gain() -> None:
    p = _rd("single_paired")
    p = p[p.metric == "utility"]
    regs = list(dict.fromkeys(p.regime))
    pairs = [("v2_value", "v2_no_inquiry", AQUA, "Decision-value asking vs database-only"), ("v2_value_adaptive", "v2_no_inquiry", VIOLET, "... with learned responsiveness"),
             ("v2_infogain", "v2_no_inquiry", ORANGE, "Information-gain asking vs database-only"), ("v2_no_inquiry", "v1_legacy", BLUE, "v2 database-only vs legacy v1")]
    fig, ax = plt.subplots(figsize=(9, 5.6))
    h = 0.19
    for j, (a, b, col, lab) in enumerate(pairs):
        d = p[(p.a == a) & (p.b == b)].set_index("regime").reindex(regs)
        y = np.arange(len(regs)) + (j - 1.5) * h
        ax.errorbar(d.mean_diff, y, xerr=[d.mean_diff - d.ci_lo, d.ci_hi - d.mean_diff], fmt="o", color=col, ecolor=col, elinewidth=1.6, capsize=0, ms=5.5, mec="#fcfcfb", mew=1.2, label=lab)
    ax.axvline(0, color=INK2, lw=0.8)
    ax.set_yticks(np.arange(len(regs)), [pretty(r) for r in regs])
    ax.invert_yaxis()
    ax.grid(axis="x")
    n = int(p.n.iloc[0])
    ax.set_xlabel("Paired difference in realised utility per case (environment units; right = better), 95% CI")
    ax.set_title(f"Effect of asking people vs looking things up, by operating regime (SYNTHETIC, n={n}/regime/agent)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, fontsize=8.5)
    _save(fig, "fig_single_regimes")


def chart_ablation() -> None:
    p = _rd("ablation_paired")
    p = p[p.metric == "utility"]
    names = {"abl_point_belief": "Point-estimate\nbelief\n(no ensemble)", "abl_no_tempering": "No correlated-\nevidence\ntempering", "abl_no_lookahead": "No set\nlook-ahead",
             "abl_asks_before_looking": "Asks before\nlooking up\ndatabases", "abl_mean_autonomy": "Autonomy at mean,\nnot pessimistic\ntail", "v2_no_inquiry": "No inquiries\nat all"}
    regs = [r for r in ("baseline", "high_uncertainty", "contradictory_evidence", "urgent_deadlines", "correlated_evidence") if r in set(p.regime)]
    cols = [BLUE, ORANGE, AQUA, VIOLET, RED]
    fig, ax = plt.subplots(figsize=(11, 5.2))
    h = 0.16
    x = np.arange(len(names))
    for j, r in enumerate(regs):
        d = p[p.regime == r].set_index("b").reindex(list(names))
        off = (j - (len(regs) - 1) / 2) * h
        ax.bar(x + off, d.mean_diff, width=h - 0.015, color=cols[j], label=pretty(r))
        ax.errorbar(x + off, d.mean_diff, yerr=[d.mean_diff - d.ci_lo, d.ci_hi - d.mean_diff], fmt="none", ecolor=INK, elinewidth=1)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_xticks(x, list(names.values()), fontsize=8.5)
    ax.set_ylabel("Full system minus ablated variant\n(utility per case; > 0 means the component helps)")
    ax.grid(axis="y")
    ax.set_title(f"Ablation: what each component contributes (SYNTHETIC, n={int(p.n.iloc[0])}/regime, 95% CI)")
    ax.legend(ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.2), fontsize=8.5)
    _save(fig, "fig_ablation")


def chart_sensitivity() -> None:
    t = _rd("sensitivity_envs").sort_values("value_minus_dbonly").reset_index(drop=True)
    s = json.loads((R / "sensitivity_summary.json").read_text())
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 4.8), gridspec_kw={"width_ratios": [1.6, 1], "wspace": 0.55})
    col = np.where(t.ci_lo > 0, AQUA, np.where(t.ci_hi < 0, RED, GRAY))
    a1.vlines(t.index, t.ci_lo, t.ci_hi, color=col, lw=1.4)
    a1.scatter(t.index, t.value_minus_dbonly, c=col, s=14, zorder=3, label="fixed assumptions (colour: significantly better / worse / n.s.)")
    if "adaptive_minus_dbonly" in t:
        a1.scatter(t.index + 0.25, t.adaptive_minus_dbonly, marker="D", s=14, color=VIOLET, zorder=4, label="learned responsiveness")
        a1.legend(loc="lower right", fontsize=8)
    a1.axhline(0, color=INK2, lw=0.8)
    a1.set_xlabel(f"{len(t)} random environments, sorted by effect")
    a1.set_ylabel("Decision-value asking minus database-only (utility/case)")
    a1.set_title("Benefit across randomly perturbed worlds (SYNTHETIC)")
    a1.grid(axis="y")
    a1.text(0.02, 0.96, f"fixed: positive in {s['value_minus_dbonly']['share_positive']:.0%}, significantly {s['value_minus_dbonly']['share_significantly_positive']:.0%} up / {s['value_minus_dbonly']['share_significantly_negative']:.0%} down;  learned: positive in {s['adaptive_minus_dbonly']['share_positive']:.0%}, {s['adaptive_minus_dbonly']['share_significantly_positive']:.0%} up / {s['adaptive_minus_dbonly']['share_significantly_negative']:.0%} down",
            transform=a1.transAxes, va="top", fontsize=8.5, color=INK2)
    k = pd.Series(s["spearman_of_benefit_with_knob"]).sort_values()
    a2.barh([pretty(i) for i in k.index], k.values, color=[AQUA if v > 0 else ORANGE for v in k.values])
    a2.axvline(0, color=INK2, lw=0.8)
    a2.set_xlabel("Spearman correlation of the benefit with the knob")
    a2.set_title("What moves the benefit")
    a2.grid(axis="x")
    _save(fig, "fig_sensitivity")


def chart_network() -> None:
    t = _rd("network_summary")
    regs = ["baseline", "low_capacity", "high_capacity", "urgent_deadlines", "flexible_deadlines", "small_incident", "large_incident", "missing_or_delayed_response", "contradictory_answers", "prior_wrong_long", "prior_wrong_short"]
    regs = [r for r in regs if r in set(t.regime)]
    strats = ["independent_naive", "independent_strong", "desk_greedy", "independent_inquiry", "coordinated_no_inquiry", "coordinated_inquiry", "coordinated_inquiry_adaptive"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), sharey=True)
    for ax, m, lab in ((axes[0], "protected_share", "Share of shipments delivered on time"), (axes[1], "regret", "Utility shortfall vs oracle per incident (lower is better)")):
        h = 0.13
        for j, s in enumerate(strats):
            d = t[t.strategy == s].set_index("regime").reindex(regs)
            y = np.arange(len(regs)) + (j - 3.0) * h
            ax.errorbar(d[m], y, xerr=[d[m] - d[m + "_lo"], d[m + "_hi"] - d[m]], fmt="o", color=STRAT_COLOR[s], ms=4.5, elinewidth=1.2, mec="#fcfcfb", label=STRAT_LABEL[s])
        ax.set_xlabel(lab)
        ax.grid(axis="x")
    axes[0].set_yticks(np.arange(len(regs)), [pretty(r) for r in regs])
    axes[0].invert_yaxis()
    n = int(t.n.iloc[0])
    fig.suptitle(f"Network recovery strategies across operating regimes (SYNTHETIC incidents, n={n}/regime, same draws for every strategy)", x=0.08, ha="left", fontsize=11, fontweight="bold")
    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=8.5, bbox_to_anchor=(0.5, -0.06))
    _save(fig, "fig_network_regimes")


def chart_network_gain() -> None:
    p = _rd("network_paired")
    p = p[p.metric == "utility"]
    regs = list(dict.fromkeys(p.regime))
    pairs = [("coordinated_no_inquiry", "desk_greedy", BLUE, "Coordinated vs human-desk heuristic"), ("coordinated_inquiry", "coordinated_no_inquiry", VIOLET, "One shared question, fixed assumptions (on top of coordination)"),
             ("coordinated_inquiry_adaptive", "coordinated_no_inquiry", AQUA, "One shared question, learned responsiveness (on top of coordination)")]
    fig, ax = plt.subplots(figsize=(9, 5.2))
    h = 0.25
    for j, (a, b, col, lab) in enumerate(pairs):
        d = p[(p.a == a) & (p.b == b)].set_index("regime").reindex(regs)
        y = np.arange(len(regs)) + (j - 1) * h
        ax.errorbar(d.mean_diff, y, xerr=[d.mean_diff - d.ci_lo, d.ci_hi - d.mean_diff], fmt="o", color=col, ms=5.5, elinewidth=1.6, mec="#fcfcfb", label=lab)
    ax.axvline(0, color=INK2, lw=0.8)
    ax.set_yticks(np.arange(len(regs)), [pretty(r) for r in regs])
    ax.invert_yaxis()
    ax.grid(axis="x")
    ax.set_xlabel("Paired gain in realised utility per incident (SAR-equivalents; right = better), 95% CI")
    ax.set_title(f"Gain from coordination and from the one shared question, by regime (SYNTHETIC, n={int(p.n.iloc[0])}/regime)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=1, fontsize=8.5)
    _save(fig, "fig_network_gain")


def chart_safety() -> None:
    dev = pd.read_csv(R / "safety_dev_sweep.csv")
    ev = _rd("safety_policy_eval")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5), gridspec_kw={"wspace": 0.7})
    a1.scatter(dev.auto_rate, dev.harmful_per_episode * 100, s=40, color=BLUE, zorder=3)
    for _, r in dev.iterrows():
        a1.annotate(r.policy.replace("A_baseline(min.62)", "baseline (min 0.62)"), (r.auto_rate, r.harmful_per_episode * 100), textcoords="offset points", xytext=(-6, 6) if r.auto_rate > 0.19 else (6, 4), ha="right" if r.auto_rate > 0.19 else "left", fontsize=7.5, color=INK2)
    a1.set_xlabel("Share of cases handled automatically")
    a1.set_ylabel("Harmful automatic actions per 100 cases")
    a1.set_title("Policy sweep (development seeds, SYNTHETIC)")
    a1.grid()
    pe = ev[ev.env.str.startswith("process/")]
    old = pe[pe.policy.str.startswith("old")].set_index("env")
    new = pe[pe.policy.str.startswith("new")].set_index("env")
    envs = list(old.index)
    y = np.arange(len(envs))
    a2.barh(y - 0.19, old.harmful_per_episode * 100, 0.36, color=GRAY, label="before: no out-of-pattern gate")
    a2.barh(y + 0.19, new.loc[envs].harmful_per_episode * 100, 0.36, color=AQUA, label="after: max P(unknown) 3%")
    a2.set_yticks(y, [e.replace("process/", "").replace("_", " ") for e in envs], fontsize=8)
    a2.invert_yaxis()
    a2.set_xlabel("Harmful automatic actions per 100 cases (held-out seeds)")
    a2.set_title("Held-out re-evaluation, every regime")
    a2.legend(loc="upper center", bbox_to_anchor=(0.4, -0.14), ncol=1, fontsize=8.5)
    a2.grid(axis="x")
    _save(fig, "fig_safety")


def chart_bridge() -> None:
    d = json.loads((PATHS.docs / "experiments" / "model_bridge.json").read_text())
    la = d["lade_replay"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.4))
    rel = pd.DataFrame(la["calibration_on_replay"]["reliability_deciles"])
    ax = axes[0]
    mx = max(rel.pred.max(), rel.obs.max()) * 1.1
    ax.plot([0, mx], [0, mx], color=GRAY, lw=1, ls="--")
    ax.scatter(rel.pred, rel.obs, color=BLUE, s=34, zorder=3)
    ax.set_xlabel("Predicted P(slow task)")
    ax.set_ylabel("Observed rate")
    ax.set_title(f"Calibration on real replay (n={la['trained_model_via_bridge']['n']})")
    ax.grid()
    ax = axes[1]
    ci = la["trained_model_via_bridge"].get("roc_auc_95ci")
    vals = [("Trained model\n(via the bridge)", la["trained_model_via_bridge"]["roc_auc"], BLUE), ("Hand-written heuristic\n(same cases)", la["heuristic_same_cases"]["roc_auc"], GRAY)]
    ax.bar([v[0] for v in vals], [v[1] for v in vals], color=[v[2] for v in vals], width=0.5)
    if ci:
        ax.errorbar([0], [vals[0][1]], yerr=[[vals[0][1] - ci[0]], [ci[1] - vals[0][1]]], fmt="none", ecolor=INK, elinewidth=1.4, capsize=4)
    for i, v in enumerate(vals):
        ax.text(i, v[1] + 0.04 if i == 0 else v[1] + 0.012, f"{v[1]:.3f}", ha="center", fontsize=9)
    ax.axhline(0.5, color=INK2, lw=0.8, ls=":")
    ax.set_ylim(0.4, 1.0)
    ax.set_ylabel("ROC-AUC on real held-out tasks")
    ax.set_title("Model vs heuristic (real data, LaDe)")
    ax = axes[2]
    op = la["operating_points"]
    names = ["elevated_band", "high_band", "top5%", "top10%", "top20%"]
    pr = [op[n]["precision"] for n in names]
    rc = [op[n]["recall"] for n in names]
    x = np.arange(len(names))
    ax.bar(x - 0.18, pr, 0.34, color=ORANGE, label="precision")
    ax.bar(x + 0.18, rc, 0.34, color=AQUA, label="recall")
    ax.axhline(la["trained_model_via_bridge"]["prevalence"], color=INK2, lw=0.8, ls=":")
    ax.text(len(names) - 0.5, la["trained_model_via_bridge"]["prevalence"] + 0.01, "base rate", ha="right", fontsize=8, color=INK2)
    ax.set_xticks(x, [n.replace("_", "\n") for n in names], fontsize=8)
    ax.set_title("Operating points")
    ax.legend(fontsize=8.5)
    fig.suptitle("Real-data model bridge: trained LaDe model served through the agent interface (REAL observed data, not SPL)", x=0.07, ha="left", fontsize=11, fontweight="bold")
    _save(fig, "fig_model_bridge")


def chart_llm() -> None:
    r = json.loads((PATHS.docs / "experiments" / "reply_interpretation.json").read_text())
    pl = json.loads((PATHS.docs / "experiments" / "llm_planner.json").read_text())
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4))
    names = ["rules only"] + [f"Qwen3.5-{m.split(':')[1].upper()}" for m in r["models"]]
    cov = [r["rules_only"]["coverage_of_answerable"]] + [v["llm_only"]["coverage_of_answerable"] for v in r["models"].values()]
    fa = [r["rules_only"]["false_accept_rate"]] + [v["llm_only"]["false_accept_rate"] for v in r["models"].values()]
    x = np.arange(len(names))
    a1.bar(x - 0.18, cov, 0.34, color=AQUA, label="answerable replies read correctly")
    a1.bar(x + 0.18, fa, 0.34, color=RED, label="wrong answers accepted (of accepted)")
    for i, (c, f) in enumerate(zip(cov, fa, strict=True)):
        a1.text(i - 0.18, c + 0.015, f"{c:.0%}", ha="center", fontsize=8.5)
        a1.text(i + 0.18, f + 0.015, f"{f:.1%}", ha="center", fontsize=8.5)
    a1.set_xticks(x, names)
    a1.set_ylim(0, 1.1)
    a1.set_title(f"Arabic/English reply interpretation (hand-written set, n={r['set']['n']})")
    a1.legend(fontsize=8.5, loc="upper left")
    c = pl["contenders"]
    keys = [k for k in c if k != "evoi"]
    diffs = [c[k]["paired_regret_diff_vs_evoi"] for k in keys]
    agree = [c[k]["agreement_with_evoi"] for k in keys]
    labs = [k.replace("qwen3.5:", "Qwen3.5-").replace("|", "\n") for k in keys]
    a2.bar(labs, diffs, color=[ORANGE if d > 0 else AQUA for d in diffs], width=0.5)
    for i, (d, a_) in enumerate(zip(diffs, agree, strict=True)):
        a2.text(i, d + (0.2 if d >= 0 else -0.6), f"{d:+.1f}\nagree {a_:.0%}", ha="center", fontsize=8.5)
    a2.axhline(0, color=INK2, lw=0.8)
    a2.set_ylabel("Regret vs decision-theoretic planner (>0 = worse)")
    a2.set_title(f"LLM planner vs EVOI (SYNTHETIC, n={pl['n_episodes']} paired episodes)")
    _save(fig, "fig_llm")


def main() -> None:
    for fn in (chart_single_gain, chart_ablation, chart_sensitivity, chart_network, chart_network_gain, chart_safety, chart_bridge, chart_llm):
        try:
            fn()
        except FileNotFoundError as e:
            print("skipped", fn.__name__, e.filename)


if __name__ == "__main__":
    main()
