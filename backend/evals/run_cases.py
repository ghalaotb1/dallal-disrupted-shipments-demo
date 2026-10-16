"""Agent evaluation. Run:  python -I evals/run_cases.py

Part 1  three headline end-to-end cases (A low-risk automation, B systemic incident, C conflicting evidence -> human)
Part 2  functional sweep: every scenario x 20 seeds, checked against the evaluation-only `expected` block
Part 3  metamorphic perturbations: change the evidence, the tool path / decision MUST change accordingly

IMPORTANT: all data here is SYNTHETIC (tagged). Pass rates measure whether the agent's logic behaves as designed on situations
real data cannot show. They are NOT estimates of real-world accuracy.
"""
from __future__ import annotations

import json
import statistics
from collections import Counter

from dallal.agent.runtime import AgentRuntime
from dallal.config import PATHS
from dallal.data.augment.scenarios import SCENARIOS
from dallal.tools.bundle import Bundle

HEADLINE = {"A_low_risk_automation": "address_risk", "B_systemic_incident": "route_blockage", "C_conflicting_evidence": "custody_conflict"}
SEEDS = range(20)


def check(bundle: Bundle, run) -> list[str]:
    e, d, fails = bundle.expected, run.decision, []
    if "decision" in e and d["type"] != e["decision"]:
        fails.append(f"decision {d['type']} != {e['decision']}")
    if "decision_in" in e and d["type"] not in e["decision_in"]:
        fails.append(f"decision {d['type']} not in {e['decision_in']}")
    if "cause" in e and d["top_cause"] != e["cause"]:
        fails.append(f"cause {d['top_cause']} != {e['cause']}")
    if "cause_in" in e and d["top_cause"] not in e["cause_in"]:
        fails.append(f"cause {d['top_cause']} not in {e['cause_in']}")
    if "reason_in" in e and d.get("reason") not in e["reason_in"]:
        fails.append(f"reason {d.get('reason')} not in {e['reason_in']}")
    if "reason" in e and d.get("reason") != e["reason"]:
        fails.append(f"reason {d.get('reason')} != {e['reason']}")
    if "action" in e and d.get("action") != e["action"]:
        fails.append(f"action {d.get('action')} != {e['action']}")
    if "action_in" in e and d.get("action") not in e["action_in"]:
        fails.append(f"action {d.get('action')} not in {e['action_in']}")
    for t in e.get("must_call", []):
        if t not in run.tool_path:
            fails.append(f"missing required tool {t}")
    for t in e.get("must_not_call", []):
        if t in run.tool_path:
            fails.append(f"called forbidden tool {t}")
    return fails


def safety_violations(run, state) -> list[str]:
    """Invariants that must hold on EVERY run regardless of scenario."""
    v, f, d = [], state.facts or {}, run.decision
    if d["type"] == "auto_eligible":
        if (f.get("failed_attempts") or 0) > 2:
            v.append("auto action after >2 failed attempts")
        if (f.get("value") or 0) > 1500:
            v.append("auto action above value bound")
        if (state.diagnosis or {}).get("agreement") == "conflicts":
            v.append("auto action despite evidence conflict")
        if d["posterior"] < 0.8:
            v.append("auto action below confidence bound")
    if d["type"] == "escalate" and run.escalation is None:
        v.append("escalation decided but no escalation packet created")
    if "rank_recovery_actions" in run.tool_path and "retrieve_policy_constraints" not in run.tool_path and run.actions:
        v.append("actions ranked but policy gate skipped")
    if run.tool_path.count("get_shipment") != 1 or len(run.tool_path) != len(set(run.tool_path)):
        v.append("repeated tool call")
    return v


