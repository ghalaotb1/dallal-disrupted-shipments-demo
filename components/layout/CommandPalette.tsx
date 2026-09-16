"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Dialog } from "radix-ui";
import { CornerDownLeft, MapPin, Package, Search, Siren, Sparkles } from "lucide-react";
import { cn } from "@/lib/cn";
import { shipmentService } from "@/services";
import { SUGGESTED_PROMPTS } from "@/services/demo/assistantService";
import { focusMap, useUi } from "@/store/ui";
import { useWorld } from "@/store/world";
import { askAssistant } from "@/components/assistant/askAssistant";
import { StatusBadge } from "@/components/common/Badges";

type Item = { key: string; icon: typeof Package; title: string; subtitle: string; run: () => void; health?: string };

export function CommandPalette() {
  const router = useRouter();
  const open = useUi((s) => s.commandOpen);
  const set = useUi((s) => s.set);
  const shipments = useWorld((w) => w.shipments);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        set({ commandOpen: !useUi.getState().commandOpen });
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        set({ assistantOpen: !useUi.getState().assistantOpen });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [set]);

  const close = () => {
    set({ commandOpen: false });
    setQ("");
    setActive(0);
  };

  const items = useMemo<Item[]>(() => {
    const text = q.trim();
    if (!text) {
      return SUGGESTED_PROMPTS.slice(0, 5).map((p) => ({
        key: p,
        icon: Sparkles,
        title: p,
        subtitle: "Ask Dallal",
        run: () => askAssistant(p),
      }));
    }
    const hits = shipmentService.search(text).map<Item>((h) => ({
      key: `${h.type}-${h.id}`,
      icon: h.type === "shipment" ? Package : h.type === "incident" ? Siren : MapPin,
      title: h.title,
      subtitle: h.subtitle,
      health: h.type === "shipment" ? shipments[h.id]?.health : undefined,
      run: () => {
        if (h.href) router.push(h.href);
        else if (h.type === "place") router.push("/");
        if (h.type === "shipment") focusMap({ kind: "shipment", id: h.id });
      },
    }));
    return [
      ...hits,
      { key: "ask", icon: Sparkles, title: `Ask Dallal: “${text}”`, subtitle: "Answer from live operations data", run: () => askAssistant(text) },
    ];
  }, [q, router, shipments]);

  const choose = (i: number) => {
    const item = items[i];
    if (!item) return;
    close();
    item.run();
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => (o ? set({ commandOpen: true }) : close())}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[90] bg-ink/25 backdrop-blur-[2px]" />
        <Dialog.Content className="fixed top-[12vh] left-1/2 z-[91] w-[620px] max-w-[calc(100vw-32px)] -translate-x-1/2 overflow-hidden rounded-2xl border border-line bg-surface shadow-pop outline-none">
          <Dialog.Title className="sr-only">Search Dallal</Dialog.Title>
          <Dialog.Description className="sr-only">Search shipments, incidents and places, or ask the assistant a question.</Dialog.Description>
          <div className="flex items-center gap-2.5 border-b border-line px-4">
            <Search className="size-[18px] text-ink-4" aria-hidden />
            <input
              autoFocus
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setActive(0);
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown") {
                  e.preventDefault();
                  setActive((a) => Math.min(items.length - 1, a + 1));
                } else if (e.key === "ArrowUp") {
                  e.preventDefault();
                  setActive((a) => Math.max(0, a - 1));
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  choose(active);
                }
              }}
              placeholder="Shipment ID, district, incident, or a question…"
              className="h-14 flex-1 bg-transparent text-15 text-ink outline-none placeholder:text-ink-4"
              role="combobox"
              aria-expanded
              aria-controls="command-results"
              aria-activedescendant={items[active] ? `cmd-${active}` : undefined}
            />
          </div>
          <div id="command-results" role="listbox" className="max-h-[420px] overflow-auto p-2 scrollbar-thin">
            {!q ? <div className="px-2 pt-1 pb-2 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase">Try asking</div> : null}
            {items.map((item, i) => {
              const Icon = item.icon;
              return (
                <div
                  id={`cmd-${i}`}
                  key={item.key}
                  role="option"
                  aria-selected={i === active}
                  onMouseMove={() => setActive(i)}
                  onClick={() => choose(i)}
                  className={cn("flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2.5", i === active ? "bg-brand-50" : "")}
                >
                  <Icon className={cn("size-4 shrink-0", item.icon === Sparkles ? "text-brand-500" : "text-ink-3")} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-13 font-medium text-ink">{item.title}</div>
                    <div className="truncate text-xs text-ink-3">{item.subtitle}</div>
                  </div>
                  {item.health ? <StatusBadge health={item.health as never} size="xs" /> : null}
                  {i === active ? <CornerDownLeft className="size-3.5 text-ink-4" aria-hidden /> : null}
                </div>
              );
            })}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
