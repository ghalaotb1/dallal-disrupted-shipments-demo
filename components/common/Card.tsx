import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-xl border border-line bg-surface shadow-card", className)} {...props} />;
}

export function CardHeader({ title, subtitle, icon, actions, className }: { title: ReactNode; subtitle?: ReactNode; icon?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-start justify-between gap-3 px-4 pt-3.5 pb-2.5", className)}>
      <div className="flex min-w-0 items-start gap-2.5">
        {icon ? <span className="mt-px text-ink-3 [&_svg]:size-4">{icon}</span> : null}
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          {subtitle ? <p className="mt-0.5 text-xs text-ink-3">{subtitle}</p> : null}
        </div>
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-1.5">{actions}</div> : null}
    </div>
  );
}

export function SectionLabel({ children, className, count }: { children: ReactNode; className?: string; count?: number }) {
  return (
    <div className={cn("flex items-center gap-2 text-2xs font-semibold tracking-[0.06em] text-ink-4 uppercase", className)}>
      {children}
      {count !== undefined ? <span className="rounded bg-muted px-1 font-mono tracking-normal text-ink-3 tabular">{count}</span> : null}
    </div>
  );
}

export function EmptyState({ icon, title, body, action, className }: { icon?: ReactNode; title: string; body?: string; action?: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-10 text-center", className)}>
      {icon ? <div className="mb-3 flex size-10 items-center justify-center rounded-full bg-muted text-ink-4 [&_svg]:size-5">{icon}</div> : null}
      <p className="text-13 font-medium text-ink-2">{title}</p>
      {body ? <p className="mt-1 max-w-72 text-xs text-ink-3">{body}</p> : null}
      {action ? <div className="mt-3">{action}</div> : null}
    </div>
  );
}

export function Avatar({ initials, tone = "brand", size = 28, className }: { initials: string; tone?: "brand" | "review" | "ink"; size?: number; className?: string }) {
  const toneCls = tone === "review" ? "bg-review-100 text-review-700" : tone === "ink" ? "bg-ink text-white" : "bg-brand-100 text-brand-800";
  return (
    <span className={cn("inline-flex shrink-0 items-center justify-center rounded-full font-semibold", toneCls, className)} style={{ width: size, height: size, fontSize: size * 0.4 }} aria-hidden>
      {initials}
    </span>
  );
}