def perturb(bundle: Bundle, how: str) -> Bundle:
    t = {k: v.copy() for k, v in bundle.tables.items()}
    sid = bundle.subject_id
    if how == "address_ok":
        t["address_context"].loc[t["address_context"].shipment_id == sid, ["confidence", "past_failures_at_address", "first_delivery_to_address"]] = [0.95, 0, False]
    elif how == "drop_delivered_scan":
        ev = t["event"]
        t["event"] = ev[~((ev.shipment_id == sid) & (ev.event_type == "delivered"))]
    else:
        raise ValueError(how)
    b = Bundle(bundle.scenario_id + f"+{how}", bundle.as_of, sid, bundle.trigger, t, {})
    b.validate()
    return b


def main() -> None:
    rt = AgentRuntime()
    out_dir = PATHS.traces
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"headline": {}, "sweep": {}, "metamorphic": {}}

    # Part 1 -----------------------------------------------------------------
    for label, scn in HEADLINE.items():
        b = SCENARIOS[scn](7)
        run, st = rt.investigate(b, run_id=f"case-{label}")
        run.write(out_dir / f"{label}.json")
        report["headline"][label] = {"scenario": scn, "tool_path": run.tool_path, "decision": run.decision["type"],
                                     "reason": run.decision.get("reason"), "action": run.decision.get("action"), "top_cause": run.decision["top_cause"],
                                     "posterior": run.decision["posterior"], "p_systemic": run.decision["p_systemic"], "failures": check(b, run)}

    # Part 2 -----------------------------------------------------------------
    paths_all: Counter = Counter()
    for name, fn in SCENARIOS.items():
        results, lens, viol = [], [], []
        for seed in SEEDS:
            b = fn(seed)
            run, st = rt.investigate(b)
            f = check(b, run)
            sv = safety_violations(run, st)
            results.append(not f)
            lens.append(len(run.tool_path))
            viol += sv
            paths_all[tuple(run.tool_path)] += 1
            if f and seed < 3:
                report["sweep"].setdefault(name, {}).setdefault("example_failures", []).append({"seed": seed, "fails": f})
        report["sweep"].setdefault(name, {}).update({"pass_rate": sum(results) / len(results), "mean_tool_calls": round(statistics.mean(lens), 2),
                                                     "safety_violations": viol})
    report["sweep"]["_overall"] = {"runs": len(SCENARIOS) * len(SEEDS), "distinct_tool_paths": len(paths_all),
                                   "pass_rate": round(sum(v["pass_rate"] for k, v in report["sweep"].items() if k != "_overall") / len(SCENARIOS), 4),
                                   "safety_violations": sum(len(v["safety_violations"]) for k, v in report["sweep"].items() if k != "_overall")}

    # Part 3 -----------------------------------------------------------------
    for how, scn, expect in (("address_ok", "address_risk", lambda r: r.decision.get("top_cause") != "address_issue" and r.decision["type"] != "auto_eligible"),
                             ("drop_delivered_scan", "custody_conflict", lambda r: r.decision.get("top_cause") != "custody_anomaly"),
                             ):
        base = SCENARIOS[scn](7)
        r0, _ = rt.investigate(base)
        r1, _ = rt.investigate(perturb(base, how))
        report["metamorphic"][how] = {"base_decision": r0.decision["type"], "perturbed_decision": r1.decision["type"], "base_cause": r0.decision["top_cause"],
                                      "perturbed_cause": r1.decision["top_cause"], "base_path": r0.tool_path, "perturbed_path": r1.tool_path,
                                      "behaviour_changed_as_required": bool(expect(r1)), "path_changed": r0.tool_path != r1.tool_path}
    (out_dir / "eval_report.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(json.dumps({"headline": {k: {kk: vv for kk, vv in v.items() if kk != "tool_path"} for k, v in report["headline"].items()},
                      "sweep_overall": report["sweep"]["_overall"], "metamorphic": {k: {kk: vv for kk, vv in v.items() if "path" not in kk} for k, v in report["metamorphic"].items()}}, indent=2))
    for k, v in report["sweep"].items():
        if k != "_overall":
            print(f"{k:24} pass={v['pass_rate']:.0%} calls={v['mean_tool_calls']} violations={len(v['safety_violations'])}", v.get("example_failures", ""))


if __name__ == "__main__":
    main()
