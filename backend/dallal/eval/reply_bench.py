"""Free-text reply interpretation: rule interpreter vs LLM stage vs rules-then-LLM, on the hand-written set (dallal.eval.reply_set).

An LLM answer is accepted only if it is one of the inquiry's own answer ids (schema-constrained) AND its stated confidence >= 0.8;
trust is capped at 0.9 by the runtime. The costly error is a FALSE ACCEPT (a wrong answer id, or an answer where abstaining was right):
it would become evidence. Run: python -I -m dallal.eval.reply_bench qwen3.5:4b [qwen3.5:9b ...]  -> docs/experiments/reply_interpretation.json
"""

from __future__ import annotations

import os

os.environ.setdefault("DALLAL_LLM_BACKEND", "ollama")  # benchmarks talk to a local Ollama unless told otherwise

import json
import sys
import time

import pandas as pd

from dallal.agent.v2 import inquiry as iq
from dallal.channels.interpret import interpret
from dallal.channels.whatsapp import Inbound
from dallal.config import PATHS
from dallal.eval.reply_set import REPLIES
from dallal.llm.interpret import suggest

ACCEPT_CONF = 0.8
def llm_interpret(model: str, spec: iq.InquirySpec, text: str) -> tuple[str | None, float, float]:
    sg = suggest(model, spec, text)
    return sg.answer_id, sg.confidence, sg.latency_s


def rules_interpret(spec: iq.InquirySpec, text: str) -> str | None:
    m = Inbound("w", "x", 0, "text", text=text)
    r = interpret(m, spec, "inq", {})
    return None if r.needs_review else r.answer_id


def _score(rows: list[dict], col: str) -> dict:
    df = pd.DataFrame(rows)
    acc = df[df[col].notna()]
    pos = df[df["expected"].notna()]
    wrong = acc[acc[col] != acc["expected"]]  # includes accepting where abstaining was right (expected NaN)
    return {"n": int(len(df)), "coverage_of_answerable": round(float((pos[col] == pos["expected"]).mean()), 3), "accepted": int(len(acc)),
            "false_accept_rate": round(float(len(wrong) / max(len(acc), 1)), 3), "false_accepts": int(len(wrong)),
            "abstain_correct_on_unanswerable": round(float(df[df["expected"].isna()][col].isna().mean()), 3)}


def run(models: list[str]) -> dict:
    rows = []
    for sid, text, exp in REPLIES:
        s = iq.spec(sid)
        rows.append({"spec": sid, "text": text, "expected": exp, "rules": rules_interpret(s, text)})
    out: dict = {"set": {"n": len(rows), "answerable": sum(r["expected"] is not None for r in rows), "note": "hand-written by the team; not real traffic"}, "rules_only": _score(rows, "rules"), "models": {}}
    for m in models:
        lat = []
        for r in rows:
            a, c, l_ = llm_interpret(m, iq.spec(r["spec"]), r["text"])
            lat.append(l_)
            r["llm"] = a if c >= ACCEPT_CONF else None
            r["llm_raw"] = a
            r["llm_conf"] = c
            r["rules_then_llm"] = r["rules"] if r["rules"] is not None else r["llm"]
        for r in rows:
            r["lang"] = "ar" if any("\u0600" <= ch <= "\u06ff" for ch in r["text"]) else "en"
        by_lang = {}
        for lg in ("ar", "en"):
            sub = [r for r in rows if r["lang"] == lg]
            by_lang[lg] = {"llm_only": _score(sub, "llm"), "rules_only": _score(sub, "rules")}
        out["models"][m] = {"by_language": by_lang, "rows": [{k: r.get(k) for k in ("spec", "text", "expected", "rules", "llm", "llm_conf", "lang")} for r in rows], "llm_only": _score(rows, "llm"), "rules_then_llm": _score(rows, "rules_then_llm"), "median_latency_s": round(float(pd.Series(lat).median()), 2),
                            "errors": [{"spec": r["spec"], "text": r["text"], "expected": r["expected"], "got": r["llm"], "conf": r["llm_conf"]} for r in rows if r["llm"] is not None and r["llm"] != r["expected"]]}
        print(m, json.dumps({k: v for k, v in out["models"][m].items() if k != "errors"}))
    out["origin"] = "synthetic-handwritten (not real traffic)"
    out["generated"] = pd.Timestamp.now().isoformat(timespec="seconds")
    p = PATHS.docs / "experiments"
    p.mkdir(parents=True, exist_ok=True)
    prev = p / "reply_interpretation.json"
    if prev.exists():  # keep earlier models when benchmarking one at a time
        out["models"] = {**json.loads(prev.read_text()).get("models", {}), **out["models"]}
    (p / "reply_interpretation.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    return out


if __name__ == "__main__":
    t0 = time.time()
    res = run(sys.argv[1:])
    print("rules_only", res["rules_only"], f"({time.time() - t0:.0f}s)")
