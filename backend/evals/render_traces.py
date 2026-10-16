"""Render evals/traces/*.json into docs/architecture/EVAL_TRACES.md (human-readable audit of the three headline cases)."""
from __future__ import annotations

import json

from dallal.config import PATHS

NAMES = {"A_low_risk_automation": "A — Low-risk case → safe automated recovery",
         "B_systemic_incident": "B — Shared root cause → incident-level reasoning",
         "C_conflicting_evidence": "C — Conflicting evidence → human escalation"}


def main() -> None:
    rep = json.loads((PATHS.traces / "eval_report.json").read_text())
    md = ["# Dallal agent — evaluation traces", "",
          "> **All data in these traces is SYNTHETIC** (`origin=synthetic`, scenario ids shown). They demonstrate that the agent's behaviour depends on the",
          "> evidence; they are **not** accuracy estimates. Probabilities come from expert-assumption observation models (`expert_assumption_v1`),",
          "> not from a fitted model. Regenerate: `python -I evals/run_cases.py && python -I evals/render_traces.py`.", ""]
    for key, title in NAMES.items():
        r = json.loads((PATHS.traces / f"{key}.json").read_text())
        d = r["decision"]
        md += [f"## {title}", "", f"* scenario `{r['scenario_id']}` · trigger `{r['trigger'].get('kind')}` · planner `{r['planner']}`",
               f"* **tool path:** `{' → '.join(r['tool_path'])}`",
               f"* **decision:** `{d['type']}`" + (f" / `{d.get('reason')}`" if d.get("reason") else "") + (f" · action `{d.get('action')}`" if d.get("action") else "")
               + f" · leading cause `{d['top_cause']}` ({d['posterior']:.0%}) · P(systemic) {d['p_systemic']:.0%}",
               f"* **headline:** {d['headline']}", f"* **rationale:** {d['rationale']}"]
        if d.get("question"):
            md.append(f"* **question for the human:** {d['question']}")
        md += ["", "| # | tool | why it was chosen | outcome | leading hypotheses after |", "|---|---|---|---|---|"]
        for s in r["steps"]:
            top = ", ".join(f"{c} {p:.0%}" for c, p in (s["belief_after"] or {}).get("top", [])[:2]) if s["belief_after"] else "—"
            why = s["why"].replace("|", "/")
            md.append(f"| {s['index']} | `{s['tool']}` | {why} | {s['outcome'] or s['status']} | {top} |")
        md += ["", "<details><summary>Facts returned by tools</summary>", ""]
        for s in r["steps"]:
            md.append(f"* `{s['tool']}` — {s['summary']}" + ("".join(f"\n  * {f}" for f in s["facts"])))
        md += ["", "</details>", ""]
    sw = rep["sweep"]
    md += ["## Functional sweep (synthetic, 11 scenarios × 20 seeds)", "",
           f"* runs: {sw['_overall']['runs']} · distinct tool paths: {sw['_overall']['distinct_tool_paths']} · "
           f"scenario-expectation pass rate: {sw['_overall']['pass_rate']:.0%} · safety-invariant violations: {sw['_overall']['safety_violations']}",
           "* **Read with care:** scenarios were authored alongside the agent and seeds vary geometry/counts, not structure. The pass rate shows the logic",
           "  behaves as designed; it says nothing about real-world accuracy. The invariants (no automation above value/attempt/confidence bounds, no skipped",
           "  policy gate, no repeated tool, escalation always carries a packet) are the stronger result.", "",
           "| scenario | pass | mean tool calls |", "|---|---|---|"]
    md += [f"| {k} | {v['pass_rate']:.0%} | {v['mean_tool_calls']} |" for k, v in sw.items() if k != "_overall"]
    md += ["", "## Metamorphic checks (change the evidence → behaviour must change)", "", "| perturbation | before | after | required change observed |", "|---|---|---|---|"]
    md += [f"| `{k}` | {v['base_decision']} / {v['base_cause']} | {v['perturbed_decision']} / {v['perturbed_cause']} | {v['behaviour_changed_as_required']} |" for k, v in rep["metamorphic"].items()]
    out = PATHS.docs / "architecture" / "EVAL_TRACES.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(md) + "\n")
    print("wrote", out)


if __name__ == "__main__":
    main()
