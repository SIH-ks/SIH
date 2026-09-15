import {
  ArrowRight,
  CheckCircle2,
  ChevronLeft,
  Download,
  FileJson,
  History,
  Lightbulb,
  Printer,
  ShieldAlert,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { DiscrepancyMap } from "@/components/DiscrepancyMap";
import { ParcelWorkspace } from "@/components/parcel/ParcelWorkspace";
import { WorkflowActions } from "@/components/parcel/WorkflowActions";
import { ParcelSuccessionPanel } from "@/components/succession/ParcelSuccessionPanel";
import {
  ActionBadge,
  PriorityBadge,
  SeverityBadge,
  SlaBadge,
  StatusBadge,
  TrafficLightBadge,
  deriveTrafficLight,
} from "@/components/ui/Badge";
import {
  Card,
  CardHeader,
  EmptyState,
  ErrorPanel,
  Field,
  LinkButton,
  PageHeader,
} from "@/components/ui/Primitives";
import {
  NOT_FOUND,
  getParcel,
  getParcelEvents,
  getParcelSuccessionCases,
  getSessionProfile,
} from "@/lib/api";
import { cn, formatArea, formatDateTime, formatPercent, formatRelative, formatScore, titleCase } from "@/lib/format";
import type { ValidationIssue } from "@/types/parcel";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const parcel = await getParcel(id);
  if (!parcel.data) return { title: "Record" };
  return { title: `${parcel.data.village ?? "Record"} · Survey ${parcel.data.survey_number ?? "—"}` };
}

/**
 * One record, in full: the split-screen workspace, the two scores that drive
 * triage, the workflow controls, the rule engine's findings, the cadastral
 * cross-reference, and the record's own audit trail.
 *
 * Laid out so the reviewer's eye lands on the *decision* first (identity strip,
 * scores, action bar), the evidence second (scan and fields), and the supporting
 * detail third — rather than making them scroll past a map to find the Approve
 * button.
 */
