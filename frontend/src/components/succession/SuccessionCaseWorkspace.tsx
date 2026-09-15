import { AlertTriangle, GitBranch, ListChecks, ScrollText, Users } from "lucide-react";

import { Card, CardHeader, EmptyState, Field } from "@/components/ui/Primitives";
import { formatDateTime } from "@/lib/format";
import type { SuccessionCaseDetail } from "@/types/succession";

import { OutcomeBadge, RiskBadge, SuccessionActionBadge } from "./SuccessionBadges";
import { OwnershipTimeline } from "./OwnershipTimeline";
import { RiskBreakdown } from "./RiskBreakdown";
import { SuccessionChecklist } from "./SuccessionChecklist";

/**
 * One succession case, in full — the identity strip, the plain-language summary,
 * the ownership timeline, every check, and the risk arithmetic.
 *
 * What a reviewer needs to see, per the specification: previous owner, death
 * event, potential heirs identified, mutation event, new recorded owner(s),
 * supporting documents, validation checks, risk level, and *why* the case was
 * flagged. Every one of those is a section here, in that order — decision first
 * (identity strip, summary, outcome), evidence second (timeline), detail third
 * (checks, risk breakdown).
 */
export function SuccessionCaseWorkspace({ case: item }: { case: SuccessionCaseDetail }) {
  const { report } = item;

  return (
    <div className="flex flex-col gap-5">
      <div>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold tracking-tight text-ink-primary">{item.case_reference}</h2>
            <p className="mt-0.5 text-sm text-ink-secondary">
              {item.village ?? "—"}
              {item.district && <span className="text-ink-muted"> · {item.district}</span>}
              {item.parcel_key && (
                <code className="ml-2 rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[11px] text-ink-muted">
                  {item.parcel_key}
                </code>
              )}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <OutcomeBadge outcome={item.outcome} />
            <RiskBadge level={item.risk_level} score={item.risk_score} />
            <SuccessionActionBadge action={item.recommended_action} />
          </div>
        </div>

        <p className="mt-3 max-w-3xl rounded-lg border border-line bg-surface-sunken px-3.5 py-3 text-[13px] leading-relaxed text-ink-primary">
          {report.summary}
        </p>

        {report.issues.length > 0 && (
          <div className="mt-3 flex flex-col gap-1.5">
            {report.issues.map((issue, index) => (
              <p key={index} className="flex items-start gap-2 text-[13px] leading-snug text-ink-secondary">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-status-warning" aria-hidden />
                {issue}
              </p>
            ))}
          </div>
        )}

        <p className="mt-3 rounded-lg border border-line-hairline bg-surface-card px-3 py-2 text-[11px] italic leading-relaxed text-ink-muted">
          {report.disclaimer}
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Field
          label="Previous owner(s)"
          value={report.previous_owners.map((o) => o.name).join(", ") || "—"}
        />
        <Field
          label="Current owner(s)"
          value={report.current_owners.map((o) => o.name).join(", ") || "—"}
        />
        <Field
          label="Death verified"
          value={report.death_verified ? "Yes, against the previous record" : "No"}
        />
        <Field label="Potential heirs" value={String(report.potential_heirs.length)} />
      </div>

      {report.potential_heirs.length > 0 && (
        <Card>
          <CardHeader
            title="Potential heirs identified"
            subtitle="Named by the submitted documents — not a determination of entitlement or share"
            icon={Users}
          />
          <ul className="flex flex-wrap gap-2 px-4 py-3">
            {report.potential_heirs.map((heir) => (
              <li
                key={heir.name}
                className="rounded-full bg-surface-sunken px-3 py-1.5 text-xs font-medium text-ink-primary ring-1 ring-inset ring-line-strong/50"
              >
                {heir.name}
                {heir.relation !== "unknown" && (
                  <span className="text-ink-muted"> · {heir.relation.replace(/_/g, " ")}</span>
                )}
                {heir.stated_share && <span className="text-ink-muted"> · {heir.stated_share}</span>}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Ownership timeline"
          subtitle="Previous owner → death → potential heirs → mutation → current owner(s)"
          icon={GitBranch}
        />
        <OwnershipTimeline events={report.timeline} />
      </Card>

      <section className="grid grid-cols-1 gap-5 lg:grid-cols-[1.2fr_1fr]">
        <Card>
          <CardHeader
            title={`Validation checks (${report.checks.length})`}
            subtitle="Every check the engine ran, including the ones that passed"
            icon={ListChecks}
          />
          <div className="max-h-[520px] overflow-y-auto">
            <SuccessionChecklist checks={report.checks} />
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Why this case scored what it did"
            subtitle="The risk score is the sum of these contributions, capped at 100"
            icon={AlertTriangle}
          />
          <RiskBreakdown contributions={report.risk_contributions} score={report.risk_score} />
        </Card>
      </section>

      {item.normalization_warnings.length > 0 && (
        <Card>
          <CardHeader
            title="How the submission was read"
            subtitle="Values the engine could not normalise — the assessment above was made without them"
            icon={ScrollText}
          />
          <ul className="flex flex-col gap-1.5 px-4 py-3">
            {item.normalization_warnings.map((warning, index) => (
              <li key={index} className="text-xs text-ink-muted">
                {warning}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <p className="text-[11px] text-ink-muted">
        Filed by {item.created_by ? `@${item.created_by}` : "—"} on {formatDateTime(item.created_at)} ·
        last assessed {formatDateTime(item.updated_at)}
      </p>
    </div>
  );
}

export function SuccessionCaseEmptyState() {
  return (
    <EmptyState
      icon={ScrollText}
      title="No succession case for this record"
      description="No ownership-succession bundle has been filed against this parcel yet."
    />
  );
}
