import Link from "next/link";
import { notFound } from "next/navigation";

import { ActionBadge, SeverityBadge } from "@/components/Badge";
import { DiscrepancyMap } from "@/components/DiscrepancyMap";
import { Gauge } from "@/components/Gauge";
import { HeaderBar } from "@/components/HeaderBar";
import { IconChevronLeft } from "@/components/icons";
import { Panel } from "@/components/Panel";
import { ApiError, getParcel, usingDemoData } from "@/lib/api";
import { formatArea } from "@/lib/utils";
import type { ValidationIssue } from "@/types/parcel";

/**
 * Parcel detail / review view: readout gauges, the discrepancy map, and the
 * validation findings as an event log — the three things a reviewer cross-checks
 * against the source scan before accepting or correcting a parcel.
 */
export default async function ParcelDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let parcel;
  try {
    parcel = await getParcel(id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  const demo = usingDemoData();
  const artifact = parcel.artifact_json as Record<string, unknown>;
  const geometry = (artifact.geometry as GeoJSON.Geometry | undefined) ?? null;
  const issues = (artifact.validation_issues as ValidationIssue[] | undefined) ?? [];

  return (
    <div className="flex flex-col gap-6">
      <HeaderBar breadcrumb={`Parcel / ${parcel.parcel_key}`} demo={demo} />

      <div>
        <Link
          href="/"
          className="inline-flex items-center gap-1 font-mono text-[11px] uppercase tracking-wider text-ink-dim hover:text-signal-cyan"
        >
          <IconChevronLeft className="h-3 w-3" /> Back to manifest
        </Link>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <h1 className="font-display text-xl font-semibold tracking-tight text-ink-primary">
            {parcel.village ?? "Unknown village"}
            <span className="mx-2 text-ink-faint">/</span>
            <span className="font-mono text-lg text-ink-secondary">
              Khata {parcel.khata_number ?? "—"} · Survey {parcel.survey_number ?? "—"}
            </span>
          </h1>
          <div className="flex items-center gap-2">
            <ActionBadge action={parcel.recommended_action} />
            <SeverityBadge severity={parcel.validation_highest_severity} />
          </div>
        </div>
      </div>

      <section className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <div className="flex flex-col gap-5">
          <Panel eyebrow="Instrumentation" title="Discrepancy Readout">
            <div className="flex items-center justify-around gap-4 p-5">
              <Gauge value={parcel.mismatch_score} label="Mismatch" higherIsBetter={false} />
              <Gauge value={parcel.confidence_score !== null ? parcel.confidence_score * 100 : null} label="Confidence" />
            </div>
            <dl className="grid grid-cols-2 gap-px border-t border-seam bg-seam text-xs">
              <Field label="Total area" value={formatArea(parcel.total_area_sq_metre)} />
              <Field label="Record format" value={artifact.record_format as string ?? parcel.parcel_key.split("/")[0] ?? "—"} />
              <Field label="State" value={parcel.state ?? "—"} />
              <Field label="District" value={parcel.district ?? "—"} />
            </dl>
          </Panel>

          <Panel eyebrow={`${issues.length} entries`} title="Validation Findings">
            {issues.length === 0 ? (
              <p className="px-4 py-8 text-center font-mono text-xs text-ink-faint">
                NO FINDINGS RECORDED ON THIS ARTIFACT
              </p>
            ) : (
              <ul className="divide-y divide-seam">
                {issues.map((issue, i) => (
                  <li key={i} className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <SeverityBadge severity={issue.severity} />
                      <span className="font-mono text-[10px] text-ink-dim">{issue.rule_code}</span>
                    </div>
                    <p className="mt-1.5 text-[13px] text-ink-primary">{issue.message}</p>
                    {issue.remediation && (
                      <p className="mt-1 font-mono text-[11px] italic text-ink-dim">→ {issue.remediation}</p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>

        <DiscrepancyMap geometry={geometry} mismatchScore={parcel.mismatch_score} parcelKey={parcel.parcel_key} />
      </section>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-hull px-4 py-2.5">
      <div className="font-mono text-[9px] uppercase tracking-[0.14em] text-ink-dim">{label}</div>
      <div className="mt-0.5 font-mono text-[13px] text-ink-primary">{value}</div>
    </div>
  );
}
