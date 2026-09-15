"use client";

import {
  Activity,
  ArrowRight,
  BarChart3,
  ClipboardList,
  FileSearch,
  LayoutDashboard,
  ListChecks,
  Map,
  Search,
  Shield,
  UploadCloud,
  Users,
  type LucideIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PROXY_BASE } from "@/lib/api-config";
import { cn } from "@/lib/format";
import { can, type SessionProfile } from "@/lib/session";
import type { Page, ParcelSummary } from "@/types/parcel";

/**
 * Ctrl/Cmd-K: jump to any page, or straight to a parcel by village, khata or
 * survey number.
 *
 * The reason this exists in a government console rather than being developer
 * flourish: the actual work is "pull up survey 88/3 in Hanamkonda", and doing
 * that through dashboard → records → filter → scroll is four interactions for
 * something that should be one. Record search is debounced and served by the
 * same paged `/parcels` endpoint the table uses, so results can never disagree
 * with what the table would show.
 */

interface NavCommand {
  id: string;
  label: string;
  hint: string;
  href: string;
  icon: LucideIcon;
  minRole?: "operator" | "reviewer" | "admin";
}

const NAV_COMMANDS: NavCommand[] = [
  { id: "dashboard", label: "Command dashboard", hint: "Fleet-wide status", href: "/", icon: LayoutDashboard },
  { id: "queue", label: "Review queue", hint: "Prioritised worklist", href: "/queue", icon: ListChecks },
  { id: "records", label: "All records", hint: "Search and filter", href: "/records", icon: ClipboardList },
  { id: "map", label: "Cadastral map", hint: "Geospatial overview", href: "/map", icon: Map },
  { id: "analytics", label: "Analytics", hint: "Trends and rollups", href: "/analytics", icon: BarChart3 },
  { id: "audit", label: "Audit trail", hint: "Every human action", href: "/audit", icon: Activity },
  { id: "rules", label: "Validation rules", hint: "What the engine checks", href: "/rules", icon: Shield },
  { id: "upload", label: "Upload scans", hint: "Single or batch", href: "/upload", icon: UploadCloud, minRole: "operator" },
  { id: "admin", label: "User management", hint: "Accounts and roles", href: "/admin", icon: Users, minRole: "admin" },
];

