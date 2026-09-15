"use client";

import {
  Activity,
  BarChart3,
  ClipboardList,
  Database,
  GitBranch,
  LandPlot,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Map,
  Menu,
  Shield,
  UploadCloud,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { CommandPalette } from "@/components/shell/CommandPalette";
import { ThemeToggle } from "@/components/shell/ThemeToggle";
import { signOut } from "@/lib/client-api";
import { cn, initials } from "@/lib/format";
import { ROLE_LABEL, can, type SessionProfile } from "@/lib/session";
import type { SystemStatus } from "@/types/parcel";

/**
 * The console frame: a persistent left rail, a navy command bar, and the page.
 *
 * A rail rather than a top-only nav because this application has nine
 * destinations, not two — a horizontal bar at that count either wraps or starts
 * hiding things behind a "More" menu, and an officer should be able to see the
 * whole system at once. The rail collapses to a drawer below `lg`, which is the
 * width a field officer's tablet actually is.
 *
 * Navigation entries are filtered by role here purely so the UI does not offer
 * an action that will be refused; the API enforces the same boundaries
 * independently (`app/api/deps.py`).
 */

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  minRole?: "operator" | "reviewer" | "admin";
  /** Match nested routes (`/parcels/…` highlights Records). */
  match?: (pathname: string) => boolean;
}

const NAV_GROUPS: { heading: string; items: NavItem[] }[] = [
  {
    heading: "Operations",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
      { href: "/queue", label: "Review queue", icon: ListChecks },
      {
        href: "/records",
        label: "Records",
        icon: ClipboardList,
        match: (path) => path.startsWith("/records") || path.startsWith("/parcels"),
      },
      { href: "/upload", label: "Upload", icon: UploadCloud, minRole: "operator" },
      {
        href: "/succession",
        label: "Ownership succession",
        icon: GitBranch,
        match: (path) => path.startsWith("/succession"),
      },
    ],
  },
  {
    heading: "Oversight",
    items: [
      { href: "/map", label: "Cadastral map", icon: Map },
      { href: "/analytics", label: "Analytics", icon: BarChart3 },
      { href: "/audit", label: "Audit trail", icon: Activity },
    ],
  },
  {
    heading: "System",
    items: [
      { href: "/rules", label: "Validation rules", icon: Shield },
      { href: "/admin", label: "Users", icon: Users, minRole: "admin" },
    ],
  },
];

