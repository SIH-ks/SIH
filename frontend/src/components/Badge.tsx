import { AlertOctagon, AlertTriangle, CheckCircle2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ParcelSummary, RecommendedAction, Severity } from "@/types/parcel";

/**
 * The traffic-light status: the single glanceable signal the Command Dashboard's
 * table is built around. Derived from the pipeline's two independent outcomes
 * (the discrepancy engine's `recommended_action` and the validation engine's
 * `validation_highest_severity`) rather than stored directly -- a record can only
 * be "Auto-Validated" green when *both* systems agree nothing needs a human, so
 * this function is where that agreement is decided, once, rather than re-derived
 * inconsistently at each call site.
 */
export type TrafficLight = "green" | "yellow" | "red";

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

const TRAFFIC_LIGHT_CONFIG: Record<
  TrafficLight,
  { label: string; icon: typeof CheckCircle2; classes: string; dot: string }
> = {
  green: {
    label: "Auto-Validated",
    icon: CheckCircle2,
    classes: "bg-status-green-bg text-status-green-text ring-status-green-border",
    dot: "bg-status-green-dot",
  },
  yellow: {
    label: "Requires Review",
    icon: AlertTriangle,
    classes: "bg-status-amber-bg text-status-amber-text ring-status-amber-border",
    dot: "bg-status-amber-dot",
  },
  red: {
    label: "Flagged / Risk",
    icon: AlertOctagon,
    classes: "bg-status-red-bg text-status-red-text ring-status-red-border",
    dot: "bg-status-red-dot",
  },
};

export function TrafficLightBadge({ status }: { status: TrafficLight }) {
  const { label, icon: Icon, classes } = TRAFFIC_LIGHT_CONFIG[status];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-inset",
        classes,
      )}
    >
      <Icon className="h-3.5 w-3.5" strokeWidth={2.25} />
      {label}
    </span>
  );
}

/** A bare dot version for dense contexts (e.g. a table's leftmost column) where
 * the full pill would be too wide. */
export function TrafficLightDot({ status }: { status: TrafficLight }) {
  const { dot, label } = TRAFFIC_LIGHT_CONFIG[status];
  return <span className={cn("inline-block h-2.5 w-2.5 rounded-full", dot)} title={label} />;
}

// -- Secondary badges: the discrepancy engine's own recommendation, and validation
// severity, shown as supporting detail alongside (not instead of) the traffic light.

const ACTION_LABELS: Record<RecommendedAction, string> = {
  auto_approve: "Auto-approve",
  review_queue: "Review queue",
  field_verification: "Field verification",
  reject_re_scan: "Reject / re-scan",
};

const ACTION_STYLES: Record<RecommendedAction, string> = {
  auto_approve: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  review_queue: "bg-amber-50 text-amber-700 ring-amber-200",
  field_verification: "bg-orange-50 text-orange-700 ring-orange-200",
  reject_re_scan: "bg-red-50 text-red-700 ring-red-200",
};

export function ActionBadge({ action }: { action: RecommendedAction | null }) {
  if (!action) return <span className="text-xs text-slate-400">—</span>;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset",
        ACTION_STYLES[action],
      )}
    >
      {ACTION_LABELS[action]}
    </span>
  );
}

const SEVERITY_STYLES: Record<Severity, string> = {
  info: "bg-blue-50 text-blue-700 ring-blue-200",
  warning: "bg-amber-50 text-amber-700 ring-amber-200",
  error: "bg-red-50 text-red-700 ring-red-200",
  critical: "bg-red-100 text-red-800 ring-red-300",
};

export function SeverityBadge({ severity }: { severity: Severity | null }) {
  if (!severity) return <span className="text-xs text-slate-400">—</span>;
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ring-1 ring-inset",
        SEVERITY_STYLES[severity],
      )}
    >
      {severity}
    </span>
  );
}

export function MismatchScore({ score }: { score: number | null }) {
  if (score === null) return <span className="text-xs text-slate-400">No geometry</span>;
  const color = score < 5 ? "text-emerald-600" : score < 50 ? "text-amber-600" : "text-red-600";
  return <span className={cn("font-mono text-sm font-semibold tabular-nums", color)}>{score.toFixed(1)}</span>;
}
