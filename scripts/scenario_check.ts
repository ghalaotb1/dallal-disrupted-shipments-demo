/**
 * Headless end-to-end check of the three demonstration scenarios.
 *
 * It drives the SAME application code the browser uses (world data, scenario staging, case/plan snapshots, agent flows, store) against the
 * running local backend, and asserts what the real agent and policy decided. Nothing here is mocked.
 *
 *   npm run demo:scenarios            (needs `npm run demo` running: backend on :8000)
 */
import { planApi, api, ApiError } from "@/lib/live/client";
import { decidePlan, executeRun, openCase, resetDemo, sendReply } from "@/lib/ops/agent";
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
type Id = "A" | "B" | "C";
let cur: Id = "A";
const theCase = (id: Id = cur) => getOps().cases.find((c) => c.scenario === id)!;
const run = (id: Id = cur) => {
  const r = theCase(id).runId;
  return r ? getOps().runs[r] : undefined;
};
/** Fresh operation, then open the case: Dallal starts investigating by itself (no click). */
async function start(id: Id) {
  await resetDemo();
  cur = id;
  openCase(id);
}
const dtype = () => String(run()?.decision.type ?? "");
const parcel = (id: string) => getOps().parcels[id];

async function scenarioA() {
  log("\nScenario A - Dallal resolves an address failure without a manager");
  await start("A");
  const a = theCase();
  check("problem is on the driver's route; the agent starts by itself", parcel(a.parcelId).state === "attempt_failed" && a.driverId === "yousef", `${a.parcelId} on ${a.driverId}`);
  check("agent completed", await waitFor(() => run()?.status === "completed"), `status ${run()?.status}`);
  check("decision is auto_eligible (policy permits autonomy)", dtype() === "auto_eligible", `${dtype()} / ${run()?.decision.action}`);
  check("action is the address confirmation", run()?.decision.action === "verify_address");
  check("no question was asked (records were enough)", (run()?.inquiries.length ?? 0) === 0);
  check("cause identified from evidence", run()?.decision.top_cause === "address_issue" && Number(run()?.decision.posterior) > 0.85, `p=${run()?.decision.posterior}`);
  check("executed automatically, in simulation", await waitFor(() => ["recovering", "prevented"].includes(parcel(a.parcelId).state), 8000), parcel(a.parcelId).state);
  check("outcome recorded only after the simulated world observes it", await waitFor(() => parcel(a.parcelId).state === "prevented", 12_000) && !!parcel(a.parcelId).simOutcome);
  const decision = `${dtype()}/${run()?.decision.action}`;
  // replay determinism
  await start("A");
  await waitFor(() => run()?.status === "completed");
  check("replay gives the same decision", `${dtype()}/${run()?.decision.action}` === decision);
}