export default async function ParcelDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [parcel, events, profile, successionCases] = await Promise.all([
    getParcel(id),
    getParcelEvents(id),
    getSessionProfile(),
    getParcelSuccessionCases(id),
  ]);

  if (parcel.error) {
    if (parcel.error.status === NOT_FOUND) notFound();
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Record" />
        <ErrorPanel message={parcel.error.message} unreachable={parcel.error.unreachable} />
      </div>
    );
  }

  const record = parcel.data;
  const issues = (record.artifact_json.validation_issues as ValidationIssue[] | undefined) ?? [];
  const ranked = [...issues].sort(
    (a, b) => severityRank(b.severity) - severityRank(a.severity),
  );

  return (
    <div className="flex flex-col gap-5">
      {/* -- Identity strip ----------------------------------------------------- */}
      <div>
        <Link
          href="/queue"
          className="inline-flex items-center gap-1 text-xs font-medium text-ink-muted transition-colors hover:text-series-1"
        >
          <ChevronLeft className="h-3.5 w-3.5" aria-hidden /> Back to the queue
        </Link>

        <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-[22px] font-bold tracking-tight text-ink-primary">
              {record.village ?? "Unknown village"}
            </h1>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink-secondary">
              <span>{record.district ?? "—"}</span>
              <span className="text-ink-muted">·</span>
              <span>Khata {record.khata_number ?? "—"}</span>
              <span className="text-ink-muted">·</span>
              <span>Survey {record.survey_number ?? "—"}</span>
              <code className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[11px] text-ink-muted">
                {record.parcel_key}
              </code>
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <LinkButton
              href={`/api/proxy/exports/parcels/${record.id}/report.html`}
              variant="secondary"
              size="sm"
              icon={Printer}
              external
            >
              Verification report
            </LinkButton>
            <LinkButton
              href={`/api/proxy/exports/parcels/${record.id}/artifact.json`}
              variant="secondary"
              size="sm"
              icon={FileJson}
              external
            >
              Artifact JSON
            </LinkButton>
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <TrafficLightBadge status={deriveTrafficLight(record)} />
          <StatusBadge status={record.review_status} />
          <PriorityBadge priority={record.priority} score={record.priority_score} />
          <ActionBadge action={record.recommended_action} />
          <SlaBadge dueAt={record.sla_due_at} status={record.review_status} />
          {record.has_human_corrections && (
            <span className="rounded-full bg-series-2/10 px-2.5 py-1 text-xs font-semibold text-series-2 ring-1 ring-inset ring-series-2/25">
              {record.correction_count} human correction{record.correction_count === 1 ? "" : "s"} applied
            </span>
          )}
        </div>
      </div>

      {/* -- Scores + triage explanation + actions ------------------------------ */}
      <section className="grid grid-cols-1 gap-5 lg:grid-cols-[1fr_320px]">
        <Card className="flex flex-col gap-5 px-5 py-5 sm:flex-row sm:items-center">
          <div className="flex gap-8">
            <ScoreDial
              label="Mismatch"
              value={record.mismatch_score}
              display={formatScore(record.mismatch_score)}
              percent={record.mismatch_score === null ? null : Math.min(record.mismatch_score, 100)}
              higherIsBetter={false}
              caption="vs the cadastral polygon"
            />
            <ScoreDial
              label="Confidence"
              value={record.confidence_score}
              display={record.confidence_score === null ? "—" : formatPercent(record.confidence_score)}
              percent={record.confidence_score === null ? null : record.confidence_score * 100}
              higherIsBetter
              caption="OCR + extraction + geometry"
            />
          </div>

          <div className="min-w-0 flex-1 border-t border-line pt-4 sm:border-l sm:border-t-0 sm:pl-6 sm:pt-0">
            <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-ink-muted">
              <Lightbulb className="h-3.5 w-3.5" aria-hidden />
              Why this record is where it is in the queue
            </p>
            <ul className="mt-2 flex flex-col gap-1.5">
              {record.triage_reasons.map((reason) => (
                <li key={reason} className="flex items-start gap-2 text-[13px] leading-snug text-ink-secondary">
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-ink-muted" aria-hidden />
                  {reason}
                </li>
              ))}
            </ul>
            <p className="mt-2.5 text-[11px] leading-relaxed text-ink-muted">
              Triage score {record.priority_score.toFixed(1)} / 100, computed from the pipeline's own
              scores — not a learned ranker, so the reason is always a sentence.
            </p>
          </div>
        </Card>

        <WorkflowActions parcel={record} profile={profile} />
      </section>

      {/* -- The workspace ------------------------------------------------------ */}
      <ParcelWorkspace parcel={record} profile={profile} />

      {/* -- Ownership succession, when a case has been filed against this parcel */}
      {successionCases.data && <ParcelSuccessionPanel cases={successionCases.data} />}

      {/* -- Findings + identity detail ----------------------------------------- */}
      <section className="grid grid-cols-1 gap-5 lg:grid-cols-[1.15fr_1fr]">
        <Card>
          <CardHeader
            title={`Validation findings (${issues.length})`}
            subtitle="Recomputed by the rule engine after every correction — never a stale copy"
            icon={ShieldAlert}
            action={
              <Link href="/rules" className="text-xs font-semibold text-series-1 hover:underline">
                Rule catalogue →
              </Link>
            }
          />
          {ranked.length === 0 ? (
            <EmptyState
              icon={CheckCircle2}
              title="No findings on this record"
              description="Every enabled rule passed: the arithmetic is internally consistent, the ownership shares resolve, and the mutation chain is in order."
            />
          ) : (
            <ul className="max-h-[420px] divide-y divide-line overflow-y-auto">
              {ranked.map((issue, index) => (
                <li key={`${issue.rule_code}-${index}`} className="px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <SeverityBadge severity={issue.severity} />
                    <code className="font-mono text-[10px] text-ink-muted">{issue.rule_code}</code>
                    {issue.confidence < 1 && (
                      <span className="text-[10px] text-ink-muted">
                        rule confidence {Math.round(issue.confidence * 100)}%
                      </span>
                    )}
                  </div>
                  <p className="mt-1.5 text-[13px] leading-snug text-ink-primary">{issue.message}</p>

                  {(issue.observed || issue.expected) && (
                    <p className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
                      {issue.observed && (
                        <span className="rounded bg-status-critical-wash px-1.5 py-0.5 font-mono text-[11px] text-status-critical-ink">
                          found {issue.observed}
                        </span>
                      )}
                      {issue.expected && (
                        <>
                          <ArrowRight className="h-3 w-3 text-ink-muted" aria-hidden />
                          <span className="rounded bg-status-good-wash px-1.5 py-0.5 font-mono text-[11px] text-status-good-ink">
                            expected {issue.expected}
                          </span>
                        </>
                      )}
                    </p>
                  )}

                  {issue.remediation && (
                    <p className="mt-1.5 flex gap-1.5 text-xs leading-snug text-ink-muted">
                      <span aria-hidden>→</span>
                      <span className="italic">{issue.remediation}</span>
                    </p>
                  )}
                  <code className="mt-1.5 block break-anywhere text-[10px] text-ink-muted">
                    {issue.json_path}
                  </code>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="flex flex-col gap-5">
          <Card>
            <CardHeader title="Record detail" subtitle="The projected columns the console filters and sorts on" />
            <dl className="grid grid-cols-2 gap-4 px-4 py-4 sm:grid-cols-3">
              <Field label="Total area" value={formatArea(record.total_area_sq_metre)} mono />
              <Field label="Record format" value={titleCase(record.artifact_json.record_format as string)} />
              <Field label="State" value={record.state} />
              <Field label="Assigned to" value={record.assigned_to ? `@${record.assigned_to}` : "Unclaimed"} />
              <Field label="Ingested" value={formatRelative(record.created_at)} />
              <Field label="Last updated" value={formatRelative(record.updated_at)} />
              {record.document && (
                <>
                  <Field label="Source file" value={record.document.file_name} mono className="col-span-2" />
                  <Field label="Pages" value={record.document.page_count} />
                </>
              )}
            </dl>
          </Card>

          <DiscrepancyMap
            geometry={record.geometry}
            mismatchScore={record.mismatch_score}
            parcelKey={record.parcel_key}
          />
        </div>
      </section>

      {/* -- Audit trail --------------------------------------------------------- */}
      <Card>
        <CardHeader
          title="Audit trail for this record"
          subtitle="Append-only. A correction supersedes a value but never erases what it replaced."
          icon={History}
          action={
            <LinkButton
              href={`/api/proxy/exports/audit.csv`}
              variant="ghost"
              size="sm"
              icon={Download}
              external
            >
              Export
            </LinkButton>
          }
        />
        {events.error ? (
          <ErrorPanel className="m-4" message={events.error.message} unreachable={events.error.unreachable} />
        ) : events.data.length === 0 ? (
          <EmptyState
            icon={History}
            title="No human action recorded yet"
            description="Everything shown on this page is the pipeline's own output, untouched."
          />
        ) : (
          <ol className="relative px-4 py-4">
            {events.data.map((event, index) => (
              <li key={event.id} className="relative flex gap-4 pb-5 last:pb-0">
                {index !== events.data.length - 1 && (
                  <span className="absolute left-[11px] top-6 h-[calc(100%-1rem)] w-px bg-line" aria-hidden />
                )}
                <span
                  className={cn(
                    "z-10 mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold",
                    event.action === "status_changed"
                      ? "bg-status-good-wash text-status-good-ink"
                      : event.action === "corrected"
                        ? "bg-series-2/15 text-series-2"
                        : "bg-surface-sunken text-ink-muted",
                  )}
                >
                  {index + 1}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-baseline gap-x-2 text-[13px]">
                    <span className="font-semibold text-ink-primary">{titleCase(event.action)}</span>
                    <span className="text-ink-secondary">by @{event.reviewer}</span>
                    {event.reviewer_role && (
                      <span className="text-xs text-ink-muted">({event.reviewer_role})</span>
                    )}
                    <span className="text-xs text-ink-muted" title={formatDateTime(event.created_at)}>
                      · {formatRelative(event.created_at)}
                    </span>
                  </p>
                  {event.field_path !== "$" && (
                    <code className="mt-0.5 block break-anywhere text-[10px] text-ink-muted">
                      {event.field_path}
                    </code>
                  )}
                  {(event.previous_value?.value != null || event.new_value?.value != null) && (
                    <p className="mt-1 flex flex-wrap items-center gap-2 text-xs">
                      <span className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[11px] text-ink-muted line-through decoration-1">
                        {stringify(event.previous_value?.value)}
                      </span>
                      <ArrowRight className="h-3 w-3 text-ink-muted" aria-hidden />
                      <span className="rounded bg-status-good-wash px-1.5 py-0.5 font-mono text-[11px] font-semibold text-status-good-ink">
                        {stringify(event.new_value?.value)}
                      </span>
                    </p>
                  )}
                  {event.note && (
                    <p className="mt-1 break-anywhere text-xs italic text-ink-muted">“{event.note}”</p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}

/**
 * A radial score readout.
 *
 * Two dials rather than one because the scores answer different questions and
 * move independently: a record can be extracted with high confidence and still
 * disagree wildly with the survey map. The caption under each says which is
 * which, so the pair is never read as one composite "quality".
 */
function ScoreDial({
  label,
  value,
  display,
  percent,
  higherIsBetter,
  caption,
}: {
  label: string;
  value: number | null;
  display: string;
  percent: number | null;
  higherIsBetter: boolean;
  caption: string;
}) {
  const radius = 30;
  const circumference = 2 * Math.PI * radius;
  const filled = percent === null ? 0 : (Math.max(0, Math.min(percent, 100)) / 100) * circumference;

  const good = value === null ? false : higherIsBetter ? percent! >= 85 : percent! < 5;
  const bad = value === null ? false : higherIsBetter ? percent! < 60 : percent! >= 50;
  const stroke = value === null
    ? "var(--ink-muted)"
    : good
      ? "var(--status-good)"
      : bad
        ? "var(--status-critical)"
        : "var(--status-warning)";

  return (
    <div className="flex flex-col items-center">
      <div className="relative">
        <svg width={74} height={74} viewBox="0 0 74 74" className="-rotate-90" role="img" aria-label={`${label}: ${display}`}>
          <circle cx={37} cy={37} r={radius} fill="none" stroke="var(--surface-sunken)" strokeWidth={7} />
          <circle
            cx={37}
            cy={37}
            r={radius}
            fill="none"
            stroke={stroke}
            strokeWidth={7}
            strokeLinecap="round"
            strokeDasharray={`${filled} ${circumference - filled}`}
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-sm font-bold tabular-nums text-ink-primary">
          {display}
        </span>
      </div>
      <p className="mt-1.5 text-xs font-semibold text-ink-primary">{label}</p>
      <p className="max-w-[110px] text-center text-[10px] leading-tight text-ink-muted">{caption}</p>
    </div>
  );
}

function severityRank(severity: string): number {
  return { info: 0, warning: 1, error: 2, critical: 3 }[severity] ?? 0;
}

function stringify(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
