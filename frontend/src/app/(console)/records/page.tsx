import type { Metadata } from "next";

import { RecordsTable } from "@/components/records/RecordsTable";
import { ErrorPanel, PageHeader } from "@/components/ui/Primitives";
import { getFacets, getSessionProfile, listParcels } from "@/lib/api";
import type { ParcelListFilters } from "@/types/parcel";

export const metadata: Metadata = { title: "Records" };
export const dynamic = "force-dynamic";

/**
 * The full records grid.
 *
 * Filters arrive as URL search params, are validated into a typed filter object
 * here, and are then passed to the API. Reading them from the URL rather than
 * from component state is what makes a filtered view a shareable link — see the
 * note on `RecordsTable`.
 */
export default async function RecordsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const one = (key: string): string | undefined => {
    const value = raw[key];
    return Array.isArray(value) ? value[0] : value;
  };

  const filters: ParcelListFilters = {
    q: one("q"),
    state: one("state"),
    district: one("district"),
    village: one("village"),
    review_status: one("review_status") as ParcelListFilters["review_status"],
    priority: one("priority") as ParcelListFilters["priority"],
    severity: one("severity") as ParcelListFilters["severity"],
    assigned_to: one("assigned_to"),
    unassigned: one("unassigned") === "true",
    overdue: one("overdue") === "true",
    open_only: one("open_only") === "true",
    sort: (one("sort") as ParcelListFilters["sort"]) ?? "priority",
    order: (one("order") as ParcelListFilters["order"]) ?? "desc",
    limit: 25,
    offset: Number(one("offset") ?? 0) || 0,
  };

  const [page, facets, profile] = await Promise.all([listParcels(filters), getFacets(), getSessionProfile()]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Records"
        description="Every parcel extracted from every scan, with the pipeline's verdict and the workflow's. Filters are reflected in the URL, so a filtered view is a link you can send to a colleague."
      />

      {page.error ? (
        <ErrorPanel message={page.error.message} unreachable={page.error.unreachable} />
      ) : (
        <RecordsTable page={page.data} facets={facets.data ?? null} profile={profile} />
      )}
    </div>
  );
}
