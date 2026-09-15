"use client";

import {
  ArrowUpDown,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Download,
  FileSearch,
  Loader2,
  Search,
  SlidersHorizontal,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState, useTransition } from "react";

import {
  ConfidenceMeter,
  Button,
  EmptyState,
} from "@/components/ui/Primitives";
import {
  PriorityBadge,
  SlaBadge,
  StatusBadge,
  TrafficLightBadge,
  deriveTrafficLight,
} from "@/components/ui/Badge";
import { useToast } from "@/components/ui/Toast";
import { bulkStatus, exportUrl } from "@/lib/client-api";
import { cn, formatArea, formatCount, formatDate } from "@/lib/format";
import { can, type SessionProfile } from "@/lib/session";
import type { Facets, Page, ParcelSummary } from "@/types/parcel";

/**
 * The records grid: filter, sort, page, select, act, export.
 *
 * **Filters live in the URL, not in component state.** That is what makes a
 * filtered view shareable — a Tehsildar can paste "every escalated record in
 * Belagavi" into an email and the recipient sees exactly that. It also means the
 * browser's back button behaves, and a refresh does not silently reset someone's
 * work.
 *
 * **The export uses the same query string as the table.** An export that covered
 * a different set of records than the screen it was launched from is the kind of
 * discrepancy that discredits a whole report, so the download URL is built from
 * the identical params rather than from a second, parallel filter object.
 */

const SORT_OPTIONS = [
  { value: "priority", label: "Triage priority" },
  { value: "updated_at", label: "Last updated" },
  { value: "created_at", label: "Date ingested" },
  { value: "mismatch", label: "Cadastral mismatch" },
  { value: "confidence", label: "Extraction confidence" },
  { value: "area", label: "Total area" },
  { value: "village", label: "Village (A–Z)" },
] as const;

