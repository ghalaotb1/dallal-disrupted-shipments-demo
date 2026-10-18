"""Operator assistant: a local Qwen model as the CONVERSATIONAL INTERFACE over live operational facts.

What it is and is not
  * It explains and answers (Arabic or English). It never decides, approves, executes or changes anything: the deterministic agent, the policy gates and the
    people who approve are untouched.
  * Every answer is grounded: the model only sees a CONTEXT built here from (a) the operation snapshot the UI sends (drivers, parcels, cases, KPIs, activity) and
    (b) this backend's own records (agent runs, their questions and replies, coordinated plans, the ledger). The prompt forbids anything outside it, and the
    answer is checked afterwards: an unknown parcel / run / plan identifier invalidates it and the caller falls back to the deterministic answer.
  * Everything is local (Ollama). No data leaves the machine.
"""

from __future__ import annotations

import os
import re
import time
from typing import Any, Iterator

from dallal import llm

ID_RE = re.compile(r"DL-\d{5}", re.I)
RUN_RE = re.compile(r"\brun-[0-9a-f]{8}\b", re.I)
PLAN_RE = re.compile(r"\bplan-[0-9a-f]{8}\b", re.I)

CAUSE = {"address_issue": "address problem", "recipient_unavailable": "customer not available", "attempt_not_completed": "attempt not completed", "route_disruption": "road disruption",
         "facility_backlog": "facility backlog", "pickup_point_unavailable": "pickup point closed", "custody_anomaly": "custody mismatch", "none": "no real problem", "unknown": "unknown pattern"}

SYSTEM = """You are Dallal Assistant, the conversational interface of a last-mile delivery control room (Eastern Province, Saudi Arabia).

Rules:
1. Answer ONLY from the CONTEXT. It is the live state of the operation and the results of the Dallal decision agent. If the answer is not in CONTEXT, say you do not have it. Never guess or invent parcels, drivers, numbers, causes, actions, approvals or outcomes.
2. Reply in the language of the user's last message (Arabic or English). Keep parcel ids (DL-12345), vehicle codes and driver names exactly as in CONTEXT; you may add the Arabic driver name when replying in Arabic.
3. Be brief: 1 to 4 short sentences, or up to 5 short bullets. No preamble, no repetition of the question.
4. You only explain. You cannot execute, approve, reject or change anything. Decisions come from Dallal's deterministic engine and from people (group plans need the manager, who approves in the Manager view). If asked to act, say where it is done.
5. Quote percentages and amounts exactly as given. Outcomes are simulated and pending unless CONTEXT says otherwise; never say a parcel was delivered or recovered unless CONTEXT says so.
6. Say clearly when something is still in progress (investigating, waiting for a reply, waiting for the manager).
7. Glossary: 'waiting for the manager' = Dallal prepared a plan and policy requires the manager to approve it. 'recovery in progress' = an action was sent (simulated), outcome not known yet. 'outcome observed in the simulated world' = the simulated world reported it; there is no real-world delivery data. WhatsApp is a sandbox: nothing is sent to a real phone. A driver's reply is the driver's, not the customer's.
8. When asked what happened or what Dallal did, retell the numbered steps of the RUN in order: what happened, what Dallal checked, whom it asked and what they replied, how its belief changed, and its decision. Name who did each thing (Dallal, the driver, the dispatcher, the manager) and do not mix up parcels.

Example (the names and numbers here are made up; use only CONTEXT for real answers):
Q: Why did DL-XXXXX fail and what did Dallal do?
A: DL-XXXXX failed at the door because the customer did not answer. Dallal asked the driver Sami; Sami replied that nobody answered, and Dallal's belief that the customer was unavailable rose from 60% to 90%. It then resolved the case alone by messaging the customer on WhatsApp (sandbox); no manager was needed.
Q: لماذا فشل الطرد DL-XXXXX وماذا فعل دلّال؟
A: فشل الطرد DL-XXXXX عند الباب لأن العميل لم يرد. سأل دلّال السائق سامي فأجاب أنه لا أحد يفتح، فارتفعت ثقته بأن العميل غير متاح من 60% إلى 90%. ثم عالج الحالة بنفسه بمراسلة العميل عبر واتساب (بيئة تجريبية) دون حاجة إلى المدير."""


def _norm(s: str) -> str:
    return re.sub(r"[ً-ٰٟ]", "", s or "").lower()  # strip Arabic diacritics


def _pct(x: Any) -> str:
    try:
        return f"{round(float(x) * 100)}%"
    except (TypeError, ValueError):
        return "?"


