/**
 * Headless end-to-end check of the three demonstration scenarios.
 *
 * It drives the SAME application code the browser uses (world data, scenario staging, case/plan snapshots, agent flows, store) against the
 * running local backend, and asserts what the real agent and policy decided. Nothing here is mocked.
 *
 *   npm run demo:scenarios            (needs `npm run demo` running: backend on :8000)
 */
import { planApi, api, ApiError } from "@/lib/live/client";
import { decidePlan, executeRun, investigate, resetDemo, sendReply, startScenario } from "@/lib/ops/agent";
import { getOps, getUi } from "@/store/ops";

let fails = 0;
const log = (s: string) => console.log(s);
function check(name: string, ok: boolean, detail = "") {
  if (!ok) fails += 1;
  log(`  ${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` - ${detail}` : ""}`);
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function waitFor(cond: () => boolean, ms = 30_000, step = 150): Promise<boolean> {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    if (cond()) return true;
    await sleep(step);
  }
  return cond();
}
const run = () => {
  const id = getOps().active?.runId;
  return id ? getOps().runs[id] : undefined;
};
const dtype = () => String(run()?.decision.type ?? "");
const parcel = (id: string) => getOps().parcels[id];

async function scenarioA() {
  log("\nScenario A - Dallal resolves an address failure without a manager");
  await startScenario("A");
  const a = getOps().active!;
  check("problem is staged on the driver's route", parcel(a.parcelId).state === "attempt_failed" && a.driverId === "yousef", `${a.parcelId} on ${a.driverId}`);
  await investigate();
  check("agent completed", await waitFor(() => run()?.status === "completed"), `status ${run()?.status}`);
  check("decision is auto_eligible (policy permits autonomy)", dtype() === "auto_eligible", `${dtype()} / ${run()?.decision.action}`);
  check("action is the address confirmation", run()?.decision.action === "verify_address");
  check("no question was asked (records were enough)", (run()?.inquiries.length ?? 0) === 0);
  check("cause identified from evidence", run()?.decision.top_cause === "address_issue" && Number(run()?.decision.posterior) > 0.85, `p=${run()?.decision.posterior}`);
  check("executed automatically, in simulation", await waitFor(() => ["recovering", "prevented"].includes(parcel(a.parcelId).state), 8000), parcel(a.parcelId).state);
  check("outcome recorded only after the simulated world observes it", await waitFor(() => parcel(a.parcelId).state === "prevented", 12_000) && !!parcel(a.parcelId).simOutcome);
  const decision = `${dtype()}/${run()?.decision.action}`;
  // replay determinism
  await startScenario("A");
  await investigate();
  await waitFor(() => run()?.status === "completed");
  check("replay gives the same decision", `${dtype()}/${run()?.decision.action}` === decision);
}

async function scenarioB() {
  log("\nScenario B - Dallal asks the driver, the reply changes the decision");
  await startScenario("B");
  const a = getOps().active!;
  await investigate();
  check("agent paused to ask a person", await waitFor(() => run()?.status === "awaiting_response"), `status ${run()?.status}`);
  const inq = run()?.inquiries[0];
  check("it asked the driver (not the customer) after reading the records", inq?.target === "courier" && run()!.ui.steps.length >= 6, `${inq?.target}, ${run()?.ui.steps.length} steps`);
  check("message is sandbox only - no real delivery", inq?.delivery_mode === "sandbox" && inq?.real_delivery === false);
  const before = run()!.trajectory.at(-1)!.top[0];
  await sendReply(inq!.inquiry_id, { run: a.runId }, { kind: "button", answer_id: "at_address_no_answer" });
  check("agent resumed and finished", await waitFor(() => run()?.status === "completed"), `status ${run()?.status}`);
  check("reply raised belief in 'customer not available'", run()!.trajectory.at(-1)!.top[0][0] === "recipient_unavailable" && run()!.trajectory.at(-1)!.top[0][1] > 0.85, `${before[0]} ${(before[1] * 100).toFixed(0)}% -> ${(run()!.trajectory.at(-1)!.top[0][1] * 100).toFixed(0)}%`);
  check("decision is auto_eligible contact_recipient", dtype() === "auto_eligible" && run()?.decision.action === "contact_recipient", `${dtype()} / ${run()?.decision.action}`);
  check("executed automatically in simulation", await waitFor(() => ["recovering", "recovered"].includes(parcel(a.parcelId).state), 8000));

  // the same question, a different answer -> a different decision (the answer really matters)
  await startScenario("B");
  await investigate();
  await waitFor(() => run()?.status === "awaiting_response");
  const inq2 = run()!.inquiries[0];
  await sendReply(inq2.inquiry_id, { run: getOps().active!.runId }, { kind: "button", answer_id: "cannot_find_address" });
  await waitFor(() => run()?.status === "completed");
  check("a different reply changes the decision", `${dtype()}/${run()?.decision.action}` !== "auto_eligible/contact_recipient", `${dtype()} / ${run()?.decision.action}`);
  if (dtype() === "recommend") {
    await sleep(800);
    check("a recommendation is NOT executed until a person confirms", parcel(a.parcelId).state === "attempt_failed");
    await executeRun(run()!.ui.id, "Desk operator", "analyst");
    check("operator confirmation executes it", parcel(a.parcelId).state === "recovering");
  }
}