const STATUS_OPTIONS = [
  { value: "", label: "Any status" },
  { value: "pending", label: "Pending triage" },
  { value: "in_review", label: "In review" },
  { value: "escalated", label: "Escalated" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
];

const PRIORITY_OPTIONS = [
  { value: "", label: "Any priority" },
  { value: "critical", label: "Critical" },
  { value: "high", label: "High" },
  { value: "normal", label: "Normal" },
  { value: "low", label: "Low" },
];

const SEVERITY_OPTIONS = [
  { value: "", label: "Any severity" },
  { value: "critical", label: "Critical findings" },
  { value: "error", label: "Errors" },
  { value: "warning", label: "Warnings" },
  { value: "info", label: "Info only" },
];

export function RecordsTable({
  page,
  facets,
  profile,
  showBulkActions = true,
}: {
  page: Page<ParcelSummary>;
  facets: Facets | null;
  profile: SessionProfile | null;
  showBulkActions?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const toast = useToast();
  const [isPending, startTransition] = useTransition();

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [showFilters, setShowFilters] = useState(false);
  const [search, setSearch] = useState(params.get("q") ?? "");

  const canApprove = can.approve(profile?.role) && showBulkActions;

  const current = useMemo(() => {
    const entries: Record<string, string> = {};
    params.forEach((value, key) => {
      entries[key] = value;
    });
    return entries;
  }, [params]);

  /** Rewrite the URL with `patch` applied. Any filter change resets the offset —
   * staying on page 4 of a result set that now has two pages shows an empty
   * table and reads as "no results". */
  const update = (patch: Record<string, string | number | undefined | null>) => {
    const next = new URLSearchParams(params.toString());
    for (const [key, value] of Object.entries(patch)) {
      if (value === undefined || value === null || value === "") next.delete(key);
      else next.set(key, String(value));
    }
    if (!("offset" in patch)) next.delete("offset");
    setSelected(new Set());
    startTransition(() => router.push(`${pathname}?${next.toString()}`));
  };

  const activeFilterCount = ["district", "state", "review_status", "priority", "severity", "overdue", "unassigned"]
    .filter((key) => current[key])
    .length;

  const allOnPageSelected = page.items.length > 0 && page.items.every((row) => selected.has(row.id));

  const toggleAll = () => {
    setSelected(allOnPageSelected ? new Set() : new Set(page.items.map((row) => row.id)));
  };

  const toggleOne = (id: string) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const runBulk = async (status: string, verb: string) => {
    if (selected.size === 0) return;
    setBulkBusy(true);
    try {
      const result = await bulkStatus([...selected], status, `Bulk ${verb} from the records view`);
      if (result.updated.length > 0) {
        toast.success(
          `${result.updated.length} record${result.updated.length === 1 ? "" : "s"} ${verb}`,
          result.skipped.length > 0
            ? `${result.skipped.length} skipped — see the reasons below.`
            : undefined,
        );
      }
      // Every skipped id is surfaced with its reason rather than swallowed: a
      // bulk action that silently dropped records would be an audit failure.
      for (const skip of result.skipped.slice(0, 3)) {
        toast.push({ tone: "warning", title: "Skipped", description: skip.reason });
      }
      setSelected(new Set());
      startTransition(() => router.refresh());
    } catch (error) {
      toast.error("Bulk action failed", error instanceof Error ? error.message : undefined);
    } finally {
      setBulkBusy(false);
    }
  };

  const limit = page.limit;
  const pageNumber = Math.floor(page.offset / limit) + 1;
  const pageCount = Math.max(1, Math.ceil(page.total / limit));

  return (
    <div className="flex flex-col gap-4">
      {/* -- Filter row -------------------------------------------------------- */}
      <div className="flex flex-wrap items-center gap-2">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            update({ q: search });
          }}
          className="relative min-w-[260px] flex-1 sm:max-w-md"
        >
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted"
            aria-hidden
          />
          <input
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search village, district, khata, survey no…"
            aria-label="Search records"
            className="h-9 w-full rounded-lg border border-line-strong bg-surface-card pl-9 pr-3 text-sm text-ink-primary outline-none transition-colors placeholder:text-ink-muted focus:border-series-1"
          />
        </form>

        <Button
          variant={showFilters || activeFilterCount > 0 ? "primary" : "secondary"}
          size="sm"
          icon={SlidersHorizontal}
          onClick={() => setShowFilters((current) => !current)}
        >
          Filters{activeFilterCount > 0 && ` · ${activeFilterCount}`}
        </Button>

        <label className="flex items-center gap-1.5 text-xs text-ink-secondary">
          <ArrowUpDown className="h-3.5 w-3.5 text-ink-muted" aria-hidden />
          <span className="sr-only sm:not-sr-only">Sort</span>
          <select
            value={current.sort ?? "priority"}
            onChange={(event) => update({ sort: event.target.value })}
            className="h-9 rounded-lg border border-line-strong bg-surface-card px-2.5 text-xs text-ink-primary outline-none focus:border-series-1"
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <a
          href={exportUrl("/exports/parcels.csv", current)}
          className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line-strong bg-surface-card px-3 text-xs font-semibold text-ink-primary transition-colors hover:bg-surface-sunken"
          title="Downloads exactly the records this filter selects"
        >
          <Download className="h-3.5 w-3.5" aria-hidden />
          Export CSV
        </a>
      </div>

      {showFilters && (
        <div className="grid animate-fade-up grid-cols-2 gap-3 rounded-xl border border-line bg-surface-card p-4 md:grid-cols-4 lg:grid-cols-6">
          <FilterSelect
            label="District"
            value={current.district ?? ""}
            onChange={(value) => update({ district: value })}
            options={[
              { value: "", label: "All districts" },
              ...(facets?.districts ?? []).map((d) => ({ value: d, label: d })),
            ]}
          />
          <FilterSelect
            label="Status"
            value={current.review_status ?? ""}
            onChange={(value) => update({ review_status: value })}
            options={STATUS_OPTIONS}
          />
          <FilterSelect
            label="Priority"
            value={current.priority ?? ""}
            onChange={(value) => update({ priority: value })}
            options={PRIORITY_OPTIONS}
          />
          <FilterSelect
            label="Finding severity"
            value={current.severity ?? ""}
            onChange={(value) => update({ severity: value })}
            options={SEVERITY_OPTIONS}
          />
          <FilterToggle
            label="Past SLA only"
            checked={current.overdue === "true"}
            onChange={(checked) => update({ overdue: checked ? "true" : undefined })}
          />
          <FilterToggle
            label="Unclaimed only"
            checked={current.unassigned === "true"}
            onChange={(checked) => update({ unassigned: checked ? "true" : undefined })}
          />

          {activeFilterCount > 0 && (
            <button
              type="button"
              onClick={() => {
                setSearch("");
                startTransition(() => router.push(pathname));
              }}
              className="col-span-2 inline-flex items-center gap-1.5 self-end justify-self-start rounded-lg px-2 py-1.5 text-xs font-semibold text-series-1 hover:underline md:col-span-1"
            >
              <X className="h-3.5 w-3.5" aria-hidden /> Clear all filters
            </button>
          )}
        </div>
      )}

      {/* -- Bulk action bar --------------------------------------------------- */}
      {canApprove && selected.size > 0 && (
        <div className="flex animate-fade-up flex-wrap items-center gap-3 rounded-xl border border-series-1/30 bg-series-1/[0.06] px-4 py-2.5">
          <span className="text-sm font-semibold text-ink-primary">
            {selected.size} selected
          </span>
          <span className="text-xs text-ink-muted">Applies one decision to all of them, individually audited.</span>
          <div className="ml-auto flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" disabled={bulkBusy} onClick={() => runBulk("in_review", "claimed")}>
              Claim for review
            </Button>
            <Button
              size="sm"
              variant="primary"
              icon={bulkBusy ? Loader2 : CheckCircle2}
              disabled={bulkBusy}
              onClick={() => runBulk("approved", "approved")}
              className={bulkBusy ? "[&_svg]:animate-spin" : undefined}
            >
              Approve
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {/* -- Table -------------------------------------------------------------- */}
      <div
        className={cn(
          "overflow-hidden rounded-xl border border-line bg-surface-card shadow-card transition-opacity",
          isPending && "opacity-60",
        )}
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1040px] text-left text-sm">
            <thead className="border-b border-line bg-surface-sunken text-[11px] uppercase tracking-wide text-ink-muted">
              <tr>
                {canApprove && (
                  <th scope="col" className="w-10 px-4 py-2.5">
                    <input
                      type="checkbox"
                      checked={allOnPageSelected}
                      onChange={toggleAll}
                      aria-label="Select all records on this page"
                      className="h-3.5 w-3.5 rounded border-line-strong accent-[var(--series-1)]"
                    />
                  </th>
                )}
                <th scope="col" className="px-4 py-2.5 font-semibold">Quality</th>
                <th scope="col" className="px-4 py-2.5 font-semibold">Parcel</th>
                <th scope="col" className="px-4 py-2.5 font-semibold">Workflow</th>
                <th scope="col" className="px-4 py-2.5 font-semibold">Priority</th>
                <th scope="col" className="px-4 py-2.5 font-semibold">Area</th>
                <th scope="col" className="px-4 py-2.5 font-semibold">Confidence</th>
                <th scope="col" className="px-4 py-2.5 font-semibold">Findings</th>
                <th scope="col" className="px-4 py-2.5 font-semibold">Updated</th>
                <th scope="col" className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {page.items.map((parcel) => (
                <tr
                  key={parcel.id}
                  className={cn(
                    "transition-colors hover:bg-surface-sunken/60",
                    selected.has(parcel.id) && "bg-series-1/[0.05]",
                  )}
                >
                  {canApprove && (
                    <td className="px-4 py-3">
                      <input
                        type="checkbox"
                        checked={selected.has(parcel.id)}
                        onChange={() => toggleOne(parcel.id)}
                        aria-label={`Select ${parcel.parcel_key}`}
                        className="h-3.5 w-3.5 rounded border-line-strong accent-[var(--series-1)]"
                      />
                    </td>
                  )}
                  <td className="px-4 py-3">
                    <TrafficLightBadge status={deriveTrafficLight(parcel)} />
                  </td>
                  <td className="px-4 py-3">
                    <Link href={`/parcels/${parcel.id}`} className="group block">
                      <span className="block font-semibold text-ink-primary group-hover:text-series-1">
                        {parcel.village ?? "Unknown village"}
                      </span>
                      <span className="mt-0.5 block text-xs text-ink-muted">
                        {parcel.district ?? "—"} · Khata {parcel.khata_number ?? "—"} · Survey{" "}
                        {parcel.survey_number ?? "—"}
                      </span>
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={parcel.review_status} />
                    <div className="mt-1 flex items-center gap-2">
                      {parcel.assigned_to && (
                        <span className="text-[11px] text-ink-muted">@{parcel.assigned_to}</span>
                      )}
                      <SlaBadge dueAt={parcel.sla_due_at} status={parcel.review_status} />
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <PriorityBadge priority={parcel.priority} score={parcel.priority_score} />
                  </td>
                  <td className="px-4 py-3 font-mono text-xs tabular-nums text-ink-secondary">
                    {formatArea(parcel.total_area_sq_metre)}
                  </td>
                  <td className="px-4 py-3">
                    <ConfidenceMeter value={parcel.confidence_score} />
                  </td>
                  <td className="px-4 py-3">
                    {parcel.validation_issue_count === 0 ? (
                      <span className="inline-flex items-center gap-1 text-xs text-status-good-ink">
                        <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> Clean
                      </span>
                    ) : (
                      <span className="text-xs text-ink-secondary">
                        <span className="font-semibold text-ink-primary">{parcel.validation_issue_count}</span>{" "}
                        · {parcel.validation_highest_severity}
                      </span>
                    )}
                    {parcel.has_human_corrections && (
                      <span className="mt-0.5 block text-[10px] font-medium text-series-2">
                        {parcel.correction_count} human correction
                        {parcel.correction_count === 1 ? "" : "s"}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-ink-muted">{formatDate(parcel.updated_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <Link
                      href={`/parcels/${parcel.id}`}
                      className="text-sm font-semibold text-series-1 hover:underline"
                    >
                      Review →
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {page.items.length === 0 && (
          <EmptyState
            icon={FileSearch}
            title="No records match this filter"
            description="Try clearing a filter, or widening the search. If the database is empty, seed it with `python scripts/seed_demo_data.py --reset` from the backend directory."
          />
        )}
      </div>

      {/* -- Pagination --------------------------------------------------------- */}
      <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
        <p className="text-ink-secondary">
          Showing{" "}
          <span className="font-semibold text-ink-primary">
            {page.total === 0 ? 0 : page.offset + 1}–{page.offset + page.items.length}
          </span>{" "}
          of <span className="font-semibold text-ink-primary">{formatCount(page.total)}</span> records
        </p>

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            icon={ChevronLeft}
            disabled={page.offset === 0 || isPending}
            onClick={() => update({ offset: Math.max(0, page.offset - limit) })}
          >
            Previous
          </Button>
          <span className="px-1 text-xs text-ink-muted">
            Page {pageNumber} of {pageCount}
          </span>
          <Button
            size="sm"
            variant="secondary"
            disabled={page.offset + limit >= page.total || isPending}
            onClick={() => update({ offset: page.offset + limit })}
          >
            Next
            <ChevronRight className="h-3.5 w-3.5" aria-hidden />
          </Button>
        </div>
      </div>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 rounded-lg border border-line-strong bg-surface-card px-2.5 text-xs text-ink-primary outline-none focus:border-series-1"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function FilterToggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-end gap-2 pb-2">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-3.5 w-3.5 rounded border-line-strong accent-[var(--series-1)]"
      />
      <span className="text-xs font-medium text-ink-secondary">{label}</span>
    </label>
  );
}