export function CommandPalette({ profile }: { profile: SessionProfile | null }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [records, setRecords] = useState<ParcelSummary[]>([]);
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const commands = useMemo(
    () =>
      NAV_COMMANDS.filter((command) => {
        if (!command.minRole) return true;
        if (command.minRole === "admin") return can.administer(profile?.role);
        if (command.minRole === "reviewer") return can.approve(profile?.role);
        return can.write(profile?.role);
      }),
    [profile?.role],
  );

  const filteredCommands = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return commands;
    return commands.filter(
      (command) =>
        command.label.toLowerCase().includes(needle) || command.hint.toLowerCase().includes(needle),
    );
  }, [commands, query]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((current) => !current);
      }
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) {
      setCursor(0);
      // Focus after the dialog paints, otherwise the browser has nothing to move
      // the caret into yet.
      requestAnimationFrame(() => inputRef.current?.focus());
    } else {
      setQuery("");
      setRecords([]);
    }
  }, [open]);

  // Debounced record lookup. 220 ms is short enough to feel immediate while a
  // reviewer types a five-character survey number, long enough that it does not
  // fire a query per keystroke.
  useEffect(() => {
    const needle = query.trim();
    if (needle.length < 2) {
      setRecords([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const response = await fetch(
          `${PROXY_BASE}/parcels?q=${encodeURIComponent(needle)}&limit=6`,
          { signal: controller.signal, cache: "no-store" },
        );
        if (!response.ok) return;
        const page = (await response.json()) as Page<ParcelSummary>;
        setRecords(page.items);
      } catch {
        // An aborted or failed lookup simply shows no record results; the
        // navigation commands above stay usable, which is the point of keeping
        // the two result groups independent.
      }
    }, 220);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query]);

  const results = useMemo(
    () => [
      ...filteredCommands.map((command) => ({ kind: "nav" as const, ...command })),
      ...records.map((record) => ({
        kind: "record" as const,
        id: record.id,
        label: `${record.village ?? "Unknown village"} · Survey ${record.survey_number ?? "—"}`,
        hint: `${record.district ?? "—"} · Khata ${record.khata_number ?? "—"}`,
        href: `/parcels/${record.id}`,
        icon: FileSearch,
      })),
    ],
    [filteredCommands, records],
  );

  const go = useCallback(
    (href: string) => {
      setOpen(false);
      router.push(href);
    },
    [router],
  );

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((c) => Math.min(c + 1, results.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((c) => Math.max(c - 1, 0));
    } else if (event.key === "Enter" && results[cursor]) {
      event.preventDefault();
      go(results[cursor].href);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="hidden items-center gap-2 rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs text-white/60 transition-colors hover:bg-white/10 hover:text-white md:flex"
      >
        <Search className="h-3.5 w-3.5" aria-hidden />
        <span>Search records…</span>
        <kbd className="ml-2 rounded border border-white/20 px-1.5 py-0.5 font-mono text-[10px] text-white/50">
          Ctrl K
        </kbd>
      </button>

      {open && (
        <div
          className="fixed inset-0 z-[90] flex items-start justify-center bg-black/45 px-4 pt-[12vh] backdrop-blur-sm"
          onClick={() => setOpen(false)}
          role="presentation"
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Command palette"
            onClick={(event) => event.stopPropagation()}
            className="w-full max-w-xl animate-fade-up overflow-hidden rounded-xl border border-line bg-surface-card shadow-pop"
          >
            <div className="flex items-center gap-3 border-b border-line px-4">
              <Search className="h-4 w-4 shrink-0 text-ink-muted" aria-hidden />
              <input
                ref={inputRef}
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setCursor(0);
                }}
                onKeyDown={onKeyDown}
                placeholder="Jump to a page, or search by village, khata or survey number…"
                className="h-12 w-full bg-transparent text-sm text-ink-primary outline-none placeholder:text-ink-muted"
              />
            </div>

            <ul className="max-h-[52vh] overflow-y-auto p-1.5">
              {results.length === 0 && (
                <li className="px-3 py-8 text-center text-sm text-ink-muted">
                  Nothing matches “{query}”.
                </li>
              )}
              {results.map((result, index) => {
                const Icon = result.icon;
                return (
                  <li key={`${result.kind}-${result.id}`}>
                    <button
                      type="button"
                      onMouseEnter={() => setCursor(index)}
                      onClick={() => go(result.href)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors",
                        cursor === index ? "bg-surface-sunken" : "hover:bg-surface-sunken/60",
                      )}
                    >
                      <Icon className="h-4 w-4 shrink-0 text-ink-muted" strokeWidth={2} aria-hidden />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13px] font-medium text-ink-primary">
                          {result.label}
                        </span>
                        <span className="block truncate text-xs text-ink-muted">{result.hint}</span>
                      </span>
                      {result.kind === "record" && (
                        <span className="shrink-0 rounded bg-series-1/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-series-1">
                          Record
                        </span>
                      )}
                      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-ink-muted" aria-hidden />
                    </button>
                  </li>
                );
              })}
            </ul>

            <div className="flex items-center gap-4 border-t border-line bg-surface-sunken px-4 py-2 text-[11px] text-ink-muted">
              <span>
                <kbd className="rounded border border-line-strong px-1 font-mono">↑↓</kbd> navigate
              </span>
              <span>
                <kbd className="rounded border border-line-strong px-1 font-mono">↵</kbd> open
              </span>
              <span>
                <kbd className="rounded border border-line-strong px-1 font-mono">esc</kbd> close
              </span>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
