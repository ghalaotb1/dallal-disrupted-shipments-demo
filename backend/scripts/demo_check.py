#!/usr/bin/env python3
"""End-to-end check of the three local demonstrations against a running backend (default http://localhost:8000), with a printed backend trace for each.

  A. real-data replay: a real held-out LaDe task -> live agent -> trained-model inference (or an explicit abstention) -> outcome revealed afterwards
  B. uncertain shipment: databases exhausted -> value-based inquiry -> sandbox reply -> belief update -> decision (and what a different reply would have changed)
  C. shared incident: one dispatcher question -> coordinated plan for several shipments changes -> supervisor approval -> simulated execution + ledger
Nothing is sent to a phone (sandbox). Exit code 1 if any check fails.   python backend/scripts/demo_check.py [--backend URL] [--key K] [--write docs/demos/DEMO_TRACES.md]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_deployment import call  # noqa: E402

LOG: list[str] = []
FAILS = 0


def out(s: str = "") -> None:
    print(s, flush=True)
    LOG.append(s)


def check(name: str, ok: bool, detail: str = "") -> None:
    global FAILS
    FAILS += not ok
    out(f"- [{'x' if ok else ' '}] {name}" + (f" - {detail}" if detail else ""))


def top(step: dict) -> str:
    b = (step.get("belief_after") or {}).get("top") or []
    return ", ".join(f"{c} {p:.0%}" for c, p in b[:2]) if b else "-"


def demo_a(B: str, K: str | None) -> None:
    out("## Demo A - real-data replay with trained-model inference\n")
    scored = abstained = None
    for seed in range(0, 40):
        s, r = call(B, "POST", f"/v1/replay/lade?seed={seed}", K, None, 120)
        if s != 200:
            check("replay endpoint available (needs the LaDe tables locally)", False, f"status {s}: {r}")
            return
        if r["risk"]["source"] == "model" and scored is None:
            scored = (seed, r)
        if r["risk"]["source"] != "model" and abstained is None:
            abstained = (seed, r)
        if scored and abstained:
            break
    for label, case in (("model scored", scored), ("model abstained", abstained)):
        if case is None:
            out(f"(no {label} case found in 40 seeds)")
            continue
        seed, r = case
        out(f"### {label}: replay seed {seed} ({r['source']}; accepted {r['accepted_at']}, agent sees it at {r['as_of']})\n")
        for st in r["steps"]:
            out(f"  - `{st['tool']}` - {st['summary']} -> {st['outcome']} | belief: {top(st)}")
            if st["tool"] == "predict_risk":
                for f in st["facts"]:
                    out(f"      * {f}")
        k = r["risk"]
        if k["source"] == "model":
            out(f"  - MODEL: P(slow) = {k['probability']:.2%}, band {k['band']}, base rate {k['meta']['base_rate_source']:.1%}")
        else:
            out(f"  - NO MODEL SCORE: {(k.get('meta') or {}).get('why_heuristic')}")
        out(f"  - decision: {r['decision']['headline']}")
        s, o = call(B, "GET", f"/v1/replay/lade/{r['case_id']}/outcome", K)
        out(f"  - real outcome (revealed afterwards): {o['duration_min']:.0f} min, slow={o['slow']} (threshold {o['slow_threshold_min']:.0f} min)\n")
        check(f"{label}: result is explicitly labelled", k["source"] in ("model", "heuristic"), f"source={k['source']}")
    check("a trained model really scored at least one real held-out task", scored is not None)
    check("when a task could not be scored the interface says so (abstention reason present)", abstained is None or bool((abstained[1]["risk"].get("meta") or {}).get("why_heuristic")))


def demo_b(B: str, K: str | None) -> None:
    out("\n## Demo B - uncertain shipment: value-based inquiry, sandbox reply, belief update\n")
    finals = {}
    for ans in ("at_address_no_answer", "cannot_find_address"):
        s, run = call(B, "POST", "/v1/scenarios/developing_disruption/run?seed=11", K, {})
        r = run["run"]
        inq = r["inquiries_live"][0]
        if ans == "at_address_no_answer":
            out(f"run {r['run_id']}: status {r['status']}; databases first, then a question:")
            for st in r["steps"]:
                out(f"  - `{st['tool']}` - {st['why'][:110]} -> {st['outcome']} | belief: {top(st)}")
            c = next(x for x in r["steps"] if x["tool"].startswith("ask:"))
            row = (c.get("candidates") or [{}])[0]
            out(f"  - asked the {inq['target']} (net value of information {inq['net_voi']:+.2f} SAR-eq, reply chance {inq['p_response']:.0%}); sandbox message `{inq['messages'][0]['status']}`, real_delivery={inq['real_delivery']}")
            check("agent paused to ask a person after exhausting databases", r["status"] == "awaiting_response" and inq["target"] == "courier")
            check("the message is sandbox-only", inq["delivery_mode"] == "sandbox" and inq["real_delivery"] is False)
            _ = row
        s, _rep = call(B, "POST", "/v1/sandbox/reply", K, {"inquiry_id": inq["inquiry_id"], "kind": "button", "answer_id": ans})
        s, fin = call(B, "GET", f"/v1/runs/{r['run_id']}", K)
        fr = fin["run"]
        d = fr["decision"]
        last = next(x for x in fr["steps"] if x["tool"].startswith("ask:"))
        out(f"  reply `{ans}` -> belief {top(last)}; decision {d['type']}" + (f" / {d.get('action')}" if d.get("action") else "") + f" - {d['headline']}")
        finals[ans] = (r["run_id"], d)
    a, b = finals["at_address_no_answer"][1], finals["cannot_find_address"][1]
    check("the reply changed the belief and the decision differs by answer", (a["type"], a.get("action")) != (b["type"], b.get("action")), f"{a['type']}/{a.get('action')} vs {b['type']}/{b.get('action')}")
    rid = finals["at_address_no_answer"][0]
    s, _ = call(B, "POST", f"/v1/runs/{rid}/execute", K, {"approved_by": "demo", "role": "none"})
    check("sensitive action needs human approval (403 without it)", s == 403)
    s, ex = call(B, "POST", f"/v1/runs/{rid}/execute", K, {"approved_by": "demo-analyst", "role": "analyst"})
    check("analyst approves -> action recorded as SIMULATED, outcome pending (not claimed successful)", s == 200 and ex["status"] == "executed_simulated" and ex["outcome"] == "pending", str(ex)[:100])


def demo_c(B: str, K: str | None) -> None:
    out("\n## Demo C - shared incident: one inquiry, one coordinated plan\n")
    snap = {"incidentId": "INC-DEMO", "scope": "corridor", "scopeId": "DK-04", "now": 0, "belief": {"pLong": 0.3}, "dispatcherContactable": True,
            "parcels": [{"id": f"P{i}", "van": f"V{i % 3}", "value": 400 + 120 * i, "slackMin": 75 + 6 * i, "remainingMin": 35, "service": "Express", "exposed": i > 4, "pickupOk": True, "reachable": True} for i in range(10)],
            "resources": {"spares": [{"id": "S1", "etaMin": 22, "capacity": 3}, {"id": "S2", "etaMin": 30, "capacity": 2}], "pickups": [{"id": "K1", "travelMin": 25, "capacity": 2, "online": True}],
                          "alt": {"available": False, "extraMin": 55}}}  # no alternative corridor: the regime in which the dispatcher's answer matters most
    s, plan = call(B, "POST", "/v1/frontend/incidents/plan", K, {"snapshot": snap, "lang": "ar"})
    ev = plan["evidence"]
    out(f"plan {plan['plan_id']}: P(long blockage) prior {plan['p_long_prior']:.0%}; ask the dispatcher ONCE: {ev['asked']} (net VOI {ev['voi']['net']:+.2f}, reply chance {ev['p_response']:.0%}); committed now: {sorted(plan['solution']['committed_now'])}")
    before = {k: v["option"] for k, v in plan["solution"]["per_parcel"].items()}
    check("one shared question replaces per-shipment questions", ev["asked"] and len(plan["inquiries"]) == 1 and plan["comparison"]["messages_independent_equivalent"] > plan["comparison"]["messages_coordinated"])
    s, _ = call(B, "POST", "/v1/sandbox/reply", K, {"inquiry_id": plan["inquiries"][0]["inquiry_id"], "kind": "button", "answer_id": "blocked_long"})
    s, plan2 = call(B, "GET", f"/v1/plans/{plan['plan_id']}", K)
    after = {k: v["option"] for k, v in plan2["solution"]["per_parcel"].items()}
    changed = [k for k in after if after[k] != before[k]]
    out(f"  reply `blocked_long` -> P(long) {plan2['p_long']:.0%}; plan status {plan2['status']}; decisions changed for {len(changed)}/{len(after)} shipments: " + ", ".join(f"{k}: {before[k]}->{after[k]}" for k in changed[:6]))
    cmp = plan2["comparison"]
    out(f"  coordinated utility {cmp['coordinated_utility']:.0f} vs independent {cmp['independent_utility']:.0f}; messages {cmp['messages_coordinated']} vs {cmp['messages_independent_equivalent']}; independent capacity over-requests {cmp['independent_capacity_requests_over_cap']}")
    check("the single answer changed the plan for several shipments", len(changed) >= 2, f"{len(changed)} changed")
    s, _ = call(B, "POST", f"/v1/plans/{plan['plan_id']}/decision", K, {"decision": "approve", "by": "demo", "role": "analyst"})
    check("analyst cannot approve a network plan (supervisor only)", s == 403)
    s, done = call(B, "POST", f"/v1/plans/{plan['plan_id']}/decision", K, {"decision": "approve", "by": "demo-supervisor", "role": "supervisor"})
    check("supervisor approval -> executed as SIMULATED with ledger entries", s == 200 and done["status"] == "executed_simulated" and len(done.get("executed", [])) == 10)
    s, led = call(B, "GET", "/v1/ledger?limit=60", K)
    check("actions and pending outcomes are in the ledger (no fabricated success)", any(r.get("table") == "outcome" and r.get("kind") == "pending" for r in led))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="http://localhost:8000")
    ap.add_argument("--key", default="")
    ap.add_argument("--write", default="")
    a = ap.parse_args()
    K = a.key or None
    s, m = call(a.backend, "GET", "/v1/meta", K)
    if s != 200:
        print("backend not reachable at", a.backend)
        return 1
    out("# Demo traces (generated by backend/scripts/demo_check.py against the local backend)\n")
    out(f"backend: env={m.get('env')} whatsapp={m['whatsapp']['mode']} real_delivery_possible={m['real_delivery_possible']} actions={m['execution']['mode']} llm={m['llm']['backend']} models={len(m['ml']['models'])}\n")
    check("WhatsApp is sandbox and actions are simulated", m["whatsapp"]["mode"] == "sandbox" and m["execution"]["mode"] == "simulated")
    demo_a(a.backend, K)
    demo_b(a.backend, K)
    demo_c(a.backend, K)
    out(f"\n{'ALL CHECKS PASSED' if not FAILS else str(FAILS) + ' CHECK(S) FAILED'}")
    if a.write:
        Path(a.write).parent.mkdir(parents=True, exist_ok=True)
        Path(a.write).write_text("\n".join(LOG) + "\n")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