export function AppShell({
  profile,
  status,
  children,
}: {
  profile: SessionProfile | null;
  status: SystemStatus | null;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Close the mobile drawer on navigation — leaving it open over the page the
  // user just asked for is the classic mobile-nav bug.
  useEffect(() => setDrawerOpen(false), [pathname]);

  const visible = (item: NavItem) => {
    if (!item.minRole) return true;
    if (item.minRole === "admin") return can.administer(profile?.role);
    if (item.minRole === "reviewer") return can.approve(profile?.role);
    return can.write(profile?.role);
  };

  const isActive = (item: NavItem) =>
    item.match ? item.match(pathname) : pathname === item.href;

  const rail = (
    <nav className="flex h-full flex-col gap-6 overflow-y-auto px-3 py-5" aria-label="Main">
      {NAV_GROUPS.map((group) => {
        const items = group.items.filter(visible);
        if (items.length === 0) return null;
        return (
          <div key={group.heading}>
            <p className="px-3 pb-2 text-[10px] font-bold uppercase tracking-[0.13em] text-white/35">
              {group.heading}
            </p>
            <ul className="flex flex-col gap-0.5">
              {items.map((item) => {
                const active = isActive(item);
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "group relative flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors",
                        active ? "bg-white/12 text-white" : "text-white/65 hover:bg-white/6 hover:text-white",
                      )}
                    >
                      {active && (
                        <span
                          className="absolute inset-y-1.5 left-0 w-0.5 rounded-r bg-brand-saffron"
                          aria-hidden
                        />
                      )}
                      <Icon className="h-4 w-4 shrink-0" strokeWidth={2} aria-hidden />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}

      <div className="mt-auto px-1">
        <SystemPill status={status} />
      </div>
    </nav>
  );

  return (
    <div className="flex min-h-screen bg-surface-page">
      {/* Desktop rail */}
      <aside className="sticky top-0 hidden h-screen w-[228px] shrink-0 flex-col border-r border-white/8 bg-brand-navy-deep lg:flex">
        <BrandMark />
        {rail}
      </aside>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-[70] lg:hidden">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setDrawerOpen(false)}
            role="presentation"
          />
          <aside className="absolute inset-y-0 left-0 flex w-[248px] animate-slide-in flex-col bg-brand-navy-deep shadow-pop">
            <div className="flex items-center justify-between pr-2">
              <BrandMark />
              <button
                type="button"
                onClick={() => setDrawerOpen(false)}
                aria-label="Close navigation"
                className="rounded-lg p-2 text-white/70 hover:bg-white/10 hover:text-white"
              >
                <X className="h-4 w-4" aria-hidden />
              </button>
            </div>
            {rail}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b border-white/8 bg-brand-navy px-4 shadow-sm">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            aria-label="Open navigation"
            className="rounded-lg p-2 text-white/70 transition-colors hover:bg-white/10 hover:text-white lg:hidden"
          >
            <Menu className="h-4 w-4" aria-hidden />
          </button>

          <div className="lg:hidden">
            <BrandMark compact />
          </div>

          <div className="ml-auto flex items-center gap-2.5">
            <CommandPalette profile={profile} />
            <ThemeToggle />
            <UserChip profile={profile} />
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1480px] flex-1 px-4 py-6 sm:px-6">{children}</main>

        <footer className="border-t border-line px-6 py-4 text-center text-xs text-ink-muted">
          Adhikar · Intelligent Land Record Digitization &amp; Validation System · SIH26018 ·
          Ministry of Rural Development
        </footer>
      </div>
    </div>
  );
}

function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <Link
      href="/"
      className={cn(
        "flex items-center gap-2.5 px-4",
        compact ? "h-full" : "h-14 border-b border-white/8",
      )}
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-brand-saffron to-brand-green">
        <LandPlot className="h-4 w-4 text-white" strokeWidth={2.2} aria-hidden />
      </span>
      <span className="leading-tight">
        <span className="block text-[15px] font-bold tracking-tight text-white">Adhikar</span>
        <span className="block text-[10px] font-medium tracking-wide text-white/50">
          Land Record Intelligence
        </span>
      </span>
    </Link>
  );
}

/**
 * The system-status readout, and the reason it is not just a green dot: when the
 * configured Postgres is unreachable the API falls back to the bundled SQLite
 * file (see `backend/app/db/base.py`). A pill that said "System online" while
 * the API was quietly writing to a different database than the configured one
 * would be worse than no pill at all — so the fallback is reported here, in
 * amber, on the same surface everything else is read from.
 */
function SystemPill({ status }: { status: SystemStatus | null }) {
  if (!status) {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-status-critical/15 px-3 py-2 text-[11px] font-medium text-status-critical-ink ring-1 ring-inset ring-status-critical/30">
        <span className="h-1.5 w-1.5 rounded-full bg-status-critical" aria-hidden />
        API unreachable
      </div>
    );
  }

  const degraded = status.status !== "ok" || status.database.fallback_active;
  return (
    <div
      className={cn(
        "flex flex-col gap-1 rounded-lg px-3 py-2 text-[11px] ring-1 ring-inset",
        degraded
          ? "bg-status-warning/12 text-status-warning-ink ring-status-warning/30"
          : "bg-status-good/12 text-status-good-ink ring-status-good/25",
      )}
    >
      <span className="flex items-center gap-2 font-semibold">
        <span className="relative flex h-1.5 w-1.5">
          <span
            className={cn(
              "absolute inline-flex h-full w-full animate-pulse-soft rounded-full",
              degraded ? "bg-status-warning" : "bg-status-good",
            )}
          />
          <span
            className={cn(
              "relative inline-flex h-1.5 w-1.5 rounded-full",
              degraded ? "bg-status-warning" : "bg-status-good",
            )}
          />
        </span>
        {degraded ? "Running degraded" : "System online"}
      </span>
      <span className="flex items-center gap-1.5 opacity-80">
        <Database className="h-3 w-3" aria-hidden />
        {status.database.fallback_active
          ? `SQLite fallback (${status.database.configured_url_scheme} unreachable)`
          : status.database.dialect}
      </span>
    </div>
  );
}

function UserChip({ profile }: { profile: SessionProfile | null }) {
  const [open, setOpen] = useState(false);

  if (!profile) return null;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-2 rounded-lg py-1 pl-1 pr-2 transition-colors hover:bg-white/10"
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white/15 text-[11px] font-bold text-white">
          {initials(profile.full_name)}
        </span>
        <span className="hidden text-left leading-tight sm:block">
          <span className="block text-xs font-semibold text-white">{profile.full_name}</span>
          <span className="block text-[10px] text-white/55">{ROLE_LABEL[profile.role]}</span>
        </span>
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} role="presentation" />
          <div
            role="menu"
            className="absolute right-0 z-50 mt-2 w-60 animate-fade-up overflow-hidden rounded-xl border border-line bg-surface-card shadow-pop"
          >
            <div className="border-b border-line px-4 py-3">
              <p className="text-sm font-semibold text-ink-primary">{profile.full_name}</p>
              <p className="mt-0.5 text-xs text-ink-secondary">
                {profile.designation ?? ROLE_LABEL[profile.role]}
              </p>
              <p className="mt-1.5 flex flex-wrap gap-1.5">
                <span className="rounded bg-series-1/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide text-series-1">
                  {profile.role}
                </span>
                {profile.district && (
                  <span className="rounded bg-surface-sunken px-1.5 py-0.5 text-[10px] font-medium text-ink-secondary">
                    {profile.district}
                  </span>
                )}
              </p>
            </div>
            <button
              type="button"
              role="menuitem"
              onClick={() => signOut()}
              className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-sm text-ink-secondary transition-colors hover:bg-surface-sunken hover:text-ink-primary"
            >
              <LogOut className="h-4 w-4" aria-hidden />
              Sign out
            </button>
          </div>
        </>
      )}
    </div>
  );
}
