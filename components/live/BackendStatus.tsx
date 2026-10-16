"use client";

import { Cable, CircleOff } from "lucide-react";
import { cn } from "@/lib/cn";
import { useLive } from "@/store/live";
import { Tooltip } from "@/components/common/Tooltip";

/** Top-bar indicator: is the real backend driving decisions, or is the app running on the in-browser prototype? */
export function BackendStatus() {
  const status = useLive((s) => s.status);
  const meta = useLive((s) => s.meta);
  const connected = status === "connected";
  return (
    <Tooltip
      content={
        connected ? (
          <span className="block max-w-[260px] text-xs leading-4">
            Live backend connected · engine {meta?.engine} · policy {meta?.policy} · WhatsApp {meta?.whatsapp_mode}. {meta?.notice} Shipments, vehicles and roads are still simulated.
          </span>
        ) : (
          <span className="block max-w-[260px] text-xs leading-4">No backend reachable: agent decisions come from the in-browser prototype planner and are simulated. Add ?backend=URL to connect.</span>
        )
      }
      side="bottom"
    >
      <span
        className={cn(
          "hidden h-8 cursor-help items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium ring-1 ring-inset md:inline-flex",
          connected ? "bg-ok-50 text-ok-700 ring-ok-200" : "bg-subtle text-ink-3 ring-line",
        )}
        role="status"
        aria-label={connected ? "Live backend connected" : "Simulated, no backend"}
      >
        {connected ? <Cable className="size-3.5" aria-hidden /> : <CircleOff className="size-3.5" aria-hidden />}
        {connected ? (
          <>
            Live backend
            {meta?.whatsapp_mode === "sandbox" ? <span className="rounded bg-warn-50 px-1 text-[9.5px] font-semibold text-warn-700 uppercase">WA sandbox</span> : null}
          </>
        ) : (
          "Simulated"
        )}
      </span>
    </Tooltip>
  );
}
