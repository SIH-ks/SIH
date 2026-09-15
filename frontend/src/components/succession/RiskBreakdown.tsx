import type { RiskContribution } from "@/types/succession";

/**
 * The risk score's arithmetic, decomposed to the point where it can be argued
 * with. `risk_score` is the plain sum of these `points` values and nothing
 * else — no blend, no opaque weighting on top — so this bar chart *is* the
 * calculation, not a visualization of one happening elsewhere.
 */
export function RiskBreakdown({
  contributions,
  score,
}: {
  contributions: RiskContribution[];
  score: number;
}) {
  if (contributions.length === 0) {
    return (
      <p className="px-4 py-6 text-center text-sm text-ink-muted">
        No check contributed to the risk score — every applicable check came back clear.
      </p>
    );
  }

  const max = Math.max(...contributions.map((c) => c.points), 1);

  return (
    <div className="flex flex-col gap-2.5 px-4 py-4">
      {contributions.map((c) => (
        <div key={c.rule} className="flex items-center gap-3">
          <div className="w-40 shrink-0 truncate text-[11px] font-medium text-ink-secondary" title={c.rule}>
            {c.rule.replace(/_/g, " ")}
          </div>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-sunken">
            <div
              className="h-full rounded-full bg-status-serious"
              style={{ width: `${(c.points / max) * 100}%` }}
            />
          </div>
          <div className="w-32 shrink-0 text-right font-mono text-[11px] tabular-nums text-ink-muted">
            {c.base_points.toFixed(0)} × {c.multiplier.toFixed(2)} = {c.points.toFixed(1)}
          </div>
        </div>
      ))}
      <div className="mt-1 flex items-center justify-between border-t border-line pt-2 text-xs font-semibold text-ink-primary">
        <span>Total risk score (capped at 100)</span>
        <span className="font-mono tabular-nums">{score.toFixed(1)}</span>
      </div>
    </div>
  );
}
