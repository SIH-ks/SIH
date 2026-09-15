import { MapIcon } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { CadastralMap } from "@/components/map/CadastralMap";
import { Card, CardHeader, ErrorPanel, PageHeader } from "@/components/ui/Primitives";
import { getDistrictBreakdown, getFacets, getParcelGeoJson } from "@/lib/api";
import { cn, formatCount, formatScore } from "@/lib/format";

export const metadata: Metadata = { title: "Cadastral map" };
export const dynamic = "force-dynamic";

/**
 * The geospatial overview.
 *
 * A district filter in the URL narrows both the map and the sidebar, so the two
 * always describe the same set of records — the map showing one population while
 * the table beside it shows another is the single most confusing thing a GIS
 * dashboard can do.
 */
export default async function MapPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const district = Array.isArray(raw.district) ? raw.district[0] : raw.district;

  const [collection, districts, facets] = await Promise.all([
    getParcelGeoJson({ district, limit: 5000 }),
    getDistrictBreakdown(),
    getFacets(),
  ]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Cadastral map"
        description="Every parcel whose extracted area could be matched to a cadastral polygon, drawn on one map. Where the disagreements cluster is a fact about the survey record, not about any one document."
      />

      {collection.error ? (
        <ErrorPanel message={collection.error.message} unreachable={collection.error.unreachable} />
      ) : (
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1fr_280px]">
          <CadastralMap collection={collection.data} />

          <div className="flex flex-col gap-4">
            <Card>
              <CardHeader title="Jurisdiction" subtitle="Narrow the map to one district" icon={MapIcon} />
              <ul className="max-h-[420px] overflow-y-auto p-1.5">
                <li>
                  <Link
                    href="/map"
                    className={cn(
                      "block rounded-lg px-3 py-2 text-sm transition-colors",
                      !district ? "bg-brand-navy text-white dark:bg-series-1" : "hover:bg-surface-sunken",
                    )}
                  >
                    <span className="font-semibold">All districts</span>
                    <span
                      className={cn(
                        "ml-2 text-xs",
                        !district ? "text-white/70" : "text-ink-muted",
                      )}
                    >
                      {formatCount(collection.data.properties.total_matching_filter)}
                    </span>
                  </Link>
                </li>
                {(districts.data ?? []).map((row) => {
                  const active = district === row.district;
                  return (
                    <li key={`${row.state}-${row.district}`}>
                      <Link
                        href={`/map?district=${encodeURIComponent(row.district ?? "")}`}
                        className={cn(
                          "flex items-center justify-between gap-2 rounded-lg px-3 py-2 transition-colors",
                          active ? "bg-brand-navy text-white dark:bg-series-1" : "hover:bg-surface-sunken",
                        )}
                      >
                        <span className="min-w-0">
                          <span
                            className={cn(
                              "block truncate text-[13px] font-medium",
                              active ? "text-white" : "text-ink-primary",
                            )}
                          >
                            {row.district ?? "Unknown"}
                          </span>
                          <span className={cn("block text-[11px]", active ? "text-white/65" : "text-ink-muted")}>
                            {row.state ?? "—"}
                          </span>
                        </span>
                        <span
                          className={cn(
                            "shrink-0 font-mono text-xs tabular-nums",
                            active ? "text-white" : "text-ink-secondary",
                          )}
                        >
                          {row.total}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </Card>

            <Card>
              <CardHeader
                title="Geometry coverage"
                subtitle="What can and cannot be mapped today"
              />
              <dl className="flex flex-col gap-3 px-4 py-4 text-sm">
                <div className="flex items-baseline justify-between gap-3">
                  <dt className="text-ink-secondary">Drawn on the map</dt>
                  <dd className="font-mono font-semibold tabular-nums text-ink-primary">
                    {formatCount(collection.data.properties.returned)}
                  </dd>
                </div>
                <div className="flex items-baseline justify-between gap-3">
                  <dt className="text-ink-secondary">No matched polygon</dt>
                  <dd className="font-mono font-semibold tabular-nums text-ink-primary">
                    {formatCount(collection.data.properties.without_geometry)}
                  </dd>
                </div>
                {district && districts.data && (
                  <div className="flex items-baseline justify-between gap-3 border-t border-line pt-3">
                    <dt className="text-ink-secondary">Mean mismatch here</dt>
                    <dd className="font-mono font-semibold tabular-nums text-ink-primary">
                      {formatScore(districts.data.find((d) => d.district === district)?.avg_mismatch ?? null)}
                    </dd>
                  </div>
                )}
              </dl>
              <p className="border-t border-line px-4 py-3 text-xs leading-relaxed text-ink-muted">
                A record with no matched polygon is omitted rather than drawn with empty coordinates — a
                GeoJSON feature without geometry is valid and silently invisible, and an omission you
                can count is better than a feature you cannot see.
              </p>
            </Card>

            {facets.data && (
              <p className="px-1 text-xs text-ink-muted">
                {facets.data.states.length} state{facets.data.states.length === 1 ? "" : "s"} ·{" "}
                {facets.data.districts.length} districts in the corpus.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
