import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { ActionBadge, SeverityBadge, TrafficLightBadge, deriveTrafficLight } from "@/components/Badge";
import { DiscrepancyMap } from "@/components/DiscrepancyMap";
import { Gauge } from "@/components/Gauge";
import { ValidationWorkspace } from "@/components/ValidationWorkspace";
import { ApiError, getParcel, usingDemoData } from "@/lib/api";
import { demoNeighbourGeometries } from "@/lib/demoData";
import type { ValidationIssue } from "@/types/parcel";

/**
 * Split-Screen Validation Workspace: the record's identity strip, a two-gauge
 * discrepancy readout, the document viewer / extracted-data split-screen itself,
 * and a secondary section for the geospatial cross-reference and the full
 * validation findings list.
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
  const issues = (artifact.validation_issues as ValidationIssue[] | undefined) ?? [];
  const fileName = `${parcel.village ?? "record"}-${parcel.survey_number ?? parcel.khata_number ?? id.slice(0, 8)}.pdf`;
  // Neighbour polygons are a demo-only visual aid for the map's overlap story --
  // real neighbour geometry isn't wired on the backend yet (see demoData.ts).
  const neighbourGeometries = demo ? demoNeighbourGeometries(id) : [];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-sm font-medium text-slate-500 hover:text-navy-700"
        >
          <ChevronLeft className="h-4 w-4" /> Back to dashboard
        </Link>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">
              {parcel.village ?? "Unknown village"}
            </h1>
            <p className="mt-0.5 text-sm text-slate-500">
              Khata {parcel.khata_number ?? "—"} · Survey {parcel.survey_number ?? "—"} · {parcel.parcel_key}
              {demo && (
                <span className="ml-2 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 ring-1 ring-inset ring-amber-200">
                  Demo data
                </span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <TrafficLightBadge status={deriveTrafficLight(parcel)} />
            <ActionBadge action={parcel.recommended_action} />
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-8 rounded-xl border border-slate-200 bg-white px-6 py-5 shadow-card">
        <Gauge value={parcel.mismatch_score} label="Mismatch" higherIsBetter={false} />
        <Gauge
          value={parcel.confidence_score !== null ? parcel.confidence_score * 100 : null}
          label="Confidence"
        />
        <div className="min-w-[180px] flex-1 text-sm text-slate-500">
          <p>
            <span className="font-semibold text-slate-700">Mismatch</span> compares the extracted total area
            against the matched cadastral polygon — lower is better, 0 is an exact match.
          </p>
          <p className="mt-1.5">
            <span className="font-semibold text-slate-700">Confidence</span> blends OCR legibility, extraction
            certainty, arithmetic integrity, and geometric agreement into one triage score.
          </p>
        </div>
      </div>

      <ValidationWorkspace parcel={parcel} fileName={fileName} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.3fr_1fr]">
        <DiscrepancyMap
          geometry={parcel.geometry}
          mismatchScore={parcel.mismatch_score}
          parcelKey={parcel.parcel_key}
          neighbourGeometries={neighbourGeometries}
        />

        <div className="rounded-xl border border-slate-200 bg-white shadow-card">
          <div className="border-b border-slate-200 px-4 py-3">
            <h2 className="text-sm font-semibold text-slate-700">Validation Findings</h2>
            <p className="text-xs text-slate-400">{issues.length} entries from the rule engine</p>
          </div>
          {issues.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-slate-400">No findings recorded on this artifact.</p>
          ) : (
            <ul className="max-h-[360px] divide-y divide-slate-100 overflow-y-auto">
              {issues.map((issue, i) => (
                <li key={i} className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <SeverityBadge severity={issue.severity} />
                    <span className="font-mono text-[10px] text-slate-400">{issue.rule_code}</span>
                  </div>
                  <p className="mt-1.5 text-[13px] text-slate-700">{issue.message}</p>
                  {issue.remediation && (
                    <p className="mt-1 text-xs italic text-slate-400">→ {issue.remediation}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
