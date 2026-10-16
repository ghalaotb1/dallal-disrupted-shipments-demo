"use client";

import { cn } from "@/lib/cn";
import { Tooltip } from "@/components/common/Tooltip";

/** Marks values that came from the real backend, so they are never confused with the in-browser prototype. */
export function LiveTag({ className, label = "LIVE", tip }: { className?: string; label?: string; tip?: string }) {
  return (
    <Tooltip content={tip ?? "Produced by the Dallal backend (decision engine, belief state, tools). The shipment world itself is still simulated."}>
      <span className={cn("inline-flex h-4 cursor-help items-center gap-1 rounded bg-ok-50 px-1 font-mono text-[9.5px] font-semibold tracking-wide text-ok-700 uppercase ring-1 ring-ok-200", className)}>
        <span className="size-1.5 rounded-full bg-ok-500" aria-hidden />
        {label}
      </span>
    </Tooltip>
  );
}

export function SandboxTag({ className }: { className?: string }) {
  return (
    <Tooltip content="WhatsApp SANDBOX: messages follow the real Cloud API format and rules, but nothing is sent to any phone. Replies are typed by a person on the simulated recipient device.">
      <span className={cn("inline-flex h-4 cursor-help items-center rounded bg-warn-50 px-1 font-mono text-[9.5px] font-semibold tracking-wide text-warn-700 uppercase ring-1 ring-warn-200", className)}>Sandbox</span>
    </Tooltip>
  );
}
