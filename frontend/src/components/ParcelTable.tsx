"use client";

import { Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { cn, formatArea } from "@/lib/utils";
import type { ParcelSummary } from "@/types/parcel";

import { deriveTrafficLight, TrafficLightBadge, type TrafficLight } from "./Badge";

const FILTER_OPTIONS: { value: TrafficLight | "all"; label: string }[] = [
  { value: "all", label: "All records" },
  { value: "green", label: "Auto-validated" },
  { value: "yellow", label: "Needs review" },
  { value: "red", label: "Flagged" },
];

/**
 * The Command Dashboard's records table. The traffic-light column is the whole
 * point of this view -- everything else (search, the status filter) exists to
 * help a reviewer get from "how many are flagged" to "which ones" in one motion.
 */
export function ParcelTable({ parcels }: { parcels: ParcelSummary[] }) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<TrafficLight | "all">("all");

  const filtered = useMemo(() => {
    return parcels.filter((p) => {
      const status = deriveTrafficLight(p);
      if (statusFilter !== "all" && status !== statusFilter) return false;
      if (!query) return true;
      const haystack = `${p.village ?? ""} ${p.khata_number ?? ""} ${p.survey_number ?? ""}`.toLowerCase();
      return haystack.includes(query.toLowerCase());
    });
  }, [parcels, query, statusFilter]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="Search village, khata, or survey no."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-72 rounded-lg border border-slate-200 bg-white py-2 pl-9 pr-3 text-sm text-slate-700 placeholder:text-slate-400 focus:border-navy-600 focus:outline-none focus:ring-2 focus:ring-navy-600/10"
            />
          </div>
          <div className="flex rounded-lg border border-slate-200 bg-white p-0.5">
            {FILTER_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                onClick={() => setStatusFilter(opt.value)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                  statusFilter === opt.value
                    ? "bg-navy-800 text-white"
                    : "text-slate-600 hover:bg-slate-100",
                )}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
        <span className="text-sm text-slate-500">
          Showing <span className="font-semibold text-slate-700">{filtered.length}</span> of{" "}
          {parcels.length} records
        </span>
      </div>

      <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-card">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-5 py-3 font-semibold">Status</th>
              <th className="px-5 py-3 font-semibold">Village / District</th>
              <th className="px-5 py-3 font-semibold">Khata</th>
              <th className="px-5 py-3 font-semibold">Survey No.</th>
              <th className="px-5 py-3 font-semibold">Total Area</th>
              <th className="px-5 py-3 font-semibold">Confidence</th>
              <th className="px-5 py-3 font-semibold">Last Updated</th>
              <th className="px-5 py-3 font-semibold" />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filtered.map((p) => (
              <tr key={p.id} className="transition-colors hover:bg-slate-50">
                <td className="px-5 py-3.5">
                  <TrafficLightBadge status={deriveTrafficLight(p)} />
                </td>
                <td className="px-5 py-3.5">
                  <div className="font-medium text-slate-900">{p.village ?? "Unknown"}</div>
                  <div className="text-xs text-slate-400">{p.district ?? "—"}</div>
                </td>
                <td className="px-5 py-3.5 text-slate-600">{p.khata_number ?? "—"}</td>
                <td className="px-5 py-3.5 text-slate-600">{p.survey_number ?? "—"}</td>
                <td className="px-5 py-3.5 font-mono text-xs text-slate-600">
                  {formatArea(p.total_area_sq_metre)}
                </td>
                <td className="px-5 py-3.5">
                  {p.confidence_score !== null ? (
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-slate-100">
                        <div
                          className={cn(
                            "h-full rounded-full",
                            p.confidence_score >= 0.85
                              ? "bg-emerald-500"
                              : p.confidence_score >= 0.6
                                ? "bg-amber-500"
                                : "bg-red-500",
                          )}
                          style={{ width: `${Math.round(p.confidence_score * 100)}%` }}
                        />
                      </div>
                      <span className="font-mono text-xs text-slate-500">
                        {Math.round(p.confidence_score * 100)}%
                      </span>
                    </div>
                  ) : (
                    <span className="text-xs text-slate-400">—</span>
                  )}
                </td>
                <td className="px-5 py-3.5 text-xs text-slate-400">
                  {new Date(p.updated_at).toLocaleDateString("en-IN", {
                    day: "2-digit",
                    month: "short",
                    year: "numeric",
                  })}
                </td>
                <td className="px-5 py-3.5 text-right">
                  <Link
                    href={`/parcels/${p.id}`}
                    className="text-sm font-medium text-navy-700 hover:text-navy-800 hover:underline"
                  >
                    Review →
                  </Link>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={8} className="px-5 py-12 text-center text-sm text-slate-400">
                  No records match the current filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
