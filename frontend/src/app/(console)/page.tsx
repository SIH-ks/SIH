import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  Clock,
  FileStack,
  Gauge,
  Layers,
  ListChecks,
  Timer,
} from "lucide-react";
import Link from "next/link";

import { BarList, ProportionBar } from "@/components/charts/BarList";
import { DonutChart } from "@/components/charts/DonutChart";
import { StatTile } from "@/components/charts/StatTile";
import { TrendChart } from "@/components/charts/TrendChart";
import { PriorityBadge, SlaBadge, TrafficLightDot, deriveTrafficLight } from "@/components/ui/Badge";
import { Card, CardHeader, EmptyState, ErrorPanel, LinkButton, PageHeader } from "@/components/ui/Primitives";
import {
  getDistrictBreakdown,
  getQueueHealth,
  getReviewQueue,
  getRuleFrequency,
  getSummary,
  getTimeseries,
} from "@/lib/api";
import { formatCount, formatHectares, formatPercent, humaniseRuleCode } from "@/lib/format";

export const dynamic = "force-dynamic";

/**
 * The Command Dashboard.
 *
 * Composed from six independent server-side reads issued in parallel. Each
 * returns a `Result` rather than throwing, so one failing query degrades one
 * panel instead of blanking the page — which matters here more than anywhere
 * else, because this is the screen someone opens to find out whether anything is
 * wrong.
 *
 * The figures are computed in SQL across the whole corpus (see
 * `backend/app/services/analytics.py`), not derived from whatever page of
 * records the client happened to fetch. That distinction is the difference
 * between a dashboard and a decoration.
 */
