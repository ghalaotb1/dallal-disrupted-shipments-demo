"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useRouter } from "next/navigation";
import { Popover } from "radix-ui";
import { Bell } from "lucide-react";
import { useDemoNow } from "@/hooks/useDemoNow";
import { notificationService } from "@/services";
import { useUi } from "@/store/ui";
import { useWorld } from "@/store/world";
import { hrefFor, NotificationItem } from "@/components/notifications/NotificationItem";

export function NotificationBell() {
  const router = useRouter();
  const raw = useWorld((w) => w.notifications);
  const notifications = useMemo(() => [...raw].sort((a, b) => b.at - a.at), [raw]);
  const open = useUi((s) => s.notificationsOpen);
  const set = useUi((s) => s.set);
  const now = useDemoNow(15_000);
  const unread = notifications.filter((n) => !n.read).length;

  return (
    <Popover.Root open={open} onOpenChange={(o) => set({ notificationsOpen: o })}>
      <Popover.Trigger asChild>
        <button className="relative flex size-9 items-center justify-center rounded-lg text-ink-2 transition-colors hover:bg-hover data-[state=open]:bg-brand-50 data-[state=open]:text-brand-700" aria-label={`Notifications, ${unread} unread`}>
          <Bell className="size-[18px]" />
          {unread ? (
            <span className="absolute top-1 right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-crit-600 px-1 text-[10px] font-semibold text-white tabular ring-2 ring-surface">{unread}</span>
          ) : null}
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="end" sideOffset={8} className="z-[70] w-[400px] rounded-xl border border-line bg-surface shadow-pop outline-none">
          <div className="flex items-center justify-between border-b border-line-soft px-4 py-3">
            <div className="text-sm font-semibold">
              Notifications {unread ? <span className="ml-1 text-ink-3">· {unread} new</span> : null}
            </div>
            <button onClick={() => notificationService.markAllRead()} className="text-xs font-medium text-brand-700 hover:underline disabled:opacity-40" disabled={!unread}>
              Mark all read
            </button>
          </div>
          <div className="max-h-[420px] overflow-auto p-1.5 scrollbar-thin">
            {notifications.slice(0, 7).map((n) => (
              <NotificationItem
                key={n.id}
                n={n}
                now={now}
                onClick={() => {
                  notificationService.markRead(n.id);
                  set({ notificationsOpen: false });
                  router.push(hrefFor(n));
                }}
              />
            ))}
          </div>
          <div className="border-t border-line-soft px-4 py-2.5 text-center">
            <Link href="/notifications" onClick={() => set({ notificationsOpen: false })} className="text-13 font-medium text-brand-700 hover:underline">
              View all notifications & email log
            </Link>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
