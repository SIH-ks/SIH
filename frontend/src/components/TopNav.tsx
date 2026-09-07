"use client";

import { LandPlot, LayoutDashboard, UploadCloud } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

/**
 * The institutional command bar: deep navy, always visible, holding the two
 * primary destinations (Dashboard, Upload) plus a system-status readout. Every
 * page mounts this once from the root layout rather than each page building its
 * own header, so navigation state (which link is active) stays consistent.
 */
export function TopNav() {
  const pathname = usePathname();

  const links = [
    { href: "/", label: "Dashboard", icon: LayoutDashboard },
    { href: "/upload", label: "Upload", icon: UploadCloud },
  ];

  return (
    <header className="sticky top-0 z-30 border-b border-navy-700/50 bg-navy-900 shadow-md">
      <div className="mx-auto flex h-16 max-w-[1400px] items-center justify-between px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-navy-700">
            <LandPlot className="h-5 w-5 text-white" strokeWidth={2} />
          </div>
          <div className="leading-tight">
            <div className="text-[15px] font-bold tracking-tight text-white">Adhikar</div>
            <div className="text-[11px] font-medium text-navy-600/80">Land Record Intelligence</div>
          </div>
        </Link>

        <nav className="flex items-center gap-1">
          {links.map(({ href, label, icon: Icon }) => {
            const active = pathname === href;
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2 rounded-md px-3.5 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-white/10 text-white"
                    : "text-slate-300 hover:bg-white/5 hover:text-white",
                )}
              >
                <Icon className="h-4 w-4" strokeWidth={2} />
                {label}
              </Link>
            );
          })}
        </nav>

        <div className="flex items-center gap-2 rounded-full bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-300 ring-1 ring-inset ring-emerald-400/30">
          <span className="relative flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-pulse-soft rounded-full bg-emerald-400" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
          </span>
          System Online
        </div>
      </div>
    </header>
  );
}
