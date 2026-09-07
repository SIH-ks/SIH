"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { LiveDot } from "./Panel";

/** The console's top bar: monogram mark, route breadcrumb, live UTC clock. This is
 * the single most identity-defining element of the "command center" read — it
 * needs to look like it belongs to an operations tool, not a marketing site. */
export function HeaderBar({ breadcrumb, demo = false }: { breadcrumb?: string; demo?: boolean }) {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <header className="flex items-center justify-between border-b border-seam pb-4">
      <Link href="/" className="flex items-center gap-3">
        <Monogram />
        <div>
          <div className="font-display text-sm font-bold uppercase tracking-[0.2em] text-ink-primary">
            Adhikar
          </div>
          <div className="font-mono text-[10px] uppercase tracking-widest text-ink-dim">
            {breadcrumb ?? "Land Record Console"}
          </div>
        </div>
      </Link>

      <div className="flex items-center gap-5 font-mono text-[11px] text-ink-secondary">
        {demo && (
          <span className="border border-signal-amber/40 bg-signal-amber/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-signal-amber">
            Demo data
          </span>
        )}
        <span className="flex items-center gap-1.5">
          <LiveDot color="signal-green" />
          SIH26018 · ONLINE
        </span>
        <span className="hidden text-ink-dim sm:inline">|</span>
        <span className="hidden tabular-nums sm:inline">
          {now
            ? `${now.toISOString().slice(0, 10)} ${now.toISOString().slice(11, 19)} UTC`
            : "————-—— —— ——:——:—— UTC"}
        </span>
      </div>
    </header>
  );
}

function Monogram() {
  return (
    <svg viewBox="0 0 32 32" className="h-8 w-8 text-signal-cyan" fill="none">
      <rect x="1" y="1" width="30" height="30" stroke="currentColor" strokeWidth="1.5" />
      <path d="M16 6L25 24H7L16 6Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      <path d="M16 14v6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <circle cx="16" cy="22.5" r="0.8" fill="currentColor" />
    </svg>
  );
}
