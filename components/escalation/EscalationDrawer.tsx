"use client";

import { useMemo, useState } from "react";
import { Dialog } from "radix-ui";
import { AnimatePresence, motion } from "motion/react";
import { Bell, Check, CircleCheck, Clock3, FileSearch, Mail, MapPin, MessageSquareText, Send, UserRoundCheck, X } from "lucide-react";
import { people } from "@/data/people";
import { cn } from "@/lib/cn";
import { useDemoNow } from "@/hooks/useDemoNow";
import { notificationService } from "@/services";
import { draftForIncident, draftForShipment, type EscalationDraft } from "@/services/logic/escalationDraft";
import { useUi } from "@/store/ui";
import { useWorld } from "@/store/world";
import { Avatar } from "@/components/common/Card";
import { PriorityBadge, SimTag } from "@/components/common/Badges";
import { Button } from "@/components/common/Button";
import type { Escalation } from "@/types/domain";

export function EscalationDrawer() {
  const draftTarget = useUi((s) => s.escalation);
  const set = useUi((s) => s.set);
  return (
    <Dialog.Root open={!!draftTarget} onOpenChange={(o) => (!o ? set({ escalation: null }) : null)}>
      {draftTarget ? (
        <Dialog.Portal>
          <Dialog.Overlay asChild>
            <motion.div className="fixed inset-0 z-[90] bg-ink/25" initial={{ opacity: 0 }} animate={{ opacity: 1 }} />
          </Dialog.Overlay>
          <Dialog.Content asChild aria-describedby={undefined}>
            <motion.aside
              initial={{ x: 40, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              transition={{ type: "spring", stiffness: 420, damping: 38 }}
              className="fixed inset-y-0 right-0 z-[91] flex w-[540px] max-w-[100vw] flex-col border-l border-line bg-surface shadow-pop outline-none"
            >
              <DrawerBody key={`${draftTarget.target.type}-${draftTarget.target.id}`} target={draftTarget.target} runId={draftTarget.runId} onClose={() => set({ escalation: null })} />
            </motion.aside>
          </Dialog.Content>
        </Dialog.Portal>
      ) : null}
    </Dialog.Root>
  );
}

function DrawerBody({ target, runId, onClose }: { target: { type: "shipment" | "incident"; id: string }; runId?: string; onClose: () => void }) {
  const set = useUi((s) => s.set);
  const shipments = useWorld((w) => w.shipments);
  const incidents = useWorld((w) => w.incidents);
  const runs = useWorld((w) => w.agentRuns);
  const now = useDemoNow(30_000);
  const [note, setNote] = useState("");
  const [email, setEmail] = useState(true);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState<Escalation | null>(null);

  const draft: EscalationDraft | null = useMemo(() => {
    if (target.type === "shipment") {
      const s = shipments[target.id];
      if (!s) return null;
      const run =
        (runId && runs[runId]) ||
        Object.values(runs)
          .filter((r) => r.shipmentId === s.id && r.mode === "investigation")
          .sort((a, b) => b.startedAt - a.startedAt)[0];
      return draftForShipment(s, run, now);
    }
    const inc = incidents[target.id];
    return inc ? draftForIncident(inc, shipments, now) : null;
    // Freeze the draft when the drawer opens so it doesn't shift while the analyst reads it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target.type, target.id]);

  if (!draft) return null;

  const send = async () => {
    setSending(true);
    const esc = await notificationService.sendEscalation({ ...draft, note: note.trim() || undefined, sendEmail: email });
    setSending(false);
    setSent(esc);
  };

  return (
    <>
      <header className="flex items-start justify-between gap-3 border-b border-line-soft px-5 py-4">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 flex size-9 items-center justify-center rounded-xl bg-review-600 text-white">
            <UserRoundCheck className="size-5" aria-hidden />
          </span>
          <div>
            <Dialog.Title className="text-15 font-semibold text-ink">{sent ? "Escalation sent" : draft.title}</Dialog.Title>
            <p className="text-xs text-ink-3">Human-in-the-loop decision · the agent will not act until a person decides</p>
          </div>
        </div>
        <button onClick={onClose} className="rounded-md p-1 text-ink-4 hover:bg-hover hover:text-ink-2" aria-label="Close">
          <X className="size-4" />
        </button>
      </header>

      <AnimatePresence mode="wait">
        {sent ? (
          <motion.div key="sent" initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex-1 overflow-y-auto px-5 py-6 scrollbar-thin">
            <div className="flex flex-col items-center text-center">
              <motion.span initial={{ scale: 0.6 }} animate={{ scale: 1 }} transition={{ type: "spring", stiffness: 300, damping: 16 }} className="flex size-14 items-center justify-center rounded-full bg-ok-50 text-ok-600 ring-8 ring-ok-50/60">
                <CircleCheck className="size-7" />
              </motion.span>
              <h3 className="mt-4 text-15 font-semibold text-ink">
                {people.supervisor.name} has been asked to decide
              </h3>
              <p className="mt-1 max-w-[40ch] text-13 text-ink-3">“{sent.question}”</p>
            </div>
            <ul className="mx-auto mt-6 max-w-[380px] space-y-2">
              {[
                { icon: Bell, text: "In-app notification delivered to the supervisor" },
                { icon: Mail, text: email ? "Email notification sent to Shift Supervisor — Demo (not sent externally)" : "Email skipped" },
                { icon: FileSearch, text: target.type === "shipment" ? "Case timeline updated" : "Incident timeline updated" },
                { icon: UserRoundCheck, text: target.type === "shipment" ? "Status → Awaiting supervisor" : "Incident owner notified" },
              ].map((row, i) => (
                <motion.li key={row.text} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15 + i * 0.12 }} className="flex items-center gap-2.5 rounded-lg border border-line-soft px-3 py-2 text-13 text-ink-2">
                  <Check className="size-4 shrink-0 text-ok-600" aria-hidden />
                  <row.icon className="size-4 shrink-0 text-ink-4" aria-hidden />
                  {row.text}
                </motion.li>
              ))}
            </ul>
            <div className="mt-6 flex justify-center gap-2">
              {sent.emailId ? (
                <Button variant="secondary" onClick={() => set({ emailPreviewId: sent.emailId ?? null })}>
                  <Mail /> Preview email
                </Button>
              ) : null}
              <Button variant="primary" onClick={onClose}>
                Done
              </Button>
            </div>
          </motion.div>
        ) : (
          <motion.div key="form" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex min-h-0 flex-1 flex-col">
            <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4 scrollbar-thin">
              <div className="flex items-center gap-3 rounded-xl border border-line bg-subtle p-3">
                <Avatar initials={people.supervisor.initials} tone="review" size={36} />
                <div className="min-w-0 flex-1">
                  <div className="text-2xs text-ink-4">To</div>
                  <div className="text-13 font-semibold text-ink">
                    {people.supervisor.name} · {people.supervisor.role}
                  </div>
                  <div className="truncate text-xs text-ink-3">{people.supervisor.email} · on duty until 20:00</div>
                </div>
                <PriorityBadge priority={draft.priority} />
              </div>

              <Section title="Summary">
                <dl className="divide-y divide-line-soft rounded-lg border border-line-soft">
                  {draft.summary.map((row) => (
                    <div key={row.label} className="grid grid-cols-[92px_1fr] gap-3 px-3 py-2 text-xs">
                      <dt className="text-ink-4">{row.label}</dt>
                      <dd className="text-ink-2">{row.value}</dd>
                    </div>
                  ))}
                </dl>
                <div className="mt-2 grid grid-cols-2 gap-2 text-xs">
                  <div className="flex items-start gap-1.5 rounded-lg bg-warn-50 px-2.5 py-2 text-warn-700">
                    <Clock3 className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {draft.urgency}
                  </div>
                  <div className="flex items-start gap-1.5 rounded-lg bg-subtle px-2.5 py-2 text-ink-2">
                    <MapPin className="mt-0.5 size-3.5 shrink-0 text-ink-4" aria-hidden /> {draft.location}
                  </div>
                </div>
              </Section>

              <Section title="Why the agent escalated">
                <p className="text-13 leading-5 text-ink-2">{draft.reason}</p>
              </Section>

              <Section title="Unresolved question">
                <p className="rounded-lg border border-review-200 bg-review-50 px-3 py-2 text-13 font-medium text-review-700">“{draft.question}”</p>
              </Section>

              <div className="grid gap-5 sm:grid-cols-2">
                <Section title="What the agent checked">
                  <ul className="space-y-1">
                    {draft.checks.map((c) => (
                      <li key={c} className="flex items-start gap-1.5 text-xs text-ink-2">
                        <Check className="mt-0.5 size-3.5 shrink-0 text-ok-600" aria-hidden /> {c}
                      </li>
                    ))}
                  </ul>
                </Section>
                <Section title="Supporting evidence">
                  <ul className="space-y-1.5">
                    {draft.evidence.map((e) => (
                      <li key={e} className="text-xs text-ink-2">
                        <span className="mr-1 text-ink-4">•</span>
                        {e}
                      </li>
                    ))}
                  </ul>
                </Section>
              </div>

              <Section title="Options for the supervisor">
                <ol className="space-y-1.5">
                  {draft.options.map((o, i) => (
                    <li key={o} className={cn("flex items-start gap-2 rounded-lg px-3 py-2 text-13", i === 0 ? "border border-brand-200 bg-brand-25 text-ink" : "border border-line-soft text-ink-2")}>
                      <span className={cn("mt-px flex size-5 shrink-0 items-center justify-center rounded-full text-2xs font-semibold", i === 0 ? "bg-brand-600 text-white" : "bg-muted text-ink-3")}>{i + 1}</span>
                      {o}
                      {i === 0 ? <span className="ml-auto shrink-0 text-2xs font-semibold text-brand-700">Suggested</span> : null}
                    </li>
                  ))}
                </ol>
              </Section>

              <Section title="Operator note (optional)">
                <label className="sr-only" htmlFor="op-note">
                  Operator note
                </label>
                <div className="relative">
                  <MessageSquareText className="absolute top-2.5 left-2.5 size-4 text-ink-4" aria-hidden />
                  <textarea
                    id="op-note"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    rows={3}
                    placeholder="e.g. Recipient called the hotline at 15:20 and is still available until 18:00."
                    className="w-full resize-none rounded-lg border border-line bg-surface py-2 pr-3 pl-8 text-13 text-ink outline-none placeholder:text-ink-4 focus:border-brand-300 focus:ring-2 focus:ring-brand-100"
                  />
                </div>
              </Section>
            </div>

            <footer className="border-t border-line-soft bg-subtle px-5 py-3">
              <div className="mb-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-2">
                <span className="flex items-center gap-1.5">
                  <Check className="size-3.5 text-ok-600" /> In-app notification
                </span>
                <label className="flex cursor-pointer items-center gap-1.5">
                  <input type="checkbox" checked={email} onChange={(e) => setEmail(e.target.checked)} className="size-3.5 accent-brand-600" /> Email the supervisor
                </label>
                <SimTag label="demo email" tip="Email is simulated: a preview is generated and nothing is sent outside this browser." />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={onClose}>
                  Cancel
                </Button>
                <Button variant="review" onClick={send} loading={sending}>
                  <Send /> Send escalation
                </Button>
              </div>
            </footer>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="mb-1.5 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">{title}</h3>
      {children}
    </section>
  );
}