def mentions(question: str, snap: dict[str, Any]) -> dict[str, list[str]]:
    """Which parcels and drivers the question is about (ids, names in English or Arabic, vehicle codes)."""
    q = _norm(question)
    parcels = [m.upper() for m in ID_RE.findall(question)]
    drivers: list[str] = []
    for d in snap.get("drivers", []):
        names = [d.get("name", ""), d.get("name_ar", ""), d.get("vehicle", "")]
        if any(n and _norm(n) in q for n in names):
            drivers.append(d["id"])
    return {"parcels": list(dict.fromkeys(parcels)), "drivers": drivers}


HEALTH_WORDS = {"on_track": "on track", "delivered": "delivered", "at_risk": "at risk", "disrupted": "delivery failed", "review": "waiting for the manager", "recovering": "recovery in progress",
                "recovered": "recovered (outcome observed in the simulated world)", "prevented": "failure prevented (outcome observed in the simulated world)"}


def _option_words(o: str) -> str:
    k, _, r = o.partition(":")
    return {"wait": "wait in the managed lane", "spare": f"spare courier {r}", "pickup": f"pickup point {r}", "defer": "reschedule with notice", "reroute": "reroute"}.get(k, o)


def _run_digest(run: dict[str, Any], parcel_to_driver: dict[str, str], driver_name: dict[str, str], problem: str | None) -> str:
    """One agent run as a short ordered story, so a small model can retell it faithfully."""
    d = run.get("decision") or {}
    sid = run.get("subject_id", "?")
    drv = driver_name.get(parcel_to_driver.get(sid, ""), "?")
    traj = run.get("belief_trajectory") or []
    ask_i = next((i for i, e in enumerate(traj) if str(e["after"]).startswith("ask:")), None)
    lines = [f"RUN {run.get('run_id')} - parcel {sid}, driver {drv}, status {run.get('status')}"]
    if problem:
        lines.append(f"  1. What happened: {problem}")
    steps = [f"{s['tool'].replace('get_', '').replace('_context', '')}: {s.get('summary')}" for s in (run.get("steps") or []) if not str(s["tool"]).startswith("ask:") and s["tool"] not in ("get_shipment", "analyze_disruption", "rank_recovery_actions", "retrieve_policy_constraints")]
    if steps:
        lines.append("  2. Dallal checked the records: " + "; ".join(steps[:7]))
    for q in run.get("inquiries_live") or []:
        ans = next((a for a in q.get("answers", []) if a.get("id") == q.get("outcome")), None)
        reply = f"the reply was '{(ans or {}).get('title_en') or q.get('outcome')}'" if q.get("status") == "answered" else f"status: {q.get('status')}"
        who = {"courier": f"the driver {drv}", "dispatcher": "the dispatcher", "recipient": "the customer", "branch_supervisor": "the branch supervisor"}.get(q.get("target"), f"the {q.get('target')}")
        reply = reply.replace("the reply was", f"{drv}'s reply was" if q.get("target") == "courier" else "the reply was")
        lines.append(f"  3. Dallal asked {who} (WhatsApp sandbox, nothing sent to a phone): \"{q.get('question_en') or q.get('question')}\" - {reply}")
    if traj:
        last = traj[-1]["top"][0]
        if ask_i is not None:
            b = traj[max(0, ask_i - 1)]["top"][0]
            lines.append(f"  4. Belief: before the question {CAUSE.get(b[0], b[0])} {_pct(b[1])}; after the reply {CAUSE.get(last[0], last[0])} {_pct(last[1])}")
        else:
            lines.append(f"  4. Dallal asked nobody (the records were enough). Most likely cause: {CAUSE.get(last[0], last[0])} {_pct(last[1])}")
    typ = d.get("type")
    if run.get("status") == "awaiting_response":
        lines.append("  5. Decision: not yet - waiting for the reply")
    elif typ == "auto_eligible":
        lines.append(f"  5. Decision: Dallal resolves it alone (policy safety checks passed, no manager needed): {d.get('action_title')}")
    elif typ == "recommend":
        lines.append(f"  5. Decision: Dallal recommends '{d.get('action_title')}'; an operator must confirm")
    elif typ == "escalate":
        lines.append(f"  5. Decision: escalated to the manager: {d.get('rationale')}")
    elif typ == "incident":
        lines.append(f"  5. Decision: shared incident, handled as one coordinated plan (see PLAN). {d.get('rationale')}")
    else:
        lines.append(f"  5. Decision: {d.get('headline') or typ}")
    return "\n".join(lines)


