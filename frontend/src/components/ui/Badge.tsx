import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Clock,
  Eye,
  Info,
  ShieldAlert,
  XCircle,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/format";
import type { ParcelSummary, Priority, RecommendedAction, ReviewStatus, Severity } from "@/types/parcel";

/**
 * Every status signal in the console, in one file.
 *
 * The rule these all follow: **colour never carries meaning alone.** Each badge
 * pairs its fill with an icon *and* a word, so a reviewer with a colour-vision
 * deficiency, a printed report, and a forced-colours display all read the same
 * thing. That is also why the status hues are kept separate from the chart
 * series palette — a colour that means "serious" must never also mean "series 3".
 */

// ---------------------------------------------------------------------------
// Traffic light — the single glanceable signal the records table is built around
// ---------------------------------------------------------------------------

export type TrafficLight = "green" | "yellow" | "red";

/**
 * Derived from the pipeline's two independent outcomes (the discrepancy engine's
 * `recommended_action` and the validation engine's `validation_highest_severity`)
 * rather than stored directly -- a record can only be "Auto-Validated" green when
 * *both* systems agree nothing needs a human, so this function is where that
 * agreement is decided, once, rather than re-derived inconsistently at each call
 * site. It mirrors the SQL in `app/services/analytics.summary`, which is what
 * keeps the dashboard tiles and this column from disagreeing.
 */
export function deriveTrafficLight(parcel: ParcelSummary): TrafficLight {
  if (
    parcel.recommended_action === "reject_re_scan" ||
    parcel.validation_highest_severity === "critical" ||
    (parcel.mismatch_score !== null && parcel.mismatch_score >= 50)
  ) {
    return "red";
  }
  if (
    parcel.recommended_action === "auto_approve" &&
    parcel.validation_highest_severity !== "error" &&
    parcel.validation_highest_severity !== "warning"
  ) {
    return "green";
  }
  return "yellow";
}

type BadgeTone = "good" | "warning" | "serious" | "critical" | "neutral" | "info";

const TONE_CLASSES: Record<BadgeTone, string> = {
  good: "bg-status-good-wash text-status-good-ink ring-status-good/30",
  warning: "bg-status-warning-wash text-status-warning-ink ring-status-warning/35",
  serious: "bg-status-serious-wash text-status-serious-ink ring-status-serious/35",
  critical: "bg-status-critical-wash text-status-critical-ink ring-status-critical/35",
  neutral: "bg-surface-sunken text-ink-secondary ring-line-strong/60",
  info: "bg-series-1/10 text-series-1 ring-series-1/25",
};

const DOT_CLASSES: Record<BadgeTone, string> = {
  good: "bg-status-good",
  warning: "bg-status-warning",
  serious: "bg-status-serious",
  critical: "bg-status-critical",
  neutral: "bg-ink-muted",
  info: "bg-series-1",
};

function Pill({
  tone,
  icon: Icon,
  children,
  className,
  title,
}: {
  tone: BadgeTone;
  icon?: LucideIcon;
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset",
        TONE_CLASSES[tone],
        className,
      )}
    >
      {Icon && <Icon className="h-3.5 w-3.5 shrink-0" strokeWidth={2.25} aria-hidden />}
      {children}
    </span>
  );
}

const TRAFFIC_CONFIG: Record<TrafficLight, { label: string; icon: LucideIcon; tone: BadgeTone }> = {
  green: { label: "Auto-validated", icon: CheckCircle2, tone: "good" },
  yellow: { label: "Requires review", icon: AlertTriangle, tone: "warning" },
  red: { label: "Flagged / risk", icon: AlertOctagon, tone: "critical" },
};

export function TrafficLightBadge({ status, className }: { status: TrafficLight; className?: string }) {
  const { label, icon, tone } = TRAFFIC_CONFIG[status];
  return (
    <Pill tone={tone} icon={icon} className={className}>
      {label}
    </Pill>
  );
}

/** A bare dot for dense contexts where the full pill would be too wide. Carries
 * its label in `title` and in visually-hidden text so it is never colour-only. */
