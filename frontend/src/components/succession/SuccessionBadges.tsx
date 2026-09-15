import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  CircleDashed,
  Eye,
  FileQuestion,
  Scale,
  ShieldQuestion,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/format";
import type {
  CheckStatus,
  SuccessionAction,
  SuccessionOutcome,
  SuccessionRiskLevel,
} from "@/types/succession";

/**
 * Status signals for succession cases.
 *
 * Follows the same rule as `ui/Badge.tsx`: colour never carries meaning alone,
 * so every badge pairs its fill with an icon *and* a word.
 *
 * One addition specific to this feature. `review_required` gets its own tone and
 * its own icon rather than reusing "warning" or "critical", because it means
 * something neither of those does: the documents are internally consistent *and*
 * do not establish what the record asserts. Rendering it as a failure would put a
 * verdict on the screen that the engine did not reach.
 */

type Tone = "good" | "warning" | "serious" | "critical" | "neutral" | "info";

const TONE_CLASSES: Record<Tone, string> = {
  good: "bg-status-good-wash text-status-good-ink ring-status-good/30",
  warning: "bg-status-warning-wash text-status-warning-ink ring-status-warning/35",
  serious: "bg-status-serious-wash text-status-serious-ink ring-status-serious/35",
  critical: "bg-status-critical-wash text-status-critical-ink ring-status-critical/35",
  neutral: "bg-surface-sunken text-ink-secondary ring-line-strong/60",
  info: "bg-series-1/10 text-series-1 ring-series-1/25",
};

function Pill({
  tone,
  icon: Icon,
  children,
  className,
  title,
}: {
  tone: Tone;
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

// ---------------------------------------------------------------------------

const OUTCOME_CONFIG: Record<
  SuccessionOutcome,
  { label: string; icon: LucideIcon; tone: Tone; title: string }
> = {
  validated: {
    label: "Documents consistent",
    icon: CheckCircle2,
    tone: "good",
    title: "Every check the submitted documents supported came back clear.",
  },
  incomplete: {
    label: "Evidence incomplete",
    icon: FileQuestion,
    tone: "warning",
    title: "Nothing contradicts, but documents needed to establish the chain are absent.",
  },
  review_required: {
    label: "Review required",
    icon: ShieldQuestion,
    tone: "serious",
    title:
      "The documents are internally consistent and do not establish what the record asserts. This is a statement about the evidence, not a finding of wrongdoing.",
  },
  inconsistent: {
    label: "Documents contradict",
    icon: AlertOctagon,
    tone: "critical",
    title: "Submitted documents disagree with each other on a matter of fact.",
  },
};

export function OutcomeBadge({
  outcome,
  className,
}: {
  outcome: SuccessionOutcome;
  className?: string;
}) {
  const { label, icon, tone, title } = OUTCOME_CONFIG[outcome];
  return (
    <Pill tone={tone} icon={icon} className={className} title={title}>
      {label}
    </Pill>
  );
}

const RISK_CONFIG: Record<SuccessionRiskLevel, { label: string; tone: Tone }> = {
  low: { label: "Low risk", tone: "good" },
  medium: { label: "Medium risk", tone: "warning" },
  high: { label: "High risk", tone: "serious" },
  critical: { label: "Critical risk", tone: "critical" },
};

/** The score is shown beside the band, always. A band alone hides a 41 sitting
 * one point above a threshold, which is exactly the case a reviewer should be
 * able to argue with. */
export function RiskBadge({
  level,
  score,
  className,
}: {
  level: SuccessionRiskLevel;
  score?: number;
  className?: string;
}) {
  const { label, tone } = RISK_CONFIG[level];
  return (
    <Pill tone={tone} icon={AlertTriangle} className={className}>
      {label}
      {score !== undefined && (
        <span className="font-mono text-[10px] font-bold tabular-nums opacity-80">
          {score.toFixed(0)}
        </span>
      )}
    </Pill>
  );
}

const ACTION_CONFIG: Record<SuccessionAction, { label: string; icon: LucideIcon; tone: Tone }> = {
  accept_record: { label: "Record supported", icon: CheckCircle2, tone: "good" },
  obtain_additional_documents: { label: "Obtain documents", icon: FileQuestion, tone: "warning" },
  human_review: { label: "Human review", icon: Eye, tone: "serious" },
  refer_to_revenue_authority: { label: "Refer to Revenue Officer", icon: Scale, tone: "critical" },
};

export function SuccessionActionBadge({
  action,
  className,
}: {
  action: SuccessionAction;
  className?: string;
}) {
  const { label, icon, tone } = ACTION_CONFIG[action];
  return (
    <Pill tone={tone} icon={icon} className={className}>
      {label}
    </Pill>
  );
}

const CHECK_CONFIG: Record<CheckStatus, { label: string; icon: LucideIcon; tone: Tone }> = {
  pass: { label: "Pass", icon: CheckCircle2, tone: "good" },
  warning: { label: "Warning", icon: AlertTriangle, tone: "warning" },
  review_required: { label: "Review required", icon: ShieldQuestion, tone: "serious" },
  fail: { label: "Fail", icon: AlertOctagon, tone: "critical" },
  // Recorded, never hidden: the report is evidence of what was and was not
  // examined, and a check silently omitted looks identical to one that passed.
  not_applicable: { label: "Not applicable", icon: CircleDashed, tone: "neutral" },
};

export function CheckStatusBadge({
  status,
  className,
}: {
  status: CheckStatus;
  className?: string;
}) {
  const { label, icon, tone } = CHECK_CONFIG[status];
  return (
    <Pill tone={tone} icon={icon} className={className}>
      {label}
    </Pill>
  );
}

export const CHECK_STATUS_RANK: Record<CheckStatus, number> = {
  not_applicable: 0,
  pass: 1,
  warning: 2,
  review_required: 3,
  fail: 4,
};
