import Link from "next/link";

import { EmptyState } from "@/components/ui/Primitives";
import { formatRelative } from "@/lib/format";
import type { SuccessionCaseSummary } from "@/types/succession";

import { FileQuestion } from "lucide-react";
import { OutcomeBadge, RiskBadge } from "./SuccessionBadges";

export function SuccessionCasesTable({ cases }: { cases: SuccessionCaseSummary[] }) {
  if (cases.length === 0) {
    return (
      <EmptyState
        icon={FileQuestion}
        title="No succession cases"
        description="Cases appear here once a succession bundle is submitted through Upload or the API."
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left text-sm">
        <thead>
          <tr className="border-b border-line text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
            <th className="px-4 py-2.5">Case</th>
            <th className="px-4 py-2.5">Location</th>
            <th className="px-4 py-2.5">Outcome</th>
            <th className="px-4 py-2.5">Risk</th>
            <th className="px-4 py-2.5">Heirs</th>
            <th className="px-4 py-2.5">Filed</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {cases.map((item) => (
            <tr key={item.id} className="transition-colors hover:bg-surface-sunken">
              <td className="px-4 py-2.5">
                <Link
                  href={`/succession/${item.id}`}
                  className="font-mono text-xs font-semibold text-series-1 hover:underline"
                >
                  {item.case_reference}
                </Link>
                {item.parcel_key && (
                  <p className="mt-0.5 truncate text-[11px] text-ink-muted">{item.parcel_key}</p>
                )}
              </td>
              <td className="px-4 py-2.5 text-xs text-ink-secondary">
                {item.village ?? "—"}
                {item.district && <span className="text-ink-muted"> · {item.district}</span>}
              </td>
              <td className="px-4 py-2.5">
                <OutcomeBadge outcome={item.outcome} />
              </td>
              <td className="px-4 py-2.5">
                <RiskBadge level={item.risk_level} score={item.risk_score} />
              </td>
              <td className="px-4 py-2.5 text-xs text-ink-secondary">{item.heir_count}</td>
              <td className="px-4 py-2.5 text-xs text-ink-muted">{formatRelative(item.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
