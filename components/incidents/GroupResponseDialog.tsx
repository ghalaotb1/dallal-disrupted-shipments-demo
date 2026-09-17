"use client";

import { useState } from "react";
import { Dialog } from "radix-ui";
import { motion } from "motion/react";
import { CircleCheck, Loader2, Lock, ShieldCheck, X } from "lucide-react";
import { people } from "@/data/people";
import { cn } from "@/lib/cn";
import { plural } from "@/lib/format";
import { incidentService } from "@/services";
import type { GroupResponseStage } from "@/services/contracts";
import { useUi } from "@/store/ui";
import { useWorld } from "@/store/world";
import { Button } from "@/components/common/Button";

type Phase = "confirm" | "approval" | "running" | "done";

export function GroupResponseDialog() {
  const incidentId = useUi((s) => s.groupResponseIncidentId);
  const set = useUi((s) => s.set);
  const inc = useWorld((w) => (incidentId ? w.incidents[incidentId] : undefined));
  const [phase, setPhase] = useState<Phase>("confirm");
  const [doneSteps, setDoneSteps] = useState<string[]>([]);
  const [activeStep, setActiveStep] = useState<string | null>(null);

  const close = () => {
    if (phase === "approval" || phase === "running") return;
    set({ groupResponseIncidentId: null });
    setPhase("confirm");
    setDoneSteps([]);
    setActiveStep(null);
  };

  const apply = async () => {
    if (!inc) return;
    setPhase("approval");
    await incidentService.applyGroupResponse(inc.id, (p: GroupResponseStage) => {
      if (p.stage === "approved") setPhase("running");
      if (p.stage === "step_started") setActiveStep(p.stepId);
      if (p.stage === "step_done") setDoneSteps((d) => [...d, p.stepId]);
      if (p.stage === "done") {
        setActiveStep(null);
        setPhase("done");
      }
    });
  };

  const total = inc ? new Set(inc.response.steps.flatMap((s) => s.shipments)).size : 0;
  return (
    <Dialog.Root open={!!incidentId} onOpenChange={(o) => (!o ? close() : null)}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[90] bg-ink/30 backdrop-blur-[2px]" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-[91] w-[560px] max-w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 rounded-2xl border border-line bg-surface shadow-pop outline-none">
          {inc ? (
            <>
              <div className="flex items-start justify-between gap-3 border-b border-line-soft px-5 py-4">
                <div>
                  <Dialog.Title className="text-15 font-semibold text-ink">Apply group response · {inc.id}</Dialog.Title>
                  <Dialog.Description className="mt-0.5 text-xs text-ink-3">
                    {inc.title} — one coordinated action for {plural(total, "shipment")}. Runs in the demo environment only.
                  </Dialog.Description>
                </div>
                <button onClick={close} disabled={phase === "approval" || phase === "running"} className="rounded-md p-1 text-ink-4 hover:bg-hover disabled:opacity-40" aria-label="Close">
                  <X className="size-4" />
                </button>
              </div>

              <div className="px-5 py-4">
                <div className={cn("flex items-center gap-3 rounded-lg border px-3 py-2.5", phase === "confirm" ? "border-review-200 bg-review-50" : "border-ok-200 bg-ok-50")}>
                  {phase === "approval" ? <Loader2 className="size-4 animate-spin text-review-600" /> : phase === "confirm" ? <Lock className="size-4 text-review-600" /> : <CircleCheck className="size-4 text-ok-600" />}
                  <div className="text-13">
                    {phase === "confirm" ? (
                      <>
                        <span className="font-semibold text-ink">Supervisor approval required.</span> <span className="text-ink-2">A request goes to {people.supervisor.name} first.</span>
                      </>
                    ) : phase === "approval" ? (
                      <span className="text-ink-2">Waiting for {people.supervisor.name} to approve…</span>
                    ) : (
                      <>
                        <span className="font-semibold text-ink">Approved by {people.supervisor.name}</span> <span className="text-ink-3">(simulated response)</span>
                      </>
                    )}
                  </div>
                </div>

                <ol className="mt-3 space-y-1.5">
                  {inc.response.steps.map((st, i) => {
                    const done = doneSteps.includes(st.id) || inc.response.state === "applied";
                    const active = activeStep === st.id;
                    return (
                      <motion.li key={st.id} layout className={cn("flex items-center gap-3 rounded-lg px-3 py-2", active ? "bg-brand-25" : "")}>
                        <span className={cn("flex size-6 shrink-0 items-center justify-center rounded-full text-2xs font-semibold", done ? "bg-ok-500 text-white" : active ? "bg-brand-600 text-white" : "bg-muted text-ink-3")}>
                          {done ? <CircleCheck className="size-3.5" /> : active ? <Loader2 className="size-3.5 animate-spin" /> : i + 1}
                        </span>
                        <span className="flex-1 text-13 text-ink-2">{st.title}</span>
                        <span className="text-2xs text-ink-4 tabular">{plural(st.shipments.length, "shipment")}</span>
                      </motion.li>
                    );
                  })}
                </ol>
              </div>

              <div className="flex items-center justify-end gap-2 border-t border-line-soft px-5 py-3">
                {phase === "done" ? (
                  <Button variant="primary" onClick={close}>
                    <CircleCheck /> Done
                  </Button>
                ) : (
                  <>
                    <Button variant="ghost" onClick={close} disabled={phase !== "confirm"}>
                      Cancel
                    </Button>
                    <Button variant="primary" onClick={apply} loading={phase === "approval" || phase === "running"}>
                      <ShieldCheck /> {phase === "confirm" ? "Request approval & apply" : "Applying…"}
                    </Button>
                  </>
                )}
              </div>
            </>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
