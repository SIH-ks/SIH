import { cn } from "@/lib/utils";
import type { RecommendedAction, Severity } from "@/types/parcel";

/** Sharp-edged status tags — 2px radius, not pills. Uppercase monospace label,
 * colored border + tinted background, no filled solid badges (keeps the console's
 * dark surface as the dominant visual weight, tags as accents on top of it). */

const ACTION_STYLES: Record<RecommendedAction, string> = {
  auto_approve: "border-signal-green/40 bg-signal-green/10 text-signal-green",
  review_queue: "border-signal-amber/40 bg-signal-amber/10 text-signal-amber",
  field_verification: "border-signal-amber/40 bg-signal-amber/10 text-signal-amber",
  reject_re_scan: "border-signal-red/40 bg-signal-red/10 text-signal-red",
};

const ACTION_LABELS: Record<RecommendedAction, string> = {
  auto_approve: "Auto-approve",
  review_queue: "Review queue",
  field_verification: "Field verify",
  reject_re_scan: "Reject / re-scan",
};

const SEVERITY_STYLES: Record<Severity, string> = {
  info: "border-signal-cyan/40 bg-signal-cyan/10 text-signal-cyan",
  warning: "border-signal-amber/40 bg-signal-amber/10 text-signal-amber",
  error: "border-signal-red/40 bg-signal-red/10 text-signal-red",
  critical: "border-signal-red/60 bg-signal-red/20 text-signal-red",
};

export function ActionBadge({ action }: { action: RecommendedAction | null }) {
  if (!action) return <span className="font-mono text-[11px] text-ink-faint">—</span>;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-[2px] border px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider",
        ACTION_STYLES[action],
      )}
    >
      {ACTION_LABELS[action]}
    </span>
  );
}

export function SeverityBadge({ severity }: { severity: Severity | null }) {
  if (!severity) return <span className="font-mono text-[11px] text-ink-faint">—</span>;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-[2px] border px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wider",
        SEVERITY_STYLES[severity],
      )}
    >
      {severity}
    </span>
  );
}

export function MismatchScore({ score }: { score: number | null }) {
  if (score === null) return <span className="font-mono text-xs text-ink-faint">NO GEOM</span>;
  const color =
    score < 5 ? "text-signal-green" : score < 50 ? "text-signal-amber" : "text-signal-red";
  return <span className={cn("font-mono text-sm font-semibold tabular-nums", color)}>{score.toFixed(1)}</span>;
}