export default async function DashboardPage() {
  const [summary, timeseries, districts, rules, queueHealth, queue] = await Promise.all([
    getSummary(),
    getTimeseries(30),
    getDistrictBreakdown(),
    getRuleFrequency(7),
    getQueueHealth(),
    getReviewQueue("all", { limit: 6 }),
  ]);

  if (summary.error) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Command Dashboard" description="Fleet-wide status of every digitized land record." />
        <ErrorPanel message={summary.error.message} unreachable={summary.error.unreachable} />
      </div>
    );
  }

  const s = summary.data;
  const decidedTotal = (s.by_status.approved ?? 0) + (s.by_status.rejected ?? 0);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Command Dashboard"
        description={
          <>
            {formatCount(s.total_parcels)} parcels extracted from {formatCount(s.total_documents)} scans
            across {s.districts_covered} districts, covering {formatHectares(s.total_area_hectares)}.
          </>
        }
        actions={
          <>
            <LinkButton href="/queue" variant="secondary" icon={ListChecks}>
              Review queue
            </LinkButton>
            <LinkButton href="/analytics" variant="primary" icon={BarChart3}>
              Full analytics
            </LinkButton>
          </>
        }
      />

      {/* -- KPI row: five headline numbers, no charts. The most common charting
             mistake is drawing eight coloured bars when the story is one figure. */}
      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatTile
          label="Records processed"
          value={formatCount(s.total_parcels)}
          icon={FileStack}
          accent="navy"
          hint={`${formatCount(s.total_pages)} pages ingested`}
        />
        <StatTile
          label="Straight-through"
          value={s.straight_through_rate}
          suffix="%"
          icon={CheckCircle2}
          accent="good"
          hint={`${formatCount(s.auto_validated)} cleared with no human touch`}
        />
        <StatTile
          label="Median confidence"
          value={s.median_confidence !== null ? formatPercent(s.median_confidence) : "—"}
          icon={Gauge}
          accent="series"
          hint={
            s.avg_confidence !== null
              ? `Mean ${formatPercent(s.avg_confidence)} — the gap is the bimodal split between clean print and faded handwriting`
              : "No scored extractions yet"
          }
        />
        <StatTile
          label="Awaiting a decision"
          value={formatCount(queueHealth.data?.total_open ?? s.needs_review + s.flagged)}
          icon={ListChecks}
          accent="warning"
          hint={`${formatCount(s.unassigned_count)} unclaimed in the shared pool`}
        />
        <StatTile
          label="Past service level"
          value={formatCount(s.overdue_count)}
          icon={Timer}
          accent={s.overdue_count > 0 ? "critical" : "good"}
          hint={s.overdue_count > 0 ? "Open beyond the SLA for their priority band" : "Nothing overdue"}
        />
      </section>

      {/* -- Trend + composition ------------------------------------------------ */}
      <section className="grid grid-cols-1 gap-6 xl:grid-cols-[1.55fr_1fr]">
        <Card>
          <CardHeader
            title="Throughput, last 30 days"
            subtitle="Records ingested, decisions taken, and corrections keyed — all counts of records, so one axis."
            icon={BarChart3}
          />
          <div className="px-4 pb-4 pt-3">
            {timeseries.error ? (
              <ErrorPanel message={timeseries.error.message} unreachable={timeseries.error.unreachable} />
            ) : (
              <TrendChart
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

        <Card>
          <CardHeader
            title="Adjudication status"
            subtitle={`${formatCount(decidedTotal)} of ${formatCount(s.total_parcels)} records decided`}
            icon={Layers}
          />
          <div className="px-4 py-5">
            <DonutChart
              centerLabel="Records"
              segments={[
                { label: "Approved", value: s.by_status.approved ?? 0, color: "var(--status-good)" },
                { label: "In review", value: s.by_status.in_review ?? 0, color: "var(--series-1)" },
                { label: "Escalated", value: s.by_status.escalated ?? 0, color: "var(--status-serious)" },
                { label: "Rejected", value: s.by_status.rejected ?? 0, color: "var(--status-critical)" },
                { label: "Pending triage", value: s.by_status.pending ?? 0, color: "var(--ink-muted)" },
              ]}
            />
          </div>

          <div className="border-t border-line px-4 py-4">
            <p className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              Open work by triage band
            </p>
            <ProportionBar
              segments={[
                {
                  label: "Critical",
                  value: queueHealth.data?.buckets.find((b) => b.priority === "critical")?.open ?? 0,
                  color: "var(--status-critical)",
                },
                {
                  label: "High",
                  value: queueHealth.data?.buckets.find((b) => b.priority === "high")?.open ?? 0,
                  color: "var(--status-serious)",
                },
                {
                  label: "Normal",
                  value: queueHealth.data?.buckets.find((b) => b.priority === "normal")?.open ?? 0,
                  color: "var(--status-warning)",
                },
                {
                  label: "Low",
                  value: queueHealth.data?.buckets.find((b) => b.priority === "low")?.open ?? 0,
                  color: "var(--ink-muted)",
                },
              ]}
            />
          </div>
        </Card>
      </section>

      {/* -- Next up + district + rules ---------------------------------------- */}
      <section className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-1">
          <CardHeader
            title="Next in the queue"
            subtitle="Highest triage score first"
            icon={ListChecks}
            action={
              <Link
                href="/queue"
                className="inline-flex items-center gap-1 text-xs font-semibold text-series-1 hover:underline"
              >
                Open queue <ArrowRight className="h-3 w-3" aria-hidden />
              </Link>
            }
          />
          {queue.error ? (
            <ErrorPanel className="m-4" message={queue.error.message} unreachable={queue.error.unreachable} />
          ) : queue.data.items.length === 0 ? (
            <EmptyState
              icon={CheckCircle2}
              title="Queue is clear"
              description="Every record has been adjudicated. Nothing is waiting on a human."
            />
          ) : (
            <ul className="divide-y divide-line">
              {queue.data.items.map((parcel) => (
                <li key={parcel.id}>
                  <Link
                    href={`/parcels/${parcel.id}`}
                    className="flex items-start gap-3 px-4 py-3 transition-colors hover:bg-surface-sunken"
                  >
                    <span className="mt-1.5">
                      <TrafficLightDot status={deriveTrafficLight(parcel)} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-[13px] font-semibold text-ink-primary">
                          {parcel.village ?? "Unknown village"}
                        </span>
                        <PriorityBadge priority={parcel.priority} score={parcel.priority_score} />
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-ink-muted">
                        {parcel.district ?? "—"} · Survey {parcel.survey_number ?? "—"} ·{" "}
                        {parcel.validation_issue_count} finding
                        {parcel.validation_issue_count === 1 ? "" : "s"}
                      </span>
                      <span className="mt-1 block">
                        <SlaBadge dueAt={parcel.sla_due_at} status={parcel.review_status} />
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="xl:col-span-1">
          <CardHeader
            title="Districts by volume"
            subtitle="Records extracted per district"
            icon={Layers}
          />
          <div className="px-4 py-4">
            {districts.error ? (
              <ErrorPanel message={districts.error.message} unreachable={districts.error.unreachable} />
            ) : (
              <BarList
                data={districts.data.slice(0, 8).map((row) => ({
                  label: row.district ?? "Unknown",
                  sublabel: row.state ?? undefined,
                  value: row.total,
                  href: `/records?district=${encodeURIComponent(row.district ?? "")}`,
                }))}
                emptyMessage="No districts have records yet."
              />
            )}
          </div>
        </Card>

        <Card className="xl:col-span-1">
          <CardHeader
            title="Most-fired validation rules"
            subtitle="Read across a district this is a quality report on the registers themselves"
            icon={AlertTriangle}
            action={
              <Link
                href="/rules"
                className="inline-flex items-center gap-1 text-xs font-semibold text-series-1 hover:underline"
              >
                Rule catalogue <ArrowRight className="h-3 w-3" aria-hidden />
              </Link>
            }
          />
          <div className="px-4 py-4">
            {rules.error ? (
              <ErrorPanel message={rules.error.message} unreachable={rules.error.unreachable} />
            ) : (
              <BarList
                data={rules.data.map((rule) => ({
                  label: humaniseRuleCode(rule.rule_code),
                  value: rule.count,
                  // A status colour here because the value genuinely carries a
                  // state (how bad this rule's findings are), and the severity is
                  // written out in the sublabel so hue is never the only cue.
                  color: severityColor(rule.worst_severity),
                  sublabel: rule.worst_severity,
                }))}
                emptyMessage="No validation findings recorded."
              />
            )}
          </div>
        </Card>
      </section>

      {/* -- The savings claim, with its assumption attached --------------------- */}
      <Card className="border-brand-green/25 bg-gradient-to-br from-brand-green/[0.06] to-transparent">
        <div className="flex flex-wrap items-center justify-between gap-6 px-5 py-5">
          <div className="flex items-start gap-4">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-green/12">
              <Clock className="h-5 w-5 text-brand-green" strokeWidth={2} aria-hidden />
            </span>
            <div>
              <p className="text-[26px] font-bold leading-none tracking-tight text-ink-primary">
                {formatCount(Math.round(s.staff_hours_saved))} staff hours
              </p>
              <p className="mt-1.5 max-w-2xl text-sm text-ink-secondary">
                displaced by the {formatCount(s.auto_validated)} records the pipeline cleared without a
                human touch — at the department&apos;s own assumption of{" "}
                <strong className="font-semibold text-ink-primary">
                  {s.minutes_saved_per_record_assumption} minutes
                </strong>{" "}
                of manual keying and cross-checking per record. The assumption is configuration
                (<code className="font-mono text-xs">ADHIKAR_API_MINUTES_SAVED_PER_RECORD</code>), not a
                measurement, and travels with the figure so it is never quoted as one.
              </p>
            </div>
          </div>
          <div className="text-right">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              Corrections applied
            </p>
            <p className="mt-1 text-2xl font-bold text-ink-primary">{formatCount(s.corrections_applied)}</p>
            <p className="text-xs text-ink-muted">records touched by a human</p>
          </div>
        </div>
      </Card>
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
