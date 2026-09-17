"use client";

import type { ReactNode } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopBar } from "@/components/layout/TopBar";
import { Toaster } from "@/components/layout/Toaster";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { GroupResponseDialog } from "@/components/incidents/GroupResponseDialog";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh">
      <a href="#main" className="sr-only z-[100] rounded-lg bg-brand-600 px-3 py-2 text-white focus:not-sr-only focus:fixed focus:top-2 focus:left-2">
        Skip to content
      </a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main id="main" className="flex min-h-0 flex-1 flex-col">
          {children}
        </main>
      </div>
      <CommandPalette />
      <GroupResponseDialog />
      <Toaster />
    </div>
  );
}
