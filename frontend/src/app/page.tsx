import { HeaderBar } from "@/components/HeaderBar";
import { Panel } from "@/components/Panel";
import { ParcelTable } from "@/components/ParcelTable";
import { IconAlert, IconCheck, IconLayers } from "@/components/icons";
import { listParcels, usingDemoData } from "@/lib/api";

/**
 * The console landing view: fleet-wide stat readouts, then the full parcel manifest.
 * Server component — the initial fetch runs server-side so the console is populated
 * on first paint, matching the rest of the app's "instrument panel" feel (no
 * client-side loading spinner flash on load).
 */
export default async function DashboardPage() {
  let parcels: Awaited<ReturnType<typeof listParcels>> = [];
  let fetchError: string | null = null;

  try {
    parcels = await listParcels({ limit: 100 });
  } catch {
    fetchError = "BACKEND UNREACHABLE — expected FastAPI on :8000. Start it and reload.";
  }

  const demo = usingDemoData();

  const reviewCount = parcels.filter((p) => p.requires_human_review).length;
  const approvedCount = parcels.filter((p) => p.recommended_action === "auto_approve").length;
  const criticalCount = parcels.filter((p) => p.validation_highest_severity === "critical").length;
  const meanMismatch =
    parcels.length > 0
      ? parcels.reduce((sum, p) => sum + (p.mismatch_score ?? 0), 0) / parcels.length
      : null;

  return (
    <div className="flex flex-col gap-6">
      <HeaderBar demo={demo} />

      <section className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatPanel icon={<IconLayers className="h-4 w-4" />} label="Parcels Extracted" value={parcels.length} />
        <StatPanel
          icon={<IconAlert className="h-4 w-4" />}
          label="Awaiting Review"
          value={reviewCount}
          tone={reviewCount > 0 ? "amber" : "green"}
        />
        <StatPanel
          icon={<IconCheck className="h-4 w-4" />}
          label="Auto-Approved"
          value={approvedCount}
          tone="green"
        />
        <StatPanel
          icon={<IconAlert className="h-4 w-4" />}
          label="Critical Findings"
          value={criticalCount}
          tone={criticalCount > 0 ? "red" : "green"}
        />
      </section>

      {fetchError ? (
        <Panel eyebrow="System" title="Connection Fault">
          <div className="flex items-center gap-2 px-4 py-6 font-mono text-xs text-signal-amber">
            <IconAlert className="h-4 w-4 shrink-0" />
            {fetchError}
          </div>
        </Panel>
      ) : (
        <Panel eyebrow={`Mean mismatch ${meanMismatch !== null ? meanMismatch.toFixed(1) : "—"}/100`} title="Parcel Manifest" live>
          <div className="p-3.5">
            <ParcelTable parcels={parcels} />
          </div>
        </Panel>
      )}
    </div>
  );
}

function StatPanel({
  icon,
  label,
  value,
  tone = "cyan",
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  tone?: "cyan" | "amber" | "green" | "red";
}) {
  const toneClass = {
    cyan: "text-signal-cyan",
    amber: "text-signal-amber",
    green: "text-signal-green",
    red: "text-signal-red",
  }[tone];

  return (
    <div className="hud-corners relative border border-seam bg-hull px-4 py-3.5 text-signal-cyan">
      <span className="corner-tl" />
      <span className="corner-br" />
      <div className={`flex items-center gap-1.5 ${toneClass}`}>
        {icon}
        <span className="font-mono text-[10px] uppercase tracking-[0.14em] text-ink-dim">{label}</span>
      </div>
      <div className={`mt-1.5 font-mono text-3xl font-semibold tabular-nums ${toneClass}`}>
        {String(value).padStart(2, "0")}
      </div>
    </div>
  );
}
