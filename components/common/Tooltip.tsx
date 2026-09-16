"use client";

import { Tooltip as T } from "radix-ui";
import type { ReactNode } from "react";

export function TooltipProvider({ children }: { children: ReactNode }) {
  return (
    <T.Provider delayDuration={250} skipDelayDuration={150}>
      {children}
    </T.Provider>
  );
}

export function Tooltip({ content, children, side = "top", align = "center" }: { content: ReactNode; children: ReactNode; side?: "top" | "bottom" | "left" | "right"; align?: "start" | "center" | "end" }) {
  if (!content) return <>{children}</>;
  return (
    <T.Root>
      <T.Trigger asChild>{children}</T.Trigger>
      <T.Portal>
        <T.Content
          side={side}
          align={align}
          sideOffset={6}
          collisionPadding={8}
          className="z-[80] max-w-72 rounded-lg bg-ink px-2.5 py-1.5 text-xs leading-snug text-white shadow-pop"
        >
          {content}
        </T.Content>
      </T.Portal>
    </T.Root>
  );
}
