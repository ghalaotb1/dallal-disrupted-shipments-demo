"use client";

import { forwardRef, type ButtonHTMLAttributes } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "secondary" | "ghost" | "soft" | "danger" | "review" | "dark";
type Size = "xs" | "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-600 text-white shadow-[0_1px_0_rgb(255_255_255/0.15)_inset,0_1px_2px_rgb(15_30_54/0.2)] hover:bg-brand-700 active:bg-brand-800",
  secondary: "bg-surface text-ink ring-1 ring-inset ring-line-strong hover:bg-hover hover:ring-ink-5 active:bg-muted",
  ghost: "text-ink-2 hover:bg-hover hover:text-ink active:bg-muted",
  soft: "bg-brand-50 text-brand-700 hover:bg-brand-100 active:bg-brand-200",
  danger: "bg-crit-600 text-white hover:bg-crit-700",
  review: "bg-review-600 text-white shadow-[0_1px_2px_rgb(15_30_54/0.2)] hover:bg-review-700",
  dark: "bg-ink text-white hover:bg-ink-2",
};
const SIZES: Record<Size, string> = {
  xs: "h-7 gap-1.5 rounded-md px-2 text-xs",
  sm: "h-8 gap-1.5 rounded-lg px-2.5 text-13",
  md: "h-9 gap-2 rounded-lg px-3.5 text-13",
  lg: "h-10 gap-2 rounded-lg px-4 text-sm",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, className, children, disabled, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(
        "inline-flex shrink-0 items-center justify-center font-medium whitespace-nowrap transition-[background-color,box-shadow,color] duration-150 select-none disabled:opacity-55 [&_svg]:size-4 [&_svg]:shrink-0",
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <Loader2 className="animate-spin" aria-hidden /> : null}
      {children}
    </button>
  );
});

export function IconButton({ label, className, children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      aria-label={label}
      title={label}
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-lg text-ink-3 transition-colors hover:bg-hover hover:text-ink active:bg-muted [&_svg]:size-[18px]",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