def _plan_digest(plan: dict[str, Any], before: dict[str, str] | None, parcel_to_driver: dict[str, str], driver_name: dict[str, str]) -> str:
    pp = (plan.get("solution") or {}).get("per_parcel", {})
    ev = plan.get("evidence") or {}
    inc = plan.get("incident") or {}
    names = sorted({driver_name.get(parcel_to_driver.get(k, ""), "?") for k in pp})
    lines = [f"PLAN {plan.get('plan_id')} - incident on {inc.get('scope')} {inc.get('scope_id')}, status {plan.get('status')}: covers {len(pp)} parcels on {len(names)} drivers ({', '.join(names)})",
             f"  chance the blockage is long: {_pct(plan.get('p_long_prior'))} before the dispatcher answered, {_pct(plan.get('p_long'))} now"]
    q = (plan.get("inquiries") or [None])[0]
    if q:
        ans = next((a for a in q.get("answers", []) if a.get("id") == q.get("outcome")), None)
        reply = f"answered '{(ans or {}).get('title_en')}'" if q.get("status") == "answered" else q.get("status")
        lines.append(f"  one shared question to the dispatcher (WhatsApp sandbox) covers all parcels: \"{q.get('question_en') or q.get('question')}\" - {reply}")
    elif ev.get("asked") is False:
        lines.append(f"  no question asked: {ev.get('reason')}")
    if pp:
        lines.append("  plan: " + "; ".join(f"{k} -> {_option_words(v.get('option', ''))}" for k, v in pp.items()))
    if before and plan.get("status") != "awaiting_evidence":
        ch = [f"{k}: {_option_words(before[k])} -> {_option_words(v['option'])}" for k, v in pp.items() if k in before and before[k] != v["option"]]
        lines.append(f"  the dispatcher's answer changed {len(ch)} of {len(pp)} parcels: " + ("; ".join(ch) if ch else "none"))
    cmp = plan.get("comparison") or {}
    if cmp:
        lines.append(f"  planned together the expected value is {round(cmp.get('coordinated_utility', 0))} vs {round(cmp.get('independent_utility', 0))} one by one (simulated SAR-equivalents)")
    lines.append("  approval: a group plan needs the manager (operators cannot approve it)" + (f"; executed in simulation ({len(plan['executed'])} actions), outcomes pending" if plan.get("executed") else ""))
    return "\n".join(lines)


PLAN_W = re.compile(r"plan|manager|approv|escalat|block|road|incident|traffic|spare|pickup|reroute|dispatcher|خطة|خطه|مدير|موافق|اعتماد|تصعيد|اغلاق|إغلاق|طريق|حادث|ازدحام|مسدود|احتياط|استلام")
ACT_W = re.compile(r"today|did |done|activity|history|happened|summary|situation|overview|اليوم|فعل|نشاط|ملخص|حدث|وضع")
WHY_W = re.compile(r"why|what did|how did|explain|cause|reason|decid|investigat|ask|repl|لماذا|ماذا فعل|كيف|سبب|شرح|قرر|تحقيق|سأل|سال|رد ")


