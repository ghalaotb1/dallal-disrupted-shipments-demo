"""Headline end-to-end trace (SYNTHETIC scenario, SANDBOX WhatsApp): developing disruption -> uncertainty -> value-based inquiry -> answer -> update -> recovery.

Runs the same case twice - without inquiries and with - through the real service stack (durable store, sandbox channel, interpreter, policy) and renders a
side-by-side audit. Nothing is sent to a phone. Run: python -I -m dallal.eval.headline -> docs/experiments/headline_trace.md (+ .json)
"""

from __future__ import annotations

import json

from dallal.agent.v2.runtime import AgentRuntimeV2
from dallal.config import PATHS
from dallal.data.augment.scenarios import SCENARIOS
from dallal.service import OpsService
from dallal.store import Store


def _steps_table(steps: list[dict]) -> list[str]:
    rows = ["| # | step | why | outcome | belief after (top 2) |", "|---|---|---|---|---|"]
    for s in steps:
        b = s.get("belief_after") or {}
        top = ", ".join(f"{c} {p:.0%}" for c, p in b.get("top", [])[:2]) if b else "—"
        rows.append(f"| {s['index']} | `{s['tool']}` | {s['why'].replace('|', '/')[:170]} | {s['outcome'] or s['status']} | {top} |")
    return rows


def main() -> None:
    bundle = SCENARIOS["developing_disruption"](11)
    base = AgentRuntimeV2(mode="no_inquiry").start(bundle)
    svc = OpsService(Store(":memory:"), time_scale=1.0)
    first = svc.investigate(bundle, "ar")
    run_id = first["run_id"] if "run_id" in first else first["run"]["run_id"]
    paused = svc.view_run(run_id)
    inq = paused["inquiries_live"][0]
    after = svc.sandbox_reply(inq["inquiry_id"], "button", answer_id="at_address_no_answer")
    final = svc.view_run(run_id)

    md = ["# Headline trace — developing disruption (synthetic scenario, sandbox WhatsApp)", "",
          "> **SYNTHETIC case, SANDBOX channel.** No message left this machine (`real_delivery: false`). Utilities are SAR-equivalents from `utility.yaml` (assumptions).", "",
          f"Scenario `{bundle.scenario_id}`: a high-value COD parcel (1,850 SAR); the courier's van has been parked ~60 m from the address for 28 min. No scan says why.", "",
          "## A. Same case without inquiries (`v2_no_inquiry`)", "", f"* decision: **{base.run.decision['type']}** — {base.run.decision['headline']}",
          f"* leading cause: `{base.run.decision['top_cause']}` ({base.run.decision['posterior']:.0%})", ""]
    md += _steps_table(base.run.steps)
    md += ["", "## B. With value-based inquiry (`v2_value`)", "", "### B1. Investigation until it needs a person", ""]
    md += _steps_table(paused["steps"])
    md += ["", f"**Paused:** {paused['decision']['rationale']}", "", "### B2. The WhatsApp exchange (sandbox)", ""]
    for m in final["inquiries_live"][0]["messages"]:
        who = "Dallal → courier" if m["direction"] == "out" else "courier → Dallal"
        md.append(f"* **{who}** `[{m['mode']}/{m['status']}]` {m['text'] or '(interactive reply)'}" + (f" — read as `{m['interpretation']['answer_id']}` by `{m['interpretation']['method']}`" if m.get("interpretation") else ""))
    md += ["", "### B3. After the answer", ""]
    md += _steps_table(final["steps"])
    d = final["decision"]
    md += ["", f"* decision: **{d['type']}**" + (f" / action `{d.get('action')}`" if d.get("action") else "") + f" — {d['headline']}", f"* rationale: {d['rationale']}",
           f"* leading cause `{d['top_cause']}` ({d['posterior']:.0%}); virtual elapsed {final.get('virtual_minutes')} min", ""]
    ask = next((s for s in final["steps"] if s["tool"].startswith("ask:")), None)
    if ask and ask.get("candidates"):
        md += ["### Value-of-information table at the moment of asking", "", "| source | net VOI | gross | cost | P(changes best action) | reply chance | latency (min) |", "|---|---|---|---|---|---|---|"]
        for c in ask["candidates"]:
            md.append(f"| `{c['source']}` | {c['net_voi']:+.2f} | {c['gross_voi']:.2f} | {c['cost']:.2f} | {c['p_decision_change']:.0%} | {c['p_response']:.0%} | {c['latency_min']:.0f} |")
        md.append("")
    md += ["### B4. Why the answer matters: the same paused case under every possible reply", "", "| courier's answer | belief after | decision | recommended action |", "|---|---|---|---|"]
    alt = {}
    for ans in ("at_address_no_answer", "cannot_find_address", "road_blocked", "on_route_normal", "never_reached", "parcel_missing"):
        sv = OpsService(Store(":memory:"), time_scale=1.0)
        r0 = sv.investigate(SCENARIOS["developing_disruption"](11), "ar")
        rid = r0["run_id"] if "run_id" in r0 else r0["run"]["run_id"]
        iid = sv.view_run(rid)["inquiries_live"][0]["inquiry_id"]
        sv.sandbox_reply(iid, "button", answer_id=ans)
        v = sv.view_run(rid)
        dd = v["decision"]
        alt[ans] = {"decision": dd["type"], "action": dd.get("action"), "cause": dd["top_cause"], "posterior": dd["posterior"]}
        md.append(f"| `{ans}` | {dd['top_cause']} {dd['posterior']:.0%} | {dd['type']}{' / ' + dd['reason'] if dd.get('reason') else ''} | {dd.get('action') or '—'} |")
    md.append("")
    out = PATHS.docs / "experiments"
    out.mkdir(parents=True, exist_ok=True)
    (out / "headline_trace.md").write_text("\n".join(md) + "\n")
    (out / "headline_trace.json").write_text(json.dumps({"no_inquiry": base.run.decision, "with_inquiry": final["decision"], "after_reply": after.get("status"), "by_answer": alt}, indent=2, default=str) + "\n")
    print("\n".join(md[:60]))


if __name__ == "__main__":
    main()
