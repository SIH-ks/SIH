import { Activity, BarChart3, Download, Gauge, Layers, ShieldAlert, Users } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { BarList } from "@/components/charts/BarList";
import { StatTile } from "@/components/charts/StatTile";
import { TrendChart } from "@/components/charts/TrendChart";
import { SeverityBadge } from "@/components/ui/Badge";
import { Card, CardHeader, EmptyState, ErrorPanel, LinkButton, PageHeader } from "@/components/ui/Primitives";
import {
  getDistrictBreakdown,
  getRuleFrequency,
  getSummary,
  getThroughput,
  getTimeseries,
} from "@/lib/api";
import {
  formatCount,
  formatDateTime,
  formatHectares,
  formatPercent,
  formatRelative,
  formatScore,
  humaniseRuleCode,
} from "@/lib/format";

export const metadata: Metadata = { title: "Analytics" };
export const dynamic = "force-dynamic";

const RANGE_OPTIONS = [7, 30, 90] as const;

/**
 * Analytics: the district-comparison and quality view.
 *
 * Two things here are worth more to a Ministry reviewer than any per-record
 * score. The first is the district table, which turns "is this working?" into a
 * comparison. The second is the rule-frequency panel: read across a whole
 * district, the rules that fire most often are a *data-quality report on the
 * source registers themselves* — if `MUTATION_DATE_IN_FUTURE` dominates one
 * taluk, the problem is that taluk's register, not the model.
 */