def build_context(snap: dict[str, Any], runs: list[dict[str, Any]], plans: list[dict[str, Any]], ledger: list[dict[str, Any]], ment: dict[str, list[str]], question: str = "") -> tuple[str, set[str]]:
    """Only what the question needs (a small model answers faster and more faithfully from a small context)."""
    q = _norm(question)
    drivers = snap.get("drivers", [])
    driver_name = {d["id"]: d.get("name", d["id"]) for d in drivers}
    parcel_to_driver = {p["id"]: d["id"] for d in drivers for p in d.get("parcels", [])}
    known = set(parcel_to_driver)
    problem_of = {c.get("parcel_id"): c.get("problem") for c in snap.get("cases", [])}
    focus_d, focus_p = set(ment["drivers"]), set(ment["parcels"])
    focused = bool(focus_d or focus_p)
    keep_p = focus_p | {x["id"] for dd in drivers if dd["id"] in focus_d for x in dd.get("parcels", [])}
    wants_plan, wants_act, wants_why = bool(PLAN_W.search(q)), bool(ACT_W.search(q)), bool(WHY_W.search(q))
    out: list[str] = [f"TIME: {snap.get('now')} (simulated operations clock)"]
    k = snap.get("kpis") or {}
    out.append("KPIS: " + ", ".join(f"{a.replace('_', ' ')} {b}" for a, b in k.items()))
    waiting = [pl for pl in plans if pl.get("status") == "ready"]
    out.append("WAITING FOR THE MANAGER: " + ("; ".join(f"plan {pl.get('plan_id')} ({len((pl.get('solution') or {}).get('per_parcel', {}))} parcels)" for pl in waiting) if waiting else "nothing"))
    out.append("CASES:")
    for c in snap.get("cases", []):
        out.append(f"- {c.get('label')}: parcel {c.get('parcel_id')}, driver {driver_name.get(c.get('driver_id'), '?')}, status: {c.get('status')}" + (f", run {c['run_id']}" if c.get("run_id") else "") + (f", plan {c['plan_id']}" if c.get("plan_id") else ""))
    out.append("DRIVERS (one van each; parcels in delivery order):")
    for d in drivers:
        issues = [p for p in d.get("parcels", []) if p.get("health") not in ("on_track", "delivered")]
        line = f"- {d.get('name')} ({d.get('name_ar') or ''}, van {d.get('vehicle')}): {d.get('done')} of {d.get('total')} parcels done" + (f"; note: {d['note']}" if d.get("note") else "")
        if focused and d["id"] not in focus_d and not (focus_p & {p["id"] for p in d.get("parcels", [])}):
            out.append(line)
            continue
        out.append(line + ("" if focused else f"; {len(issues)} parcel(s) need attention" if issues else ""))
        if focused or wants_act:
            for p in d.get("parcels", []):
                if p["id"] in focus_p or d["id"] in focus_d or p.get("health") not in ("on_track", "delivered"):
                    bits = f"    {p['id']} (#{p['seq']}, {p.get('district')}, {p.get('service')}, SAR {p.get('value')}): {HEALTH_WORDS.get(p.get('health'), p.get('health'))}"
                    bits += f" - {p['headline']}" if p.get("headline") else ""
                    bits += f"; exception: {p['exception']}" if p.get("exception") else ""
                    bits += f"; recovery: {p['recovery']}" if p.get("recovery") else ""
                    out.append(bits)
                    if p["id"] in focus_p and p.get("journey"):
                        out.append("      journey: " + " | ".join(p["journey"]))
        elif issues:
            out.append("    " + "; ".join(f"{p['id']} {HEALTH_WORDS.get(p.get('health'), p.get('health'))}" for p in issues[:6]))
    full_runs = [r for r in runs if (not focused or r.get("subject_id") in keep_p)]
    if focused and not full_runs:
        full_runs = []
    detailed = focused or wants_why or wants_act
    out.append("AGENT RUNS (from the Dallal backend):" if runs else "AGENT RUNS: none yet - Dallal has not investigated anything in this session.")
    for r in (full_runs if detailed else [])[:4]:
        out.append(_run_digest(r, parcel_to_driver, driver_name, problem_of.get(r.get("subject_id"))))
    for r in runs:
        known.add(str(r.get("run_id")))
        if not detailed:
            d = r.get("decision") or {}
            out.append(f"RUN {r.get('run_id')} - parcel {r.get('subject_id')}: {d.get('type')} {d.get('action_title') or d.get('headline') or ''}; status {r.get('status')}")
    before = {pl["id"]: pl.get("before") or {} for pl in snap.get("plans", [])}
    plan_in_focus = any(set((pl.get("solution") or {}).get("per_parcel", {})) & keep_p for pl in plans)
    for pl in plans:
        known.add(str(pl.get("plan_id")))
    if plans and (wants_plan or plan_in_focus or (not focused and wants_why)):
        out.append("COORDINATED PLANS (from the Dallal backend):")
        for pl in plans[:2]:
            out.append(_plan_digest(pl, before.get(pl.get("plan_id")), parcel_to_driver, driver_name))
    elif plans:
        out.append("PLANS: " + "; ".join(f"{pl.get('plan_id')} status {pl.get('status')} ({len((pl.get('solution') or {}).get('per_parcel', {}))} parcels)" for pl in plans))
    if wants_act:
        acts = [e for e in ledger if e.get("table") == "action"][:6]
        if acts:
            out.append("LEDGER (actions recorded by the backend):")
            out += [f"- action {e.get('kind') or e.get('action')} on {e.get('subject_id') or e.get('shipment_id')}" for e in acts]
        ev = snap.get("events") or []
        if ev:
            out.append("RECENT ACTIVITY:")
            out += [f"- {e.get('at')} {e.get('text')}" for e in ev[:6]]
    return "\n".join(out), known


