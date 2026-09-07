import { AlertTriangle, Gauge, Sparkles, TrendingUp } from "lucide-react";

import { MetricWidget } from "@/components/MetricWidget";
import { ParcelTable } from "@/components/ParcelTable";
import { deriveTrafficLight } from "@/components/Badge";
import { listParcels, usingDemoData } from "@/lib/api";

/**
 * Command Dashboard: the landing view. Fleet-wide metric widgets frame the table,
 * then the full records manifest with its traffic-light status column does the
 * actual work of telling a reviewer where to look first.
 */
export default async function DashboardPage() {
  let parcels: Awaited<ReturnType<typeof listParcels>> = [];
  let fetchError: string | null = null;

  try {
    parcels = await listParcels({ limit: 100 });
  } catch {
    fetchError = "Could not reach the Adhikar API. Is the backend running on :8000?";
  }

  const demo = usingDemoData();
  const total = parcels.length;
  const flagged = parcels.filter((p) => deriveTrafficLight(p) === "red").length;
  const needsReview = parcels.filter((p) => deriveTrafficLight(p) === "yellow").length;
  const autoValidated = parcels.filter((p) => deriveTrafficLight(p) === "green").length;

  // "AI Accuracy" is approximated here as the mean extraction confidence across
  // every record that has one -- a defensible proxy in the absence of a labelled
  // ground-truth set, and exactly the number a reviewer cares about: how much to
  // trust the average record before opening it.
  const scored = parcels.filter((p) => p.confidence_score !== null);
  const aiAccuracy =
    scored.length > 0
      ? Math.round((scored.reduce((sum, p) => sum + (p.confidence_score ?? 0), 0) / scored.length) * 1000) / 10
      : null;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Command Dashboard</h1>
        <p className="mt-1 text-sm text-slate-500">
          Real-time overview of every digitized land record and its validation status.
          {demo && (
            <span className="ml-2 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700 ring-1 ring-inset ring-amber-200">
              Demo data
            </span>
          )}
        </p>
      </div>

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricWidget icon={TrendingUp} label="Processing Volume" value={total} suffix="records" tone="navy" />
        <MetricWidget
          icon={Sparkles}
          label="AI Accuracy"
          value={aiAccuracy !== null ? aiAccuracy : "—"}
          suffix={aiAccuracy !== null ? "%" : undefined}
          tone="green"
        />
        <MetricWidget icon={Gauge} label="Auto-Validated" value={autoValidated} tone="green" />
        <MetricWidget
          icon={AlertTriangle}
          label="Flagged for Review"
          value={needsReview + flagged}
          tone={flagged > 0 ? "red" : "amber"}
        />
      </section>

      {fetchError ? (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-800">
          {fetchError}
        </div>
      ) : (
        <ParcelTable parcels={parcels} />
      )}
    </div>
  );
}
