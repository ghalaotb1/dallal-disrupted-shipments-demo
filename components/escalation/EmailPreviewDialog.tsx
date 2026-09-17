"use client";

import { useRouter } from "next/navigation";
import { Dialog } from "radix-ui";
import { Info, Mail, X } from "lucide-react";
import { fmtDate, fmtTime } from "@/lib/time";
import { useUi } from "@/store/ui";
import { useWorld } from "@/store/world";
import { LogoMark } from "@/components/layout/Logo";

/** Renders a simulated notification email the way the supervisor would receive it. Nothing is sent. */
export function EmailPreviewDialog() {
  const router = useRouter();
  const id = useUi((s) => s.emailPreviewId);
  const set = useUi((s) => s.set);
  const email = useWorld((w) => (id ? w.emails[id] : undefined));
  const close = () => set({ emailPreviewId: null });

  return (
    <Dialog.Root open={!!id && !!email} onOpenChange={(o) => (!o ? close() : null)}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[95] bg-ink/30 backdrop-blur-[2px]" />
        <Dialog.Content className="fixed top-1/2 left-1/2 z-[96] flex max-h-[88vh] w-[680px] max-w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-2xl border border-line bg-canvas shadow-pop outline-none">
          {email ? (
            <>
              <div className="flex items-center justify-between gap-3 border-b border-line bg-surface px-5 py-3">
                <div className="flex items-center gap-2">
                  <Mail className="size-4 text-ink-3" aria-hidden />
                  <Dialog.Title className="text-13 font-semibold text-ink">Email preview</Dialog.Title>
                </div>
                <button onClick={close} className="rounded-md p-1 text-ink-4 hover:bg-hover" aria-label="Close email preview">
                  <X className="size-4" />
                </button>
              </div>
              <div className="flex items-center gap-2 border-b border-warn-100 bg-warn-50 px-5 py-2 text-xs text-warn-700">
                <Info className="size-3.5 shrink-0" aria-hidden />
                <Dialog.Description>Simulated email — generated for this prototype and not sent to any real mailbox.</Dialog.Description>
              </div>
              <div className="border-b border-line bg-surface px-5 py-3 text-xs">
                <div className="text-15 font-semibold text-ink">{email.subject}</div>
                <dl className="mt-2 grid grid-cols-[56px_1fr] gap-x-2 gap-y-0.5 text-ink-2">
                  <dt className="text-ink-4">From</dt>
                  <dd>{email.from}</dd>
                  <dt className="text-ink-4">To</dt>
                  <dd>{email.to}</dd>
                  {email.cc ? (
                    <>
                      <dt className="text-ink-4">Cc</dt>
                      <dd>{email.cc}</dd>
                    </>
                  ) : null}
                  <dt className="text-ink-4">Date</dt>
                  <dd>
                    {fmtDate(email.at)}, {fmtTime(email.at)} (AST)
                  </dd>
                </dl>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-5 scrollbar-thin">
                <article className="mx-auto max-w-[560px] overflow-hidden rounded-xl border border-line bg-surface">
                  <div className="flex items-center gap-2.5 border-b border-line-soft bg-brand-25 px-6 py-4">
                    <LogoMark size={26} />
                    <div className="leading-tight">
                      <div className="font-arabic text-[17px] font-semibold text-ink" lang="ar" dir="rtl">
                        دلّال
                      </div>
                      <div className="text-2xs text-ink-3">Exception desk · Eastern Region</div>
                    </div>
                    <span className="ml-auto rounded-full bg-review-100 px-2 py-0.5 text-2xs font-semibold text-review-700">Action required</span>
                  </div>
                  <div className="space-y-4 px-6 py-5 text-13 leading-6 text-ink-2">
                    <p>{email.greeting}</p>
                    <p>{email.reason}</p>
                    <table className="w-full border-collapse text-xs">
                      <tbody>
                        {email.summary.map((row) => (
                          <tr key={row.label} className="border-b border-line-soft last:border-0">
                            <td className="w-28 py-1.5 pr-3 align-top text-ink-4">{row.label}</td>
                            <td className="py-1.5 text-ink">{row.value}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {email.question ? (
                      <div className="rounded-lg border-l-[3px] border-review-500 bg-review-50 px-3 py-2">
                        <div className="text-2xs font-semibold tracking-[0.06em] text-review-700 uppercase">Decision needed</div>
                        <div className="font-medium text-ink">{email.question}</div>
                      </div>
                    ) : null}
                    <div>
                      <div className="text-xs font-semibold text-ink">Evidence</div>
                      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-xs">
                        {email.evidence.map((e) => (
                          <li key={e}>{e}</li>
                        ))}
                      </ul>
                    </div>
                    <div>
                      <div className="text-xs font-semibold text-ink">What the agent checked</div>
                      <p className="mt-0.5 text-xs">{email.checks.join(" · ")}</p>
                    </div>
                    <div>
                      <div className="text-xs font-semibold text-ink">Recommended action</div>
                      <p className="mt-0.5 text-xs">{email.recommendation}</p>
                    </div>
                    {email.operatorNote ? (
                      <div>
                        <div className="text-xs font-semibold text-ink">Note from the analyst</div>
                        <p className="mt-0.5 text-xs italic">“{email.operatorNote}”</p>
                      </div>
                    ) : null}
                    <div className="pt-1">
                      <button
                        onClick={() => {
                          close();
                          router.push(email.link.href);
                        }}
                        className="inline-flex h-10 items-center rounded-lg bg-brand-600 px-4 text-13 font-semibold text-white hover:bg-brand-700"
                      >
                        {email.link.label} →
                      </button>
                    </div>
                  </div>
                  <div className="border-t border-line-soft bg-subtle px-6 py-3 text-2xs leading-4 text-ink-4">
                    You are receiving this because you are the shift supervisor on duty for the Dammam–Khobar desk. Dallal prototype · simulated operations data.
                  </div>
                </article>
              </div>
            </>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
