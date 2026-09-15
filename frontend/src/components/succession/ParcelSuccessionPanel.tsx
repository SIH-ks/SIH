import { GitBranch } from "lucide-react";
import Link from "next/link";

import { Card, CardHeader } from "@/components/ui/Primitives";
import { formatRelative } from "@/lib/format";
import type { SuccessionCaseSummary } from "@/types/succession";

import { OutcomeBadge, RiskBadge } from "./SuccessionBadges";

/**
 * A compact succession panel for the parcel detail page.
 *
 * Absent when a record has no case — not shown empty. A record with no
 * succession filing is the ordinary state for almost every parcel in the
 * register, and a panel that always renders "no succession case" on every
 * record would be noise the reviewer learns to skip past, which is worse than
 * not being there.
 */
export function ParcelSuccessionPanel({ cases }: { cases: SuccessionCaseSummary[] }) {
  if (cases.length === 0) return null;

  return (
    <Card>
      <CardHeader
        title="Ownership succession"
        subtitle="Documentary-consistency assessment of a recorded ownership transition — not a determination of legal entitlement"
        icon={GitBranch}
      />
      <ul className="divide-y divide-line">
        {cases.map((item) => (
          <li key={item.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
            <div className="min-w-0">
              <Link
                href={`/succession/${item.id}`}
                className="font-mono text-xs font-semibold text-series-1 hover:underline"
              >
                {item.case_reference}
              </Link>
              <p className="mt-0.5 text-[11px] text-ink-muted">
                Filed {formatRelative(item.created_at)}
                {item.created_by && ` by @${item.created_by}`}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <OutcomeBadge outcome={item.outcome} />
              <RiskBadge level={item.risk_level} score={item.risk_score} />
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}
