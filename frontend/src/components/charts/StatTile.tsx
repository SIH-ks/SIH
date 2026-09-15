import type { LucideIcon } from "lucide-react";
import { TrendingDown, TrendingUp } from "lucide-react";

import { cn } from "@/lib/format";

/**
 * A single headline number.
 *
 * The most common charting mistake is drawing eight coloured bars when the story
 * is one figure — so the console's KPI row is stat tiles, not mini charts. The
 * accent stripe is chrome, not an encoding: it groups tiles visually and carries
 * no value, which is why the number itself always stays in ink and never takes
 * the accent's colour.
 */

type Accent = "navy" | "good" | "warning" | "critical" | "series";

const ACCENT_BAR: Record<Accent, string> = {
  navy: "bg-brand-navy dark:bg-series-1",
  good: "bg-status-good",
  warning: "bg-status-warning",
  critical: "bg-status-critical",
  series: "bg-series-1",
};

const ACCENT_ICON: Record<Accent, string> = {
  navy: "bg-brand-navy/8 text-brand-navy dark:bg-series-1/15 dark:text-series-1",
  good: "bg-status-good-wash text-status-good-ink",
  warning: "bg-status-warning-wash text-status-warning-ink",
  critical: "bg-status-critical-wash text-status-critical-ink",
  series: "bg-series-1/10 text-series-1",
};

export function StatTile({
  label,
  value,
  suffix,
  hint,
  icon: Icon,
  accent = "navy",
  delta,
  deltaGoodWhen = "up",
  footer,
  className,
}: {
  label: string;
  value: string | number;
  suffix?: string;
  hint?: string;
  icon?: LucideIcon;
  accent?: Accent;
  delta?: number | null;
  /** Which direction is the good one. "Flagged records fell 12%" is good news;
   * "throughput fell 12%" is not, and the same arrow must not imply both. */
  deltaGoodWhen?: "up" | "down";
  footer?: React.ReactNode;
  className?: string;
}) {
  const showDelta = delta !== undefined && delta !== null && Number.isFinite(delta) && delta !== 0;
  const rising = (delta ?? 0) > 0;
  const good = deltaGoodWhen === "up" ? rising : !rising;
  const DeltaIcon = rising ? TrendingUp : TrendingDown;

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-xl border border-line bg-surface-card px-4 py-3.5 shadow-card",
        className,
      )}
    >
      <span className={cn("absolute inset-y-0 left-0 w-[3px]", ACCENT_BAR[accent])} aria-hidden />

      <div className="flex items-start justify-between gap-3 pl-1.5">
        <div className="min-w-0">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">{label}</p>
          <p className="mt-1.5 flex items-baseline gap-1">
            <span className="text-[26px] font-bold leading-none tracking-tight text-ink-primary">{value}</span>
            {suffix && <span className="text-sm font-semibold text-ink-secondary">{suffix}</span>}
          </p>
          {hint && <p className="mt-1.5 text-xs leading-snug text-ink-muted">{hint}</p>}
        </div>

        {Icon && (
          <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", ACCENT_ICON[accent])}>
            <Icon className="h-4 w-4" strokeWidth={2} aria-hidden />
          </div>
        )}
      </div>

      {(showDelta || footer) && (
        <div className="mt-3 flex items-center gap-2 border-t border-line pl-1.5 pt-2.5 text-xs">
          {showDelta && (
            <span
              className={cn(
                "inline-flex items-center gap-1 font-semibold",
                good ? "text-status-good-ink" : "text-status-critical-ink",
              )}
            >
              <DeltaIcon className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden />
              {Math.abs(delta ?? 0).toFixed(1)}%
            </span>
          )}
          {footer && <span className="truncate text-ink-muted">{footer}</span>}
        </div>
      )}
    </div>
  );
}