export function TrafficLightDot({ status }: { status: TrafficLight }) {
  const { label, tone } = TRAFFIC_CONFIG[status];
  return (
    <span className="inline-flex items-center" title={label}>
      <span className={cn("inline-block h-2.5 w-2.5 rounded-full", DOT_CLASSES[tone])} aria-hidden />
      <span className="sr-only">{label}</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Workflow status
// ---------------------------------------------------------------------------

const STATUS_CONFIG: Record<ReviewStatus, { label: string; icon: LucideIcon; tone: BadgeTone }> = {
  pending: { label: "Pending triage", icon: CircleDashed, tone: "neutral" },
  in_review: { label: "In review", icon: Eye, tone: "info" },
  approved: { label: "Approved", icon: CheckCircle2, tone: "good" },
  rejected: { label: "Rejected", icon: XCircle, tone: "critical" },
  escalated: { label: "Escalated", icon: ShieldAlert, tone: "serious" },
};

export function StatusBadge({ status, className }: { status: ReviewStatus; className?: string }) {
  const config = STATUS_CONFIG[status] ?? STATUS_CONFIG.pending;
  return (
    <Pill tone={config.tone} icon={config.icon} className={className}>
      {config.label}
    </Pill>
  );
}

export const REVIEW_STATUS_LABEL: Record<ReviewStatus, string> = {
  pending: "Pending triage",
  in_review: "In review",
  approved: "Approved",
  rejected: "Rejected",
  escalated: "Escalated",
};

// ---------------------------------------------------------------------------
// Triage priority
// ---------------------------------------------------------------------------

const PRIORITY_CONFIG: Record<Priority, { label: string; tone: BadgeTone }> = {
  critical: { label: "Critical", tone: "critical" },
  high: { label: "High", tone: "serious" },
  normal: { label: "Normal", tone: "warning" },
  low: { label: "Low", tone: "neutral" },
};

export function PriorityBadge({ priority, score }: { priority: Priority; score?: number }) {
  const config = PRIORITY_CONFIG[priority] ?? PRIORITY_CONFIG.normal;
  return (
    <Pill
      tone={config.tone}
      title={score !== undefined ? `Triage score ${score.toFixed(1)} / 100` : undefined}
      className="px-2 py-0.5"
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", DOT_CLASSES[config.tone])} aria-hidden />
      {config.label}
    </Pill>
  );
}

// ---------------------------------------------------------------------------
// Validation severity
// ---------------------------------------------------------------------------

const SEVERITY_CONFIG: Record<Severity, { icon: LucideIcon; tone: BadgeTone }> = {
  info: { icon: Info, tone: "info" },
  warning: { icon: AlertTriangle, tone: "warning" },
  error: { icon: AlertOctagon, tone: "serious" },
  critical: { icon: ShieldAlert, tone: "critical" },
};

export function SeverityBadge({ severity }: { severity: Severity | null }) {
  if (!severity) return <span className="text-xs text-ink-muted">—</span>;
  const config = SEVERITY_CONFIG[severity] ?? SEVERITY_CONFIG.info;
  return (
    <Pill tone={config.tone} icon={config.icon} className="px-2 py-0.5 capitalize">
      {severity}
    </Pill>
  );
}

// ---------------------------------------------------------------------------
// Pipeline recommendation
// ---------------------------------------------------------------------------

const ACTION_CONFIG: Record<RecommendedAction, { label: string; tone: BadgeTone }> = {
  auto_approve: { label: "Auto-approve", tone: "good" },
  review_queue: { label: "Review queue", tone: "warning" },
  field_verification: { label: "Field verification", tone: "serious" },
  reject_re_scan: { label: "Reject / re-scan", tone: "critical" },
};

export function ActionBadge({ action }: { action: RecommendedAction | null }) {
  if (!action) return <span className="text-xs text-ink-muted">—</span>;
  const config = ACTION_CONFIG[action];
  if (!config) return <span className="text-xs text-ink-muted">{action}</span>;
  return (
    <Pill tone={config.tone} className="px-2 py-0.5">
      {config.label}
    </Pill>
  );
}

// ---------------------------------------------------------------------------
// Service level
// ---------------------------------------------------------------------------

/**
 * The SLA clock. Shown only while a record is still open: an approved record's
 * deadline has stopped mattering, and a red "overdue" badge on finished work
 * would send a reviewer chasing something already done.
 */
export function SlaBadge({
  dueAt,
  status,
  className,
}: {
  dueAt: string | null;
  status: ReviewStatus;
  className?: string;
}) {
  if (!dueAt || status === "approved" || status === "rejected") return null;

  const hours = Math.round((new Date(dueAt).getTime() - Date.now()) / 3_600_000);
  if (Number.isNaN(hours)) return null;

  if (hours < 0) {
    return (
      <Pill tone="critical" icon={Clock} className={cn("px-2 py-0.5", className)}>
        Overdue {formatSpan(-hours)}
      </Pill>
    );
  }
  if (hours <= 24) {
    return (
      <Pill tone="warning" icon={Clock} className={cn("px-2 py-0.5", className)}>
        Due in {formatSpan(hours)}
      </Pill>
    );
  }
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs text-ink-muted", className)}>
      <Clock className="h-3 w-3" aria-hidden /> Due in {formatSpan(hours)}
    </span>
  );
}

function formatSpan(hours: number): string {
  if (hours < 1) return "< 1 h";
  if (hours < 48) return `${hours} h`;
  return `${Math.round(hours / 24)} d`;
}

// ---------------------------------------------------------------------------

export function MismatchScore({ score }: { score: number | null }) {
  if (score === null) {
    return (
      <span className="text-xs text-ink-muted" title="No cadastral polygon was matched to this parcel.">
        No geometry
      </span>
    );
  }
  const tone = score < 5 ? "text-status-good-ink" : score < 50 ? "text-status-warning-ink" : "text-status-critical-ink";
  return <span className={cn("font-mono text-sm font-semibold tabular-nums", tone)}>{score.toFixed(1)}</span>;
}