async function scenarioB() {
  log("\nScenario B - Dallal asks the driver, the reply changes the decision");
  await start("B");
  const a = theCase();
  check("agent started on its own and paused to ask a person", await waitFor(() => run()?.status === "awaiting_response"), `status ${run()?.status}`);
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
  await start("B");
  await waitFor(() => run()?.status === "awaiting_response");
  const inq2 = run()!.inquiries[0];
  await sendReply(inq2.inquiry_id, { run: theCase().runId }, { kind: "button", answer_id: "cannot_find_address" });
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
  await start("C");
  const a = theCase();
  check("problem spans several drivers", a.affectedDriverIds.length === 3 && a.exposedParcelIds.length === 6);
  check("agent completed", await waitFor(() => run()?.status === "completed"));
  check("agent recognised a shared incident, not a single failure", dtype() === "incident", String(run()?.decision.headline));
  check("coordinated plan created for all parcels", await waitFor(() => !!theCase().planId), "");
  const planId = theCase().planId!;
  check("plan covers 10 parcels on 3 drivers", Object.keys(getOps().plans[planId].solution.per_parcel).length === 10);
  const plan0 = getOps().plans[planId];
  check("one shared question to the dispatcher (sandbox)", plan0.status === "awaiting_evidence" && plan0.inquiries.length === 1 && plan0.inquiries[0].target === "dispatcher" && plan0.inquiries[0].real_delivery === false);
  const before = { ...getOps().planBefore[planId] };
  check("sandbox dispatcher is 'typing' first (nothing is answered instantly)", theCase().reply === "typing");
  check("plan became ready for approval with NO manual reply", await waitFor(() => getOps().plans[planId].status === "ready", 30_000), getOps().plans[planId].status);
  const plan1 = getOps().plans[planId];
  const inbound = plan1.inquiries[0].messages.find((m) => m.direction === "in");
  check("the reply went through the backend inbound pipeline and was interpreted", inbound?.interpretation?.answer_id === "blocked_long" && plan1.inquiries[0].status === "answered", `${inbound?.interpretation?.method}`);
  check("the reply is sandbox-only (no real delivery)", plan1.inquiries[0].real_delivery === false && plan1.inquiries[0].delivery_mode === "sandbox");
  check("belief about the blockage moved (30% -> 88%)", plan1.p_long_prior === 0.3 && plan1.p_long > 0.8, `${plan1.p_long_prior} -> ${plan1.p_long}`);
  check("the plan was re-optimised after the reply", plan1.evidence.answer?.id === "blocked_long");
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
  await start("C");
  await waitFor(() => !!theCase().planId);
  const p2 = theCase().planId!;
  const before2 = JSON.stringify(Object.entries(getOps().planBefore[p2]).sort());
  await waitFor(() => getOps().plans[p2].status === "ready", 20_000);
  const after2 = JSON.stringify(Object.entries(getOps().plans[p2].solution.per_parcel).map(([k, v]) => [k, v.option]).sort());
  check("replay gives the same plan before and after the dispatcher's answer", before2 === firstBefore && after2 === firstAfter);
}

async function allInOneOperation() {
  log("\nAll three cases in ONE operation, opened in a different order (C, B, A)");
  await resetDemo();
  check("three cases are open from the start", getOps().cases.length === 3);
  cur = "C";
  openCase("C");
  await waitFor(() => !!theCase("C").planId);
  const plan = getOps().plans[theCase("C").planId!];
  check("C: incident plan ready for the manager", await waitFor(() => getOps().plans[plan.plan_id].status === "ready", 20_000));
  openCase("B");
  await waitFor(() => run("B")?.status === "awaiting_response");
  await sendReply(run("B")!.inquiries[0].inquiry_id, { run: theCase("B").runId }, { kind: "button", answer_id: "at_address_no_answer" });
  await waitFor(() => run("B")?.status === "completed");
  check("B: same decision when other cases were handled first", run("B")?.decision.type === "auto_eligible" && run("B")?.decision.action === "contact_recipient", String(run("B")?.decision.action));
  openCase("A");
  await waitFor(() => run("A")?.status === "completed");
  check("A: same decision, no question, no false incident", run("A")?.decision.type === "auto_eligible" && run("A")?.decision.action === "verify_address" && (run("A")?.inquiries.length ?? 0) === 0, String(run("A")?.decision.type));
  check("C is still waiting for the manager while A and B were resolved", getOps().plans[plan.plan_id].status === "ready");
  await decidePlan(plan.plan_id, "approve");
  check("manager approval still works", getOps().plans[plan.plan_id].status === "executed_simulated");
}

async function resetDuringTyping() {
  log("\nReset while the dispatcher is 'typing'");
  await start("C");
  await waitFor(() => !!theCase().planId);
  const stale = theCase().planId!;
  await resetDemo(); // clears the backend and the world before the reply was sent
  await sleep(6000);
  check("no stale reply or plan leaks into the fresh operation", Object.keys(getOps().plans).length === 0 && theCase("C").reply === undefined && theCase("C").planId === undefined, stale);
  openCase("C");
  check("replaying works: plan, automatic reply, ready", await waitFor(() => !!theCase("C").planId && getOps().plans[theCase("C").planId!].status === "ready", 40_000));
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
  await resetDuringTyping();
  await allInOneOperation();
  await resetDemo();
  log(`\n${fails === 0 ? "ALL SCENARIO CHECKS PASSED" : `${fails} CHECK(S) FAILED`}`);
  process.exit(fails === 0 ? 0 : 1);
}

void main();
