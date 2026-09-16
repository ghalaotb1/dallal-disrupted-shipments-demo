import { cn } from "@/lib/cn";

export function LogoMark({ size = 30, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 30 30" className={className} aria-hidden>
      <rect width="30" height="30" rx="8.5" fill="#2358d1" />
      <path d="M8.5 21c0-3.4 2.4-5 5.6-5h1.8c3.2 0 5.6-1.6 5.6-5" stroke="#fff" strokeWidth="2.3" strokeLinecap="round" fill="none" />
      <circle cx="8.5" cy="21" r="2.3" fill="#fff" />
      <circle cx="21.5" cy="10" r="2.6" fill="#2358d1" stroke="#fff" strokeWidth="2.1" />
    </svg>
  );
}

export function Wordmark({ collapsed, className }: { collapsed?: boolean; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <LogoMark />
      {collapsed ? null : (
        <div className="flex flex-col leading-none">
          <span lang="ar" dir="rtl" className="font-arabic text-[21px] font-semibold text-ink">
            دلّال
          </span>
          <span className="mt-1 text-[10px] font-semibold tracking-[0.18em] text-ink-4 uppercase">Dallal</span>
        </div>
      )}
    </div>
  );
}
