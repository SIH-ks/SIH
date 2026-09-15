import Link from "next/link";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/format";

/**
 * The small set of shapes every page is built from: a card, a section header, a
 * button, an empty state, an error panel. Defined once so a console assembled
 * from a dozen pages still reads as one product.
 */

// ---------------------------------------------------------------------------

export function Card({
  className,
  children,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-xl border border-line bg-surface-card shadow-card",
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  icon: Icon,
  action,
  className,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  icon?: LucideIcon;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-3 border-b border-line px-4 py-3", className)}>
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-ink-primary">
          {Icon && <Icon className="h-4 w-4 text-ink-muted" strokeWidth={2} aria-hidden />}
          {title}
        </h2>
        {subtitle && <p className="mt-0.5 text-xs text-ink-muted">{subtitle}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------

export function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  breadcrumb?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {breadcrumb}
        <h1 className="text-[22px] font-bold tracking-tight text-ink-primary">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-ink-secondary">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
type ButtonSize = "sm" | "md";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-brand-navy text-white hover:bg-brand-navy/90 disabled:bg-brand-navy/50 dark:bg-series-1 dark:hover:bg-series-1/90",
  secondary:
    "border border-line-strong bg-surface-card text-ink-primary hover:bg-surface-sunken disabled:opacity-50",
  ghost: "text-ink-secondary hover:bg-surface-sunken hover:text-ink-primary disabled:opacity-50",
  danger:
    "border border-status-critical/40 bg-status-critical-wash text-status-critical-ink hover:bg-status-critical/15 disabled:opacity-50",
  subtle: "bg-surface-sunken text-ink-secondary hover:bg-line-hairline disabled:opacity-50",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 px-3 text-xs",
  md: "h-9 gap-2 px-4 text-sm",
};

const BUTTON_BASE =
  "inline-flex items-center justify-center rounded-lg font-semibold transition-colors disabled:cursor-not-allowed";

export function Button({
  variant = "secondary",
  size = "md",
  icon: Icon,
  className,
  children,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: LucideIcon;
}) {
  return (
    <button className={cn(BUTTON_BASE, VARIANTS[variant], SIZES[size], className)} {...rest}>
      {Icon && <Icon className={size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4"} strokeWidth={2} aria-hidden />}
      {children}
    </button>
  );
}

export function LinkButton({
  href,
  variant = "secondary",
  size = "md",
  icon: Icon,
  className,
  children,
  external,
  ...rest
}: {
  href: string;
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: LucideIcon;
  className?: string;
  children: React.ReactNode;
  external?: boolean;
} & Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "href">) {
  const content = (
    <>
      {Icon && <Icon className={size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4"} strokeWidth={2} aria-hidden />}
      {children}
    </>
  );
  const classes = cn(BUTTON_BASE, VARIANTS[variant], SIZES[size], className);

  // Downloads and print views open outside the SPA: routing them through
  // `next/link` would prefetch a file response the router cannot render.
  if (external) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={classes} {...rest}>
        {content}
      </a>
    );
  }
  return (
    <Link href={href} className={classes} {...rest}>
      {content}
    </Link>
  );
}

// ---------------------------------------------------------------------------

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center px-6 py-14 text-center", className)}>
      {Icon && (
        <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-surface-sunken">
          <Icon className="h-5 w-5 text-ink-muted" strokeWidth={1.8} aria-hidden />
        </div>
      )}
      <p className="text-sm font-semibold text-ink-primary">{title}</p>
      {description && <p className="mt-1 max-w-md text-sm text-ink-muted">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/**
 * A failed panel, stated plainly.
 *
 * Every server-side reader returns `{ error }` instead of throwing (see
 * `lib/api.ts`), so one panel failing degrades that panel and leaves the rest of
 * the page working. This is what that degradation looks like — including the
 * distinction between "the API refused this" and "the API is not running", which
 * need different actions from whoever is reading.
 */
export function ErrorPanel({
  message,
  unreachable,
  className,
}: {
  message: string;
  unreachable?: boolean;
  className?: string;
}) {
  return (
    <div
      role="status"
      className={cn(
        "rounded-xl border px-4 py-3 text-sm",
        unreachable
          ? "border-status-warning/40 bg-status-warning-wash text-status-warning-ink"
          : "border-status-critical/40 bg-status-critical-wash text-status-critical-ink",
        className,
      )}
    >
      <p className="font-semibold">{unreachable ? "Backend unavailable" : "Could not load this panel"}</p>
      <p className="mt-0.5 opacity-90">{message}</p>
      {unreachable && (
        <p className="mt-1.5 font-mono text-xs opacity-80">
          cd backend &amp;&amp; uvicorn app.main:app --reload
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

/** A labelled value. The console's most repeated shape — an identity strip, a
 * detail grid, a summary row are all stacks of these. */
export function Field({
  label,
  value,
  mono,
  className,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  className?: string;
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <dt className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">{label}</dt>
      <dd
        className={cn(
          "mt-0.5 truncate text-sm font-semibold text-ink-primary",
          mono && "font-mono text-[13px] font-medium",
        )}
      >
        {value ?? "—"}
      </dd>
    </div>
  );
}

/** A horizontal confidence meter. Paired with its numeric value always — the bar
 * alone would make 62% and 68% indistinguishable at this width. */
export function ConfidenceMeter({ value, width = "w-16" }: { value: number | null; width?: string }) {
  if (value === null) return <span className="text-xs text-ink-muted">—</span>;
  const percent = Math.round(value * 100);
  const tone =
    value >= 0.85 ? "bg-status-good" : value >= 0.6 ? "bg-status-warning" : "bg-status-critical";
  return (
    <div className="flex items-center gap-2">
      <div className={cn("h-1.5 overflow-hidden rounded-full bg-surface-sunken", width)}>
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${percent}%` }} />
      </div>
      <span className="font-mono text-xs tabular-nums text-ink-secondary">{percent}%</span>
    </div>
  );
}
