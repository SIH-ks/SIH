import {
  ArrowRight,
  CheckCircle2,
  Download,
  Flag,
  History,
  PenLine,
  RefreshCw,
  ShieldCheck,
  UserPlus,
  type LucideIcon,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { Card, CardHeader, EmptyState, ErrorPanel, LinkButton, PageHeader } from "@/components/ui/Primitives";
import { getSessionProfile, listAuditEvents } from "@/lib/api";
import { cn, formatCount, formatDateTime, formatRelative } from "@/lib/format";

export const metadata: Metadata = { title: "Audit trail" };
export const dynamic = "force-dynamic";

const ACTION_FILTERS = [
  { value: "", label: "All actions" },
  { value: "corrected", label: "Corrections" },
  { value: "status_changed", label: "Decisions" },
  { value: "assigned", label: "Assignments" },
  { value: "revalidated", label: "Re-validations" },
  { value: "flagged", label: "Flags" },
];

const FALLBACK_META = { label: "Action", icon: History, tone: "text-ink-secondary bg-surface-sunken" };

const ACTION_META: Record<string, { label: string; icon: LucideIcon; tone: string }> = {
  corrected: { label: "Corrected", icon: PenLine, tone: "text-series-2 bg-series-2/10" },
  status_changed: { label: "Decision", icon: CheckCircle2, tone: "text-series-3 bg-series-3/10" },
  assigned: { label: "Assigned", icon: UserPlus, tone: "text-series-1 bg-series-1/10" },
  revalidated: { label: "Re-validated", icon: RefreshCw, tone: "text-series-7 bg-series-7/10" },
  flagged: { label: "Flagged", icon: Flag, tone: "text-status-warning-ink bg-status-warning-wash" },
  accepted: { label: "Accepted", icon: ShieldCheck, tone: "text-status-good-ink bg-status-good-wash" },
  note_added: { label: "Note", icon: History, tone: "text-ink-secondary bg-surface-sunken" },
};

/**
 * The department-wide audit trail.
 *
 * Every authenticated role can read this, including the auditor role — which is
 * the entire reason that role exists. An audit trail readable only by the people
 * being audited is not one.
 *
 * Rows are append-only: a correction supersedes a value in `artifact_json` but
 * never overwrites the entry recording what it was before, so the machine's
 * original reading stays reconstructable from here indefinitely.
 */
export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const one = (key: string) => {
    const value = raw[key];
    return Array.isArray(value) ? value[0] : value;
  };

  const action = one("action") ?? "";
  const reviewer = one("reviewer");
  const district = one("district");
  const offset = Number(one("offset") ?? 0) || 0;

  const [events, profile] = await Promise.all([
    listAuditEvents({ action: action || undefined, reviewer, district, limit: 60, offset }),
    getSessionProfile(),
  ]);

  const exportParams = new URLSearchParams();
  if (reviewer) exportParams.set("reviewer", reviewer);
  if (district) exportParams.set("district", district);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Audit trail"
        description="Every human action taken on every record — who, when, from where, and what the value was before. Append-only: nothing here is edited in place."
        actions={
          <LinkButton
            href={`/api/proxy/exports/audit.csv${exportParams.toString() ? `?${exportParams}` : ""}`}
            variant="secondary"
            icon={Download}
            external
          >
            Export trail
          </LinkButton>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        {ACTION_FILTERS.map((filter) => {
          const active = action === filter.value;
          const params = new URLSearchParams();
          if (filter.value) params.set("action", filter.value);
          if (reviewer) params.set("reviewer", reviewer);
          if (district) params.set("district", district);
          return (
            <Link
              key={filter.value || "all"}
              href={`/audit${params.toString() ? `?${params}` : ""}`}
              className={cn(
                "rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors",
                active
                  ? "bg-brand-navy text-white dark:bg-series-1"
                  : "border border-line bg-surface-card text-ink-secondary hover:bg-surface-sunken",
              )}
            >
              {filter.label}
            </Link>
          );
        })}

        {(reviewer || district) && (
          <Link href="/audit" className="ml-1 text-xs font-semibold text-series-1 hover:underline">
            Clear {reviewer ? `@${reviewer}` : district} filter
          </Link>
        )}

        {profile?.role === "auditor" && (
          <span className="ml-auto rounded-full bg-status-good-wash px-2.5 py-1 text-[11px] font-semibold text-status-good-ink ring-1 ring-inset ring-status-good/25">
            Read-only oversight access
          </span>
        )}
      </div>

      {events.error ? (
        <ErrorPanel message={events.error.message} unreachable={events.error.unreachable} />
      ) : events.data.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={History}
            title="No audit entries yet"
            description="Corrections, assignments and decisions all appear here the moment they happen."
          />
        </Card>
      ) : (
        <Card>
          <CardHeader
            title={`${formatCount(events.data.total)} recorded actions`}
            subtitle="Newest first"
            icon={History}
          />

          <ol className="divide-y divide-line">
            {events.data.items.map((event) => {
              const meta = ACTION_META[event.action] ?? FALLBACK_META;
              const Icon = meta.icon;
              const before = event.previous_value?.value;
              const after = event.new_value?.value;
              const showDiff =
                event.action === "corrected" || event.action === "status_changed" || event.action === "assigned";

              return (
                <li key={event.id} className="flex gap-3.5 px-4 py-3.5">
                  <span
                    className={cn(
                      "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg",
                      meta.tone,
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" strokeWidth={2.2} aria-hidden />
                  </span>

                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                      <span className="text-[13px] font-semibold text-ink-primary">{meta.label}</span>
                      <span className="text-xs text-ink-secondary">
                        by{" "}
                        <Link
                          href={`/audit?reviewer=${encodeURIComponent(event.reviewer)}`}
                          className="font-medium text-series-1 hover:underline"
                        >
                          @{event.reviewer}
                        </Link>
                        {event.reviewer_role && (
                          <span className="ml-1 text-ink-muted">({event.reviewer_role})</span>
                        )}
                      </span>
                      <span className="text-xs text-ink-muted" title={formatDateTime(event.created_at)}>
                        · {formatRelative(event.created_at)}
                      </span>
                    </div>

                    <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                      <Link
                        href={`/parcels/${event.parcel_id}`}
                        className="inline-flex items-center gap-1 font-medium text-ink-secondary hover:text-series-1"
                      >
                        {event.village ?? event.parcel_key ?? "Record"}
                        <ArrowRight className="h-3 w-3" aria-hidden />
                      </Link>
                      {event.district && <span className="text-ink-muted">{event.district}</span>}
                      {event.field_path !== "$" && (
                        <code className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[10px] text-ink-secondary">
                          {event.field_path}
                        </code>
                      )}
                    </div>

                    {showDiff && (before !== null || after !== null) && (
                      <p className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
                        <span className="rounded bg-status-critical-wash px-1.5 py-0.5 font-mono text-[11px] text-status-critical-ink line-through decoration-1">
                          {display(before)}
                        </span>
                        <ArrowRight className="h-3 w-3 text-ink-muted" aria-hidden />
                        <span className="rounded bg-status-good-wash px-1.5 py-0.5 font-mono text-[11px] font-semibold text-status-good-ink">
                          {display(after)}
                        </span>
                      </p>
                    )}

                    {event.note && (
                      <p className="mt-1.5 break-anywhere text-xs italic text-ink-muted">“{event.note}”</p>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>

          {events.data.total > events.data.items.length && (
            <div className="flex items-center justify-between gap-3 border-t border-line px-4 py-3 text-sm">
              <span className="text-ink-secondary">
                Showing {events.data.offset + 1}–{events.data.offset + events.data.items.length} of{" "}
                {formatCount(events.data.total)}
              </span>
              <div className="flex gap-2">
                {events.data.offset > 0 && (
                  <Link
                    href={`/audit?${buildParams({ action, reviewer, district, offset: Math.max(0, offset - 60) })}`}
                    className="rounded-lg border border-line-strong px-3 py-1.5 text-xs font-semibold text-ink-secondary hover:bg-surface-sunken"
                  >
                    Previous
                  </Link>
                )}
                {events.data.offset + events.data.items.length < events.data.total && (
                  <Link
                    href={`/audit?${buildParams({ action, reviewer, district, offset: offset + 60 })}`}
                    className="rounded-lg border border-line-strong px-3 py-1.5 text-xs font-semibold text-ink-secondary hover:bg-surface-sunken"
                  >
                    Next
                  </Link>
                )}
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

function buildParams(input: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(input)) {
    if (value !== undefined && value !== "" && value !== 0) params.set(key, String(value));
  }
  return params.toString();
}

/** Audit values are stored as `{"value": …}` so the column can hold a scalar, an
 * object or null without the reader guessing which. This renders any of them. */
function display(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
