import { Building2, KeyRound, ShieldCheck, UserCog, Users } from "lucide-react";
import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { Card, CardHeader, ErrorPanel, PageHeader } from "@/components/ui/Primitives";
import { getSessionProfile, getSystemStatus, listUsers } from "@/lib/api";
import { formatRelative, initials } from "@/lib/format";
import { ROLE_LABEL, can, type UserRole } from "@/lib/session";

export const metadata: Metadata = { title: "Users & access" };
export const dynamic = "force-dynamic";

const ROLE_POWERS: Record<UserRole, { can: string[]; cannot: string[] }> = {
  admin: {
    can: ["Everything a Revenue Inspector can", "Create and suspend accounts", "Change validation policy"],
    cannot: ["Delete an account outright — suspension preserves the audit trail"],
  },
  reviewer: {
    can: ["Approve, reject and escalate records", "Assign work to operators", "Key corrections"],
    cannot: ["Manage user accounts"],
  },
  operator: {
    can: ["Upload scans", "Key corrections into records", "Re-run validation"],
    cannot: ["Approve a record into the register", "Assign work to others"],
  },
  auditor: {
    can: ["Read every record and the full audit trail", "Export the trail as CSV"],
    cannot: ["Change anything at all"],
  },
};

/**
 * User and access administration.
 *
 * The permission matrix is spelled out rather than implied, because in a revenue
 * department "who may approve a land record" is a policy statement, not a UI
 * detail. Deactivation rather than deletion: the audit trail references
 * reviewers by username, and removing the row would orphan every decision that
 * person ever made.
 */
export default async function AdminPage() {
  const profile = await getSessionProfile();
  if (!can.administer(profile?.role)) redirect("/");

  const [users, status] = await Promise.all([listUsers(), getSystemStatus()]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Users & access"
        description="Four roles, ordered by authority. What each can do is enforced by the API on every request — the console only decides which controls to draw."
      />

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Accounts" subtitle={`${users.data?.length ?? 0} registered`} icon={Users} />
          {users.error ? (
            <ErrorPanel className="m-4" message={users.error.message} unreachable={users.error.unreachable} />
          ) : (
            <ul className="divide-y divide-line">
              {(users.data ?? []).map((user) => (
                <li key={user.id} className="flex items-center gap-3 px-4 py-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-brand-navy/8 text-xs font-bold text-brand-navy dark:bg-series-1/15 dark:text-series-1">
                    {initials(user.full_name)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="flex flex-wrap items-baseline gap-2">
                      <span className="truncate text-[13px] font-semibold text-ink-primary">
                        {user.full_name}
                      </span>
                      <code className="text-[11px] text-ink-muted">@{user.username}</code>
                    </p>
                    <p className="truncate text-xs text-ink-muted">
                      {user.designation ?? ROLE_LABEL[user.role]}
                      {user.district && ` · ${user.district}`}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <span className="rounded-full bg-surface-sunken px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-ink-secondary">
                      {user.role}
                    </span>
                    <p className="mt-1 text-[10px] text-ink-muted">
                      {("last_login_at" in user && (user as { last_login_at?: string }).last_login_at)
                        ? `seen ${formatRelative((user as { last_login_at?: string }).last_login_at)}`
                        : "never signed in"}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <p className="border-t border-line px-4 py-3 text-[11px] leading-relaxed text-ink-muted">
            Accounts are created through{" "}
            <code className="font-mono">POST /api/v1/auth/users</code> and suspended through{" "}
            <code className="font-mono">/deactivate</code> — never deleted, because the audit trail
            references reviewers by username and deleting the row would orphan every decision they
            ever made. A suspended token stops working on the next request, not at its expiry.
          </p>
        </Card>

        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader title="Permission model" subtitle="Roles nest: each inherits the one below" icon={ShieldCheck} />
            <ul className="divide-y divide-line">
              {(["admin", "reviewer", "operator", "auditor"] as UserRole[]).map((role) => (
                <li key={role} className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <UserCog className="h-4 w-4 text-ink-muted" aria-hidden />
                    <span className="text-[13px] font-semibold text-ink-primary">{ROLE_LABEL[role]}</span>
                    <code className="rounded bg-surface-sunken px-1.5 py-0.5 text-[10px] text-ink-secondary">
                      {role}
                    </code>
                  </div>
                  <ul className="mt-1.5 flex flex-col gap-0.5">
                    {ROLE_POWERS[role].can.map((line) => (
                      <li key={line} className="flex items-start gap-1.5 text-xs text-ink-secondary">
                        <span className="mt-0.5 text-status-good-ink" aria-hidden>✓</span>
                        {line}
                      </li>
                    ))}
                    {ROLE_POWERS[role].cannot.map((line) => (
                      <li key={line} className="flex items-start gap-1.5 text-xs text-ink-muted">
                        <span className="mt-0.5 text-status-critical-ink" aria-hidden>✕</span>
                        {line}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </Card>

          <Card>
            <CardHeader title="Deployment" subtitle="What this instance is actually running" icon={Building2} />
            {status.data ? (
              <dl className="grid grid-cols-2 gap-3 px-4 py-4 text-sm">
                <Row label="Environment" value={status.data.environment} />
                <Row label="Auth enforced" value={status.data.auth_enforced ? "Yes" : "No — open API"} />
                <Row label="Database" value={status.data.database.dialect} />
                <Row
                  label="Fallback active"
                  value={status.data.database.fallback_active ? "Yes — SQLite substituted" : "No"}
                />
                <Row label="Max upload" value={`${status.data.limits.max_upload_size_mb} MB`} />
                <Row label="Batch limit" value={`${status.data.limits.max_batch_upload_files} files`} />
              </dl>
            ) : (
              <ErrorPanel className="m-4" message="System status is unavailable." />
            )}

            {status.data && (
              <div className="border-t border-line px-4 py-3">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                  Service levels (hours to breach)
                </p>
                <ul className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1">
                  {Object.entries(status.data.sla_hours_by_priority).map(([band, hours]) => (
                    <li key={band} className="text-xs text-ink-secondary">
                      <span className="capitalize">{band}</span>{" "}
                      <strong className="font-mono font-semibold text-ink-primary">{hours}h</strong>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>

          <Card className="border-status-warning/30 bg-status-warning-wash">
            <div className="flex gap-3 px-4 py-3.5">
              <KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-status-warning-ink" aria-hidden />
              <div>
                <p className="text-[13px] font-semibold text-ink-primary">Before any real deployment</p>
                <ul className="mt-1 flex flex-col gap-0.5 text-xs text-ink-secondary">
                  <li>
                    Set <code className="font-mono">ADHIKAR_API_SEED_DEMO_USERS=false</code> and remove the
                    four evaluation accounts.
                  </li>
                  <li>
                    Rotate <code className="font-mono">ADHIKAR_API_JWT_SECRET</code> — the default is a
                    known string.
                  </li>
                  <li>Point the database at Postgres/PostGIS and disable the SQLite fallback.</li>
                </ul>
              </div>
            </div>
          </Card>
        </div>
      </section>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">{label}</dt>
      <dd className="mt-0.5 truncate text-sm font-semibold capitalize text-ink-primary">{value}</dd>
    </div>
  );
}
