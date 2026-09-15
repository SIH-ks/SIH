import { ArrowRight } from "lucide-react";

import { cn } from "@/lib/format";
import type { SuccessionCheck } from "@/types/succession";

import { CHECK_STATUS_RANK, CheckStatusBadge } from "./SuccessionBadges";

/**
 * Every check the engine ran, worst first — including the ones that passed.
 *
 * A reviewer deciding whether to accept a transfer needs to know the parcel
 * identifiers *were* compared and *did* agree, not just that nothing failed.
 * Showing only problems cannot distinguish "checked and fine" from "not
 * checked", so passing and not-applicable checks are kept, dimmed rather than
 * hidden.
 *
 * Each row's evidence chips are Requirement 10 made visible: "Previous owner
 * matches death certificate" is followed by the two document fields that made
 * it true, exactly as the specification's example lays out.
 */
export function SuccessionChecklist({ checks }: { checks: SuccessionCheck[] }) {
  const sorted = [...checks].sort(
    (a, b) => CHECK_STATUS_RANK[b.status] - CHECK_STATUS_RANK[a.status] || a.rule.localeCompare(b.rule),
  );

  return (
    <ul className="divide-y divide-line">
      {sorted.map((check) => (
        <li
          key={check.rule}
          className={cn("px-4 py-3", check.status === "not_applicable" && "opacity-60")}
        >
          <div className="flex flex-wrap items-center gap-2">
            <CheckStatusBadge status={check.status} />
            <span className="text-[13px] font-semibold text-ink-primary">
              {check.rule.replace(/_/g, " ")}
            </span>
            <code className="font-mono text-[10px] text-ink-muted">{check.rule_code}</code>
            {check.match_score !== null && (
              <span className="text-[10px] text-ink-muted">
                match {Math.round(check.match_score * 100)}%
              </span>
            )}
          </div>
          <p className="mt-1.5 text-[13px] leading-snug text-ink-primary">{check.explanation}</p>

          {check.evidence.length > 0 && (
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {check.evidence.map((ref, index) => (
                <span key={index} className="inline-flex items-center gap-1">
                  <span
                    className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[11px] text-ink-secondary"
                    title={ref.raw_value ?? undefined}
                  >
                    {ref.document_label ?? ref.document_type}
                    {ref.field_path && <span className="text-ink-muted"> → {ref.field_path}</span>}
                    {ref.value && <span className="text-ink-primary"> = {ref.value}</span>}
                  </span>
                  {index < check.evidence.length - 1 && (
                    <ArrowRight className="h-3 w-3 text-ink-muted" aria-hidden />
                  )}
                </span>
              ))}
            </div>
          )}

          {check.remediation && (
            <p className="mt-1.5 flex gap-1.5 text-xs leading-snug text-ink-muted">
              <span aria-hidden>→</span>
              <span className="italic">{check.remediation}</span>
            </p>
          )}
          {check.risk_points > 0 && (
            <p className="mt-1 text-[10px] font-mono text-ink-muted">
              contributes {check.risk_points.toFixed(1)} to the risk score
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}
