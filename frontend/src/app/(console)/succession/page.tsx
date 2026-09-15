import { FileQuestion, GitBranch, Scale, ShieldQuestion } from "lucide-react";
import type { Metadata } from "next";

import { StatTile } from "@/components/charts/StatTile";
import { SuccessionCasesTable } from "@/components/succession/SuccessionCasesTable";
import { Card, CardHeader, ErrorPanel, PageHeader } from "@/components/ui/Primitives";
import { getSessionProfile, getSuccessionSummary, listSuccessionCases } from "@/lib/api";
import type { SuccessionCaseFilters } from "@/types/succession";

export const metadata: Metadata = { title: "Ownership Succession" };
export const dynamic = "force-dynamic";

/**
 * The succession queue: every filed case, worst-risk first, with the same
 * "filters live in the URL" discipline the records grid uses.
 *
 * The four tiles up top intentionally have no "fraud detected" tile. There is
 * nothing in the engine that produces that number, and adding a tile for it
 * would invent a metric the system does not compute.
 */
export default async function SuccessionQueuePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const one = (key: string): string | undefined => {
    const value = raw[key];
    return Array.isArray(value) ? value[0] : value;
  };

  const filters: SuccessionCaseFilters = {
    q: one("q"),
    state: one("state"),
    district: one("district"),
    outcome: one("outcome") as SuccessionCaseFilters["outcome"],
    risk_level: one("risk_level") as SuccessionCaseFilters["risk_level"],
    open_only: one("open_only") !== "false", // defaults to true: the queue is work, not an archive
    sort: (one("sort") as SuccessionCaseFilters["sort"]) ?? "risk",
    order: (one("order") as SuccessionCaseFilters["order"]) ?? "desc",
    limit: 50,
    offset: Number(one("offset") ?? 0) || 0,
  };

  const [page, summary] = await Promise.all([
    listSuccessionCases(filters),
    getSuccessionSummary(filters.district),
    getSessionProfile(),
  ]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Ownership Succession"
        description="Cases where a recorded transfer of land followed an owner's death. Every case here is a documentary-consistency assessment, not a determination of who legally inherits — that adjudication belongs to the revenue authority."
      />

      {summary.data && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatTile label="Total cases" value={String(summary.data.total_cases)} icon={GitBranch} accent="series" />
          <StatTile
            label="Open (need action)"
            value={String(summary.data.open_cases)}
            icon={ShieldQuestion}
            accent="warning"
          />
          <StatTile
            label="High / critical risk"
            value={String(
              (summary.data.by_risk_level.high ?? 0) + (summary.data.by_risk_level.critical ?? 0),
            )}
            icon={FileQuestion}
            accent="warning"
          />
          <StatTile
            label="Referred to revenue authority"
            value={String(summary.data.by_outcome.inconsistent ?? 0)}
            icon={Scale}
            accent="critical"
          />
        </div>
      )}

      <Card>
        <CardHeader
          title="Cases"
          subtitle="Worst risk first. Use ?open_only=false to include validated cases."
        />
        {page.error ? (
          <ErrorPanel message={page.error.message} unreachable={page.error.unreachable} className="m-4" />
        ) : (
          <SuccessionCasesTable cases={page.data.items} />
        )}
      </Card>
    </div>
  );
}
