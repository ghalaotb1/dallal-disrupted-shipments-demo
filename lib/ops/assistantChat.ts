import { ask } from "@/lib/ops/assistant";
import { assistantWarmup, buildAssistantSnapshot, streamAssistant } from "@/lib/ops/assistantLive";
import { getOps, getUi, setUi } from "@/store/ops";
import type { AssistantMessage } from "@/types/ops";

let seq = 0;
let current: AbortController | null = null;

const patch = (id: string, fn: (m: AssistantMessage) => AssistantMessage) => setUi({ assistant: getUi().assistant.map((m) => (m.id === id ? fn(m) : m)) });

/** Stop any answer in flight (a reset starts a fresh operation, so an old answer must not land in it). */
export function cancelAssistant() {
  current?.abort();
  current = null;
}

/** Load the local model before the first question, so the first answer does not wait for a cold start. */
export async function prepareAssistant(): Promise<void> {
  const st = getUi().assistantModel.state;
  if (st === "loading" || st === "ready") return;
  setUi({ assistantModel: { state: "loading" } });
  try {
    const r = await assistantWarmup();
    setUi({ assistantModel: r.available ? { state: "ready", model: r.model } : { state: "unavailable", model: r.model, reason: r.reason ?? "unavailable" } });
  } catch (e) {
    setUi({ assistantModel: { state: "unavailable", reason: e instanceof Error ? e.message : "unavailable" } });
  }
}

function fallback(id: string, question: string, why: string) {
  const a = ask(question, getOps());
  patch(id, (m) => ({ ...m, text: a.text, links: a.links, status: "done", mode: "basic", sources: undefined, note: why, phase: undefined }));
}

export async function sendQuestion(text: string): Promise<void> {
  const q = text.trim();
  if (!q) return;
  cancelAssistant();
  const ctl = new AbortController();
  current = ctl;
  const uid = `u${++seq}`;
  const aid = `a${++seq}`;
  const history = getUi().assistant.filter((m) => m.status !== "thinking" && m.text).slice(-6).map((m) => ({ role: m.role, content: m.text }));
  const cold = getUi().assistantModel.state !== "ready";
  setUi({ assistant: [...getUi().assistant, { id: uid, role: "user", text: q }, { id: aid, role: "assistant", text: "", status: "thinking", phase: "Reading live data…" }] });
  let got = "";
  let finished = false;
  try {
    await streamAssistant(
      q,
      history,
      buildAssistantSnapshot(getOps()),
      (ev) => {
        if (ev.type === "context") patch(aid, (m) => ({ ...m, sources: ev.sources, phase: cold ? "Loading the local model (first question)…" : "Qwen is answering…" }));
        else if (ev.type === "delta") {
          got += ev.text;
          patch(aid, (m) => ({ ...m, text: got, status: "streaming", phase: undefined }));
        } else if (ev.type === "done") {
          finished = true;
          if (!ev.grounded) fallback(aid, q, `The model mentioned items that are not in the live data (${ev.violations.join(", ")}), so a verified basic answer is shown instead.`);
          else {
            patch(aid, (m) => ({ ...m, status: "done", mode: "qwen", meta: { model: ev.model, latencyS: ev.latency_s, firstTokenS: ev.first_token_s } }));
            setUi({ assistantModel: { state: "ready", model: ev.model } });
          }
        } else if (ev.type === "error") {
          finished = true;
          setUi({ assistantModel: { state: ev.code === "llm_unavailable" || ev.code === "model_missing" ? "unavailable" : getUi().assistantModel.state, reason: ev.message, model: getUi().assistantModel.model } });
          fallback(aid, q, `${ev.message} Showing a basic answer.`);
        }
      },
      ctl.signal,
    );
    if (!finished && ctl.signal.aborted) return;
    if (!finished) fallback(aid, q, "The answer stream ended unexpectedly. Showing a basic answer.");
  } catch (e) {
    if (ctl.signal.aborted) return;
    fallback(aid, q, `${e instanceof Error ? e.message : "The assistant is unavailable"}. Showing a basic answer.`);
  } finally {
    if (current === ctl) current = null;
  }
}