async function scenarioC() {
  log("\nScenario C - one road blockage, three drivers, manager approval");
  await startScenario("C");
  const a = getOps().active!;
  check("problem spans several drivers", a.affectedDriverIds.length === 3 && a.exposedParcelIds.length === 6);
  await investigate();
  check("agent completed", await waitFor(() => run()?.status === "completed"));
  check("agent recognised a shared incident, not a single failure", dtype() === "incident", String(run()?.decision.headline));
  check("coordinated plan created for all parcels", await waitFor(() => !!getOps().active?.planId), "");
  const planId = getOps().active!.planId!;
  check("plan covers 10 parcels on 3 drivers", Object.keys(getOps().plans[planId].solution.per_parcel).length === 10);
  const plan0 = getOps().plans[planId];
  check("one shared question to the dispatcher (sandbox)", plan0.status === "awaiting_evidence" && plan0.inquiries.length === 1 && plan0.inquiries[0].target === "dispatcher" && plan0.inquiries[0].real_delivery === false);
  const before = { ...getOps().planBefore[planId] };
  await sendReply(plan0.inquiries[0].inquiry_id, { plan: planId }, { kind: "button", answer_id: "blocked_long" });
  check("plan became ready for approval", await waitFor(() => getOps().plans[planId].status === "ready", 20_000), getOps().plans[planId].status);
  const plan1 = getOps().plans[planId];
  const changed = Object.entries(plan1.solution.per_parcel).filter(([k, v]) => before[k] !== v.option).length;
  check("the single answer changed several parcels' decisions", changed >= 3, `${changed} of 10 changed`);
  check("policy requires a supervisor", plan1.approval.required === "supervisor", plan1.approval.why);
  check("all plan parcels wait for the manager in the UI state", Object.keys(plan1.solution.per_parcel).every((id) => parcel(id).state === "awaiting_manager"));
  let refused = 0;
  try {
    await planApi.decide(planId, { decision: "approve", by: "Desk operator", role: "analyst" });
  } catch (e) {
    refused = e instanceof ApiError ? e.status : -1;
  }
  check("an operator cannot approve the plan (backend refuses)", refused === 403, `status ${refused}`);
  check("nothing executed before the manager approved", getOps().plans[planId].status === "ready");
  await decidePlan(planId, "approve");
  check("manager approval executed the plan in simulation", getOps().plans[planId].status === "executed_simulated");
  const states = Object.keys(plan1.solution.per_parcel).map((id) => parcel(id).state);
  check("every parcel moved to a recovery state (no success claimed)", states.every((s) => s === "reassigned" || s === "recovering"), [...new Set(states)].join(","));
  const ledger = await fetch(`${process.env.NEXT_PUBLIC_DALLAL_API_URL}/v1/ledger?limit=80`).then((r) => r.json() as Promise<{ table?: string; kind?: string }[]>);
  check("backend ledger holds the actions with outcomes still pending", ledger.filter((r) => r.table === "outcome" && r.kind === "pending").length >= 10);
  check("manager view is closed after the decision", getUi().role === "operator");

  // replay determinism: the same situation gives the same plan before and after the answer
  const firstBefore = JSON.stringify(Object.entries(before).sort());
  const firstAfter = JSON.stringify(Object.entries(plan1.solution.per_parcel).map(([k, v]) => [k, v.option]).sort());
  await startScenario("C");
  await investigate();
  await waitFor(() => !!getOps().active?.planId);
  const p2 = getOps().active!.planId!;
  const before2 = JSON.stringify(Object.entries(getOps().planBefore[p2]).sort());
  await sleep(400);
  await sendReply(getOps().plans[p2].inquiries[0].inquiry_id, { plan: p2 }, { kind: "button", answer_id: "blocked_long" });
  await waitFor(() => getOps().plans[p2].status === "ready", 20_000);
  const after2 = JSON.stringify(Object.entries(getOps().plans[p2].solution.per_parcel).map(([k, v]) => [k, v.option]).sort());
  check("replay gives the same plan before and after the dispatcher's answer", before2 === firstBefore && after2 === firstAfter);
}

async function main() {
  const meta = await api.meta().catch(() => null);
  if (!meta) {
    console.error("backend not reachable - run `npm run demo` first");
    process.exit(2);
  }
  check("WhatsApp is sandbox and actions are simulated", meta.whatsapp?.mode === "sandbox" && meta.execution?.mode === "simulated");
  await scenarioA();
  await scenarioB();
  await scenarioC();
  await resetDemo();
  log(`\n${fails === 0 ? "ALL SCENARIO CHECKS PASSED" : `${fails} CHECK(S) FAILED`}`);
  process.exit(fails === 0 ? 0 : 1);
}

void main();
