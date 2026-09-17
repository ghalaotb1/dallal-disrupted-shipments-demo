"use client";

import { Popover, Switch } from "radix-ui";
import { Check, Clapperboard, Pause, Play, RotateCcw, SkipForward } from "lucide-react";
import { cn } from "@/lib/cn";
import { at, DEMO_TIME_SCALE, fmtDate, fmtTime } from "@/lib/time";
import { useDemoNow } from "@/hooks/useDemoNow";
import { nextBeat, resetScenario, setAutoplay, setRunning } from "@/simulation/engine";
import { BEATS, STORY_STEPS } from "@/simulation/scenario";
import { useWorld } from "@/store/world";
import { Button } from "@/components/common/Button";

export function DemoClock() {
  const now = useDemoNow(1000);
  const running = useWorld((w) => w.clock.running);
  const scenario = useWorld((w) => w.scenario);
  const done = STORY_STEPS.filter((s) => scenario.completedSteps.includes(s.id)).length;
  const pending = BEATS.filter((b) => !scenario.firedBeats.includes(b.id));
  // The scenario clock runs fast; after a long unattended session, nudge toward a fresh run.
  const shiftEnding = now >= at("19:30");

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          className="group flex h-9 items-center gap-2.5 rounded-lg border border-line bg-surface pr-2.5 pl-2 text-left transition-colors hover:border-line-strong hover:bg-hover data-[state=open]:border-brand-300 data-[state=open]:bg-brand-25"
          aria-label="Demo controls and scenario clock"
        >
          <span className={cn("relative flex size-2", running ? "" : "opacity-60")} aria-hidden>
            {running ? <span className="absolute inline-flex size-full animate-ping rounded-full bg-ok-500 opacity-60" /> : null}
            <span className={cn("relative inline-flex size-2 rounded-full", running ? "bg-ok-500" : "bg-ink-4")} />
          </span>
          <span className="flex flex-col leading-none">
            <span className="text-15 font-semibold text-ink tabular">{fmtTime(now)}</span>
            <span className="mt-0.5 text-[10.5px] whitespace-nowrap text-ink-3">{fmtDate(now)}</span>
          </span>
          <span className={cn("ml-0.5 rounded-md px-1.5 py-0.5 text-2xs font-semibold whitespace-nowrap", shiftEnding ? "bg-warn-100 text-warn-700" : "bg-muted text-ink-2 group-hover:bg-line-soft")}>
            {shiftEnding ? "Shift ending · restart demo" : running ? `Live demo · ×${DEMO_TIME_SCALE}` : "Paused"}
          </span>
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="end" sideOffset={8} className="z-[70] w-[360px] rounded-xl border border-line bg-surface p-0 shadow-pop outline-none">
          <div className="flex items-start gap-2.5 border-b border-line-soft px-4 py-3">
            <span className="mt-0.5 flex size-7 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
              <Clapperboard className="size-4" />
            </span>
            <div>
              <div className="text-sm font-semibold">Demo director</div>
              <p className="text-xs text-ink-3">Simulated Eastern Region scenario. The operations clock runs at {DEMO_TIME_SCALE}× speed.</p>
            </div>
          </div>
          <ol className="max-h-[320px] space-y-0.5 overflow-auto px-2 py-2">
            {STORY_STEPS.map((step, i) => {
              const complete = scenario.completedSteps.includes(step.id);
              const current = !complete && STORY_STEPS.slice(0, i).every((s) => scenario.completedSteps.includes(s.id));
              return (
                <li key={step.id} className={cn("flex items-start gap-2.5 rounded-lg px-2 py-1.5", current && "bg-brand-25")}>
                  <span
                    className={cn(
                      "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-2xs font-semibold",
                      complete ? "bg-ok-500 text-white" : current ? "bg-brand-600 text-white" : "bg-muted text-ink-3",
                    )}
                  >
                    {complete ? <Check className="size-3" strokeWidth={3} /> : i + 1}
                  </span>
                  <span className="min-w-0">
                    <span className={cn("block text-13 font-medium", complete ? "text-ink-3" : "text-ink")}>{step.title}</span>
                    <span className="block text-xs text-ink-4">{step.hint}</span>
                  </span>
                </li>
              );
            })}
          </ol>
          <div className="space-y-3 border-t border-line-soft px-4 py-3">
            <div className="flex items-center justify-between">
              <label htmlFor="autoplay" className="text-13 text-ink-2">
                Auto-play world events
                <span className="block text-xs text-ink-4">{pending.length ? `Next: ${pending[0].title}` : "All scripted events have fired"}</span>
              </label>
              <Switch.Root
                id="autoplay"
                checked={scenario.autoplay}
                onCheckedChange={setAutoplay}
                className="relative h-5 w-9 shrink-0 rounded-full bg-line-strong transition-colors data-[state=checked]:bg-brand-600"
              >
                <Switch.Thumb className="block size-4 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
              </Switch.Root>
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="primary" className="flex-1" onClick={nextBeat} disabled={!pending.length}>
                <SkipForward /> Next event
              </Button>
              <Button size="sm" onClick={() => setRunning(!useWorld.getState().clock.running)}>
                {running ? <Pause /> : <Play />}
                {running ? "Pause" : "Resume"}
              </Button>
              <Button size="sm" variant="ghost" onClick={resetScenario} aria-label="Restart scenario">
                <RotateCcw /> Restart
              </Button>
            </div>
            <p className="text-2xs text-ink-4">
              {done} of {STORY_STEPS.length} story steps complete · append <code className="font-mono">?demo=manual</code> to start without auto-play.
            </p>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
