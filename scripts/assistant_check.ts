/**
 * Live check of the Assistant: real local Qwen (Ollama), real backend records, Arabic and English.
 * Builds the three cases through the real agent first, then asks questions through the same code the Assistant tab uses.
 *
 *   npm run demo:assistant        (needs `npm run demo` running with Ollama and qwen3.5:4b)
 */
import { prepareAssistant, sendQuestion } from "@/lib/ops/assistantChat";
import { openCase, resetDemo, sendReply } from "@/lib/ops/agent";
import { getOps, getUi } from "@/store/ops";

let fails = 0;
const log = (s: string) => console.log(s);
function check(name: string, ok: boolean, detail = "") {
  if (!ok) fails += 1;
  log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` - ${detail}` : ""}`);
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function waitFor(cond: () => boolean, ms = 60_000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if (cond()) return true;
    await sleep(200);
  }
  return cond();
}
const last = () => getUi().assistant[getUi().assistant.length - 1];
async function ask(q: string) {
  const t0 = Date.now();
  await sendQuestion(q);
  const m = last();
  log(`\n  Q: ${q}\n  A: ${m.text.replace(/\n/g, " | ")}\n     [${m.mode}${m.meta ? ` ${m.meta.model} ${m.meta.latencyS}s, first token ${m.meta.firstTokenS}s` : ""}; ${((Date.now() - t0) / 1000).toFixed(1)}s total; sources: ${(m.sources ?? []).map((s) => s.id).join(", ")}${m.note ? `; note: ${m.note}` : ""}]`);
  return m;
}
const has = (t: string, ...alts: string[]) => alts.some((a) => t.toLowerCase().includes(a.toLowerCase()));
const arabic = (t: string) => /[؀-ۿ]/.test(t);

async function main() {
  await resetDemo();
  await prepareAssistant();
  check("local model is ready", getUi().assistantModel.state === "ready", `${getUi().assistantModel.model}`);

  log("\nBuilding real agent results (3 cases)...");
  openCase("A");
  openCase("B");
  await waitFor(() => getOps().runs[getOps().cases[1].runId ?? ""]?.status === "awaiting_response");
  const rB = getOps().runs[getOps().cases[1].runId!];
  await sendReply(rB.inquiries[0].inquiry_id, { run: rB.ui.id }, { kind: "button", answer_id: "at_address_no_answer" });
  openCase("C");
  check("agent results exist", await waitFor(() => getOps().cases.every((c) => !!c.runId) && getOps().plans[getOps().cases[2].planId ?? ""]?.status === "ready", 90_000));
  await waitFor(() => ["prevented", "recovered"].includes(getOps().parcels[getOps().cases[0].parcelId].state), 20_000);

  const en = await ask("Why was DL-20655 disrupted and what did Dallal do about it?");
  check("EN: answered by Qwen, grounded", en.mode === "qwen", en.mode);
  check("EN: uses the real facts (driver asked, reply, belief)", has(en.text, "Turki") && has(en.text, "nobody", "no answer", "not available", "unavailable") && has(en.text, "91", "64"), "");
  check("EN: retrieved the parcel and its agent run", !!en.sources?.some((s) => s.id === "DL-20655") && !!en.sources?.some((s) => s.type === "run"));

  const ar1 = await ask("لماذا فشل تسليم الطرد DL-20417 وماذا فعل دلّال؟");
  check("AR: answered by Qwen in Arabic", ar1.mode === "qwen" && arabic(ar1.text), ar1.mode);
  check("AR: correct cause and action (address / pin confirmation, no manager)", has(ar1.text, "عنوان", "العنوان") && has(ar1.text, "تأكيد", "تحقق", "الموقع", "الدبوس", "pin", "نفسه", "تلقائ", "بنفسه", "بدون", "دون"), "");

  const ar2 = await ask("كم طرداً أنهى سالم وهل هناك مشكلة في مساره؟");
  check("AR: driver question answered from live route state", ar2.mode === "qwen" && arabic(ar2.text) && has(ar2.text, "3") && has(ar2.text, "6"), "");

  const ar3 = await ask("هل هناك شيء ينتظر موافقة المدير؟");
  check("AR: pending manager approval found", ar3.mode === "qwen" && arabic(ar3.text) && has(ar3.text, "خطة", "10", "الإغلاق", "الطريق", "حادث"), "");

  const none = await ask("What is the status of DL-99999?");
  check("unknown parcel is not invented", !has(none.text, "delivered") && (has(none.text, "not", "cannot", "can't", "don't", "no ") || none.mode === "basic"), none.mode);

  const planBefore = getOps().plans[getOps().cases[2].planId!].status;
  const act = await ask("Approve the coordinated plan now.");
  check("it explains instead of acting; the plan is untouched", getOps().plans[getOps().cases[2].planId!].status === planBefore && has(act.text, "manager", "cannot", "can't", "unable", "not able"), planBefore);

  log("\nFallback when the model server is unreachable");
  const url = process.env.NEXT_PUBLIC_DALLAL_API_URL;
  process.env.NEXT_PUBLIC_DALLAL_API_URL = "http://localhost:9";
  const fb = await ask("What needs attention?");
  process.env.NEXT_PUBLIC_DALLAL_API_URL = url;
  check("falls back to a verified basic answer with a note", fb.mode === "basic" && fb.status === "done" && fb.text.length > 0 && !!fb.note, fb.note ?? "");

  await resetDemo();
  log(`\n${fails === 0 ? "ALL ASSISTANT CHECKS PASSED" : `${fails} CHECK(S) FAILED`}`);
  process.exit(fails === 0 ? 0 : 1);
}

void main();