_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩٪", "0123456789%")
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def verify(answer: str, known: set[str], context: str = "") -> list[str]:
    """Things the answer states that are not in the context: unknown parcel/run/plan identifiers and percentages nobody computed. A grounded answer has none."""
    found = {m.upper() for m in ID_RE.findall(answer)} | {m.lower() for m in RUN_RE.findall(answer)} | {m.lower() for m in PLAN_RE.findall(answer)}
    known_n = {k.upper() if k.upper().startswith("DL-") else k.lower() for k in known}
    bad = sorted(f for f in found if f not in known_n)
    if context:
        have = set(PCT_RE.findall(context.translate(_AR_DIGITS)))
        bad += sorted(f"{p}%" for p in set(PCT_RE.findall(answer.translate(_AR_DIGITS))) if p not in have)
    return bad


def sources_for(snap: dict[str, Any], runs: list[dict[str, Any]], plans: list[dict[str, Any]], ment: dict[str, list[str]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    names = {d["id"]: d.get("name", d["id"]) for d in snap.get("drivers", [])}
    for pid in ment["parcels"]:
        out.append({"type": "parcel", "id": pid, "label": pid})
    for did in ment["drivers"]:
        out.append({"type": "driver", "id": did, "label": names.get(did, did)})
    scoped = {r["run_id"] for r in runs if r.get("subject_id") in ment["parcels"]}
    for r in runs:
        if not (ment["parcels"] or ment["drivers"]) or r["run_id"] in scoped or r.get("subject_id") in {p["id"] for d in snap.get("drivers", []) if d["id"] in ment["drivers"] for p in d.get("parcels", [])}:
            out.append({"type": "run", "id": str(r["run_id"]), "label": f"run for {r.get('subject_id')}"})
    for pl in plans:
        out.append({"type": "plan", "id": str(pl.get("plan_id")), "label": "coordinated plan"})
    if not out:
        out.append({"type": "overview", "id": "operation", "label": "live operation"})
    return out[:8]


def stream(svc: Any, question: str, history: list[dict[str, str]], snap: dict[str, Any], model: str | None = None) -> Iterator[dict[str, Any]]:
    """NDJSON-ready events: start -> context -> delta* -> done, or error (the caller then falls back to the deterministic answer)."""
    t0 = time.time()
    model = model or llm.assistant_model()
    yield {"type": "start", "model": model}
    ment = mentions(question, snap)
    if not (ment["parcels"] or ment["drivers"]) and len(question.split()) <= 4 and not PLAN_W.search(_norm(question)):  # a short follow-up like "and why?" keeps the previous subject
        prev = [h["content"] for h in history if h.get("role") == "user"][-1:]
        ment = mentions(" ".join(prev), snap) if prev else ment
    runs: list[dict[str, Any]] = []
    for r in svc.store.list_runs(None, 50):
        try:
            runs.append(svc.view_run(r["run_id"]))
        except KeyError:
            continue
    plans = []
    for p in svc.store.list_plans():
        try:
            plans.append(svc.plans.view(p["plan_id"]))
        except KeyError:
            continue
    ledger = svc.store.ledger(30)
    context, known = build_context(snap, runs, plans, ledger, ment, question)
    srcs = sources_for(snap, runs, plans, ment)
    yield {"type": "context", "sources": srcs, "chars": len(context), "runs": len(runs), "plans": len(plans)}

    if os.environ.get("DALLAL_ASSISTANT_DEBUG"):  # development aid: see exactly what the model was given
        from dallal.config import PATHS

        (PATHS.root / ".data" / "logs").mkdir(parents=True, exist_ok=True)
        (PATHS.root / ".data" / "logs" / "assistant_context.txt").write_text(f"QUESTION: {question}\n\n{context}\n")
    cap = llm.capabilities(max_age_s=5.0)
    if not cap.get("available"):
        yield {"type": "error", "code": "llm_unavailable", "message": "The local model server (Ollama) is not reachable."}
        return
    if model not in (cap.get("models") or []):
        yield {"type": "error", "code": "model_missing", "message": f"The model {model} is not installed in Ollama."}
        return
    msgs: list[dict[str, str]] = [{"role": "system", "content": SYSTEM + "\n\nCONTEXT\n" + context}]
    msgs += [{"role": h["role"], "content": h["content"]} for h in history[-6:] if h.get("role") in ("user", "assistant") and h.get("content")]
    msgs.append({"role": "user", "content": question})
    text, first = "", None
    try:
        for chunk in llm.chat_stream(model, msgs):
            if first is None:
                first = round(time.time() - t0, 2)
            text += chunk
            yield {"type": "delta", "text": chunk}
    except llm.LLMError as e:
        yield {"type": "error", "code": "llm_error", "message": str(e), "partial": text}
        return
    bad = verify(text, known, context)
    yield {"type": "done", "model": model, "latency_s": round(time.time() - t0, 2), "first_token_s": first, "grounded": not bad, "violations": bad}
