import { AlertTriangle, CheckCircle2, Inbox, Timer, UserCheck } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { ProportionBar } from "@/components/charts/BarList";
import { StatTile } from "@/components/charts/StatTile";
import { RecordsTable } from "@/components/records/RecordsTable";
import { Card, CardHeader, EmptyState, ErrorPanel, PageHeader } from "@/components/ui/Primitives";
import { getFacets, getQueueHealth, getReviewQueue, getSessionProfile } from "@/lib/api";
import { cn, formatCount, formatRelative } from "@/lib/format";
import { ROLE_LABEL } from "@/lib/session";

export const metadata: Metadata = { title: "Review queue" };
export const dynamic = "force-dynamic";

type Scope = "mine" | "unassigned" | "district" | "all";

const SCOPES: { value: Scope; label: string; hint: string }[] = [
  { value: "mine", label: "My work", hint: "Records assigned to you" },
  { value: "unassigned", label: "Unclaimed pool", hint: "Nobody has picked these up" },
  { value: "district", label: "My district", hint: "Everything in your jurisdiction" },
  { value: "all", label: "All open work", hint: "Every record awaiting a decision" },
];

/**
 * The review queue — the screen an officer actually works from.
 *
 * Ordered by triage score descending, then by SLA deadline. That ordering is
 * computed in `backend/app/services/triage.py` from the pipeline's own scores,
 * and it is *explainable*: each record carries the reasons it ranked where it
 * did, because a Tehsildar asked why a record is at the top of their list is
 * owed a sentence, not a model card.
 *
 * The scope tabs are what make this a work list rather than another table: "my
 * work" is what you open at the start of a shift, "unclaimed pool" is where you
 * pull the next record from.
 */
export default async function QueuePage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const raw = await searchParams;
  const scopeParam = Array.isArray(raw.scope) ? raw.scope[0] : raw.scope;
  const scope: Scope = (SCOPES.find((s) => s.value === scopeParam)?.value ?? "all") as Scope;
  const offset = Number((Array.isArray(raw.offset) ? raw.offset[0] : raw.offset) ?? 0) || 0;

  const [queue, health, facets, profile] = await Promise.all([
    getReviewQueue(scope, { limit: 25, offset }),
    getQueueHealth(),
    getFacets(),
    getSessionProfile(),
  ]);

  const buckets = health.data?.buckets ?? [];
  const bucketFor = (priority: string) => buckets.find((b) => b.priority === priority);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Review queue"
        description={
          profile
            ? `Signed in as ${profile.full_name} · ${ROLE_LABEL[profile.role]}${
                profile.district ? ` · ${profile.district}` : ""
              }. Records are ordered worst-first by triage score, then by how soon they breach their service level.`
            : "Records ordered worst-first by triage score."
        }
      />

      <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatTile
          label="Open work"
          value={formatCount(health.data?.total_open ?? queue.data?.total ?? 0)}
          icon={Inbox}
          accent="navy"
          hint="Pending, in review or escalated"
        />
        <StatTile
          label="Past service level"
          value={formatCount(health.data?.total_overdue ?? 0)}
          icon={Timer}
          accent={(health.data?.total_overdue ?? 0) > 0 ? "critical" : "good"}
          hint="Breached the SLA for their priority band"
        />
        <StatTile
          label="Critical band"
          value={formatCount(bucketFor("critical")?.open ?? 0)}
          icon={AlertTriangle}
          accent="critical"
          hint="Two independent systems flagged these"
        />
        <StatTile
          label="Oldest open record"
          value={health.data?.oldest_open_at ? formatRelative(health.data.oldest_open_at) : "—"}
          icon={UserCheck}
          accent="warning"
          hint="How long the backlog's tail has been waiting"
        />
      </section>

      <Card>
        <CardHeader
          title="Backlog shape"
          subtitle="Open records by triage band, with the overdue share of each"
        />
        <div className="px-4 py-4">
          {health.error ? (
            <ErrorPanel message={health.error.message} unreachable={health.error.unreachable} />
          ) : (
            <>
              <ProportionBar
                segments={[
                  { label: "Critical", value: bucketFor("critical")?.open ?? 0, color: "var(--status-critical)" },
                  { label: "High", value: bucketFor("high")?.open ?? 0, color: "var(--status-serious)" },
                  { label: "Normal", value: bucketFor("normal")?.open ?? 0, color: "var(--status-warning)" },
                  { label: "Low", value: bucketFor("low")?.open ?? 0, color: "var(--ink-muted)" },
                ]}
              />
              {(health.data?.total_overdue ?? 0) > 0 && (
                <p className="mt-3 text-xs text-ink-muted">
                  {buckets
                    .filter((bucket) => bucket.overdue > 0)
                    .map((bucket) => `${bucket.overdue} ${bucket.priority}`)
                    .join(", ")}{" "}
                  already past the service level.
                </p>
              )}
            </>
          )}
        </div>
      </Card>

      {/* -- Scope tabs --------------------------------------------------------- */}
      <div className="flex flex-wrap gap-1.5 rounded-xl border border-line bg-surface-card p-1.5">
        {SCOPES.map((option) => {
          const active = option.value === scope;
          return (
            <Link
              key={option.value}
              href={`/queue?scope=${option.value}`}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex-1 rounded-lg px-3 py-2 text-center transition-colors",
                active ? "bg-brand-navy text-white dark:bg-series-1" : "hover:bg-surface-sunken",
              )}
            >
              <span
                className={cn("block text-[13px] font-semibold", active ? "text-white" : "text-ink-primary")}
              >
                {option.label}
              </span>
              <span className={cn("mt-0.5 block text-[11px]", active ? "text-white/70" : "text-ink-muted")}>
                {option.hint}
              </span>
            </Link>
          );
        })}
      </div>

      {queue.error ? (
        <ErrorPanel message={queue.error.message} unreachable={queue.error.unreachable} />
      ) : queue.data.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={CheckCircle2}
            title={scope === "mine" ? "Nothing assigned to you" : "This queue is clear"}
            description={
              scope === "mine"
                ? "Pull the next record from the unclaimed pool, or widen the scope to your district."
                : "Every record in this scope has been adjudicated."
            }
          />
        </Card>
      ) : (
        <RecordsTable page={queue.data} facets={facets.data ?? null} profile={profile} />
      )}
    </div>
  );
}