export default async function AnalyticsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const daysParam = Number(Array.isArray(raw.days) ? raw.days[0] : raw.days);
  const days = RANGE_OPTIONS.includes(daysParam as 7 | 30 | 90) ? daysParam : 30;

  const [summary, timeseries, districts, rules, throughput] = await Promise.all([
    getSummary(),
    getTimeseries(days),
    getDistrictBreakdown(),
    getRuleFrequency(14),
    getThroughput(days),
  ]);

  if (summary.error) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Analytics" />
        <ErrorPanel message={summary.error.message} unreachable={summary.error.unreachable} />
      </div>
    );
  }

  const s = summary.data;
  const maxRuleCount = Math.max(...(rules.data ?? []).map((r) => r.count), 1);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Analytics"
        description={`Computed in SQL across the whole corpus, not from a sampled page. Generated ${formatDateTime(s.generated_at)}.`}
        actions={
          <>
            <div className="flex rounded-lg border border-line bg-surface-card p-0.5">
              {RANGE_OPTIONS.map((option) => (
                <Link
                  key={option}
                  href={`/analytics?days=${option}`}
                  className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${
                    days === option
                      ? "bg-brand-navy text-white dark:bg-series-1"
                      : "text-ink-secondary hover:bg-surface-sunken"
                  }`}
                >
                  {option}d
                </Link>
              ))}
            </div>
            <LinkButton href="/api/proxy/exports/parcels.csv" variant="secondary" icon={Download} external>
              Export all records
            </LinkButton>
          </>
        }
      />

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Corpus size"
          value={formatCount(s.total_parcels)}
          icon={Layers}
          accent="navy"
          hint={`${formatHectares(s.total_area_hectares)} across ${s.villages_covered} villages`}
        />
        <StatTile
          label="Straight-through rate"
          value={s.straight_through_rate}
          suffix="%"
          icon={Gauge}
          accent="good"
          hint="Cleared by the pipeline with no human touch"
        />
        <StatTile
          label="Mean cadastral mismatch"
          value={formatScore(s.avg_mismatch)}
          icon={ShieldAlert}
          accent={(s.avg_mismatch ?? 0) > 20 ? "critical" : "warning"}
          hint="0 is an exact match with the survey polygon"
        />
        <StatTile
          label="Human corrections"
          value={formatCount(s.corrections_applied)}
          icon={Activity}
          accent="series"
          hint="Records a reviewer had to fix — the clearest signal of model quality"
        />
      </section>

      <Card>
        <CardHeader
          title={`Pipeline activity, last ${days} days`}
          subtitle="Ingestion, adjudication and corrections — three counts of records, so one shared axis"
          icon={BarChart3}
        />
        <div className="px-4 pb-4 pt-3">
          {timeseries.error ? (
            <ErrorPanel message={timeseries.error.message} unreachable={timeseries.error.unreachable} />
          ) : (
            <TrendChart
              height={240}
              labels={timeseries.data.map((point) =>
                new Date(point.date).toLocaleDateString("en-IN", { day: "numeric", month: "short" }),
              )}
              series={[
                {
                  key: "ingested",
                  label: "Ingested",
                  color: "var(--series-1)",
                  values: timeseries.data.map((p) => p.ingested),
                  fill: true,
                },
                {
                  key: "decided",
                  label: "Adjudicated",
                  color: "var(--series-3)",
                  values: timeseries.data.map((p) => p.decided),
                },
                {
                  key: "corrections",
                  label: "Corrections keyed",
                  color: "var(--series-2)",
                  values: timeseries.data.map((p) => p.corrections),
                },
              ]}
            />
          )}
        </div>
      </Card>

      {/* -- District comparison ------------------------------------------------ */}
      <Card>
        <CardHeader
          title="District performance"
          subtitle="The comparison a Commissioner asks for first"
          icon={Layers}
        />
        {districts.error ? (
          <ErrorPanel className="m-4" message={districts.error.message} unreachable={districts.error.unreachable} />
        ) : districts.data.length === 0 ? (
          <EmptyState icon={Layers} title="No districts yet" description="Ingest a scan to populate this." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead className="border-b border-line bg-surface-sunken text-[11px] uppercase tracking-wide text-ink-muted">
                <tr>
                  <th scope="col" className="px-4 py-2.5 font-semibold">District</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Records</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Flagged</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Approved</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Overdue</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Mean confidence</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Mean mismatch</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Area</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Completion</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {districts.data.map((row) => (
                  <tr key={`${row.state}-${row.district}`} className="transition-colors hover:bg-surface-sunken/60">
                    <td className="px-4 py-3">
                      <Link
                        href={`/records?district=${encodeURIComponent(row.district ?? "")}`}
                        className="block font-semibold text-ink-primary hover:text-series-1"
                      >
                        {row.district ?? "Unknown"}
                      </Link>
                      <span className="text-xs text-ink-muted">{row.state ?? "—"}</span>
                    </td>
                    <td className="px-4 py-3 font-mono tabular-nums text-ink-secondary">{row.total}</td>
                    <td className="px-4 py-3 font-mono tabular-nums">
                      <span className={row.flagged > 0 ? "text-status-critical-ink" : "text-ink-muted"}>
                        {row.flagged}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono tabular-nums text-ink-secondary">{row.approved}</td>
                    <td className="px-4 py-3 font-mono tabular-nums">
                      <span className={row.overdue > 0 ? "text-status-warning-ink" : "text-ink-muted"}>
                        {row.overdue}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono tabular-nums text-ink-secondary">
                      {row.avg_confidence !== null ? formatPercent(row.avg_confidence) : "—"}
                    </td>
                    <td className="px-4 py-3 font-mono tabular-nums text-ink-secondary">
                      {formatScore(row.avg_mismatch)}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs tabular-nums text-ink-secondary">
                      {formatHectares(row.total_area_hectares)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-14 overflow-hidden rounded-full bg-surface-sunken">
                          <div
                            className="h-full rounded-full bg-series-3"
                            style={{ width: `${Math.min(row.completion_rate, 100)}%` }}
                          />
                        </div>
                        <span className="font-mono text-xs tabular-nums text-ink-secondary">
                          {row.completion_rate.toFixed(0)}%
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* -- Rule frequency + reviewer workload --------------------------------- */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader
            title="Validation findings by rule"
            subtitle="Across a district, this is a quality report on the source registers — not on the model"
            icon={ShieldAlert}
            action={
              <Link href="/rules" className="text-xs font-semibold text-series-1 hover:underline">
                What each rule checks →
              </Link>
            }
          />
          <div className="px-4 py-4">
            {rules.error ? (
              <ErrorPanel message={rules.error.message} unreachable={rules.error.unreachable} />
            ) : (
              <BarList
                max={maxRuleCount}
                data={(rules.data ?? []).map((rule) => ({
                  label: humaniseRuleCode(rule.rule_code),
                  sublabel: rule.worst_severity,
                  value: rule.count,
                  color: severityColor(rule.worst_severity),
                  href: `/records?severity=${rule.worst_severity}`,
                }))}
                emptyMessage="No validation findings recorded across the corpus."
              />
            )}
          </div>
        </Card>

        <Card>
          <CardHeader
            title="Reviewer workload"
            subtitle="Distribution, not a leaderboard — the useful reading is who is carrying too much"
            icon={Users}
          />
          {throughput.error ? (
            <ErrorPanel className="m-4" message={throughput.error.message} unreachable={throughput.error.unreachable} />
          ) : (throughput.data ?? []).length === 0 ? (
            <EmptyState
              icon={Users}
              title="No activity in this window"
              description="Nobody has acted on a record in the selected range."
            />
          ) : (
            <ul className="divide-y divide-line">
              {(throughput.data ?? []).map((row) => (
                <li key={row.reviewer} className="flex items-center justify-between gap-4 px-4 py-3">
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-semibold text-ink-primary">@{row.reviewer}</p>
                    <p className="text-xs text-ink-muted">
                      {row.role ?? "—"} · last active {formatRelative(row.last_active)}
                    </p>
                  </div>
                  <dl className="flex shrink-0 gap-4 text-right">
                    <div>
                      <dd className="font-mono text-sm font-semibold tabular-nums text-ink-primary">
                        {row.decisions}
                      </dd>
                      <dt className="text-[10px] uppercase tracking-wide text-ink-muted">Decisions</dt>
                    </div>
                    <div>
                      <dd className="font-mono text-sm font-semibold tabular-nums text-ink-primary">
                        {row.corrections}
                      </dd>
                      <dt className="text-[10px] uppercase tracking-wide text-ink-muted">Corrections</dt>
                    </div>
                  </dl>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </section>

      {/* -- Severity mix ------------------------------------------------------- */}
      {rules.data && rules.data.length > 0 && (
        <Card>
          <CardHeader
            title="Severity mix per rule"
            subtitle="A rule can fire at several severities depending on how far a record is out"
          />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead className="border-b border-line bg-surface-sunken text-[11px] uppercase tracking-wide text-ink-muted">
                <tr>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Rule</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Findings</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Worst severity</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">Breakdown</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rules.data.map((rule) => (
                  <tr key={rule.rule_code} className="transition-colors hover:bg-surface-sunken/60">
                    <td className="px-4 py-3">
                      <span className="block text-[13px] font-medium text-ink-primary">
                        {humaniseRuleCode(rule.rule_code)}
                      </span>
                      <code className="text-[10px] text-ink-muted">{rule.rule_code}</code>
                    </td>
                    <td className="px-4 py-3 font-mono tabular-nums text-ink-secondary">{rule.count}</td>
                    <td className="px-4 py-3">
                      <SeverityBadge severity={rule.worst_severity} />
                    </td>
                    <td className="px-4 py-3">
                      <span className="flex flex-wrap gap-2 text-xs text-ink-secondary">
                        {Object.entries(rule.severities).map(([severity, count]) => (
                          <span key={severity} className="flex items-center gap-1">
                            <span
                              className="h-2 w-2 rounded-[2px]"
                              style={{ background: severityColor(severity) }}
                              aria-hidden
                            />
                            {severity} <strong className="font-semibold text-ink-primary">{count}</strong>
                          </span>
                        ))}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function severityColor(severity: string): string {
  switch (severity) {
    case "critical":
      return "var(--status-critical)";
    case "error":
      return "var(--status-serious)";
    case "warning":
      return "var(--status-warning)";
    default:
      return "var(--series-1)";
  }
}
