"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { cn, formatArea } from "@/lib/utils";
import type { ParcelSummary } from "@/types/parcel";

import { ActionBadge, MismatchScore, SeverityBadge } from "./Badge";
import { IconSearch } from "./icons";

/**
 * The console's manifest — every extracted parcel as a dense, monospace-aligned
 * ledger, not a card grid. Filtering is client-side over the fetched page (fine at
 * reviewer-console scale); a larger deployment pushes it to the `/parcels` query
 * params instead.
 */
export function ParcelTable({ parcels }: { parcels: ParcelSummary[] }) {
  const [onlyReview, setOnlyReview] = useState(false);
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    return parcels.filter((p) => {
      if (onlyReview && !p.requires_human_review) return false;
      if (!query) return true;
      const haystack = `${p.village ?? ""} ${p.khata_number ?? ""} ${p.survey_number ?? ""}`.toLowerCase();
      return haystack.includes(query.toLowerCase());
    });
  }, [parcels, onlyReview, query]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2 border border-seam bg-plate px-3 py-1.5 focus-within:border-signal-cyan/50">
          <IconSearch className="h-3.5 w-3.5 text-ink-dim" />
          <input
            type="text"
            placeholder="grep village / khata / survey_no"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-72 bg-transparent font-mono text-xs text-ink-primary placeholder:text-ink-faint focus:outline-none"
          />
        </div>
        <button
          onClick={() => setOnlyReview((v) => !v)}
          className={cn(
            "border px-3 py-1.5 font-mono text-[10px] uppercase tracking-wider transition-colors",
            onlyReview
              ? "border-signal-amber/50 bg-signal-amber/10 text-signal-amber"
              : "border-seam text-ink-secondary hover:border-seam2 hover:text-ink-primary",
          )}
        >
          Needs review
        </button>
        <span className="ml-auto font-mono text-[10px] text-ink-dim">
          {String(filtered.length).padStart(3, "0")} / {String(parcels.length).padStart(3, "0")} RECORDS
        </span>
      </div>

      <div className="overflow-x-auto border border-seam">
        <table className="w-full min-w-[900px] text-left text-xs">
          <thead className="border-b border-seam bg-plate font-mono text-[10px] uppercase tracking-[0.14em] text-ink-dim">
            <tr>
              <th className="px-4 py-2.5 font-medium">Village / Dist.</th>
              <th className="px-4 py-2.5 font-medium">Khata</th>
              <th className="px-4 py-2.5 font-medium">Survey No.</th>
              <th className="px-4 py-2.5 font-medium">Area</th>
              <th className="px-4 py-2.5 font-medium">Mismatch</th>
              <th className="px-4 py-2.5 font-medium">Confidence</th>
              <th className="px-4 py-2.5 font-medium">Action</th>
              <th className="px-4 py-2.5 font-medium">Findings</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-seam">
            {filtered.map((p) => (
              <tr key={p.id} className="group transition-colors hover:bg-signal-cyan/[0.03]">
                <td className="px-4 py-2.5">
                  <Link
                    href={`/parcels/${p.id}`}
                    className="font-display text-[13px] font-medium text-ink-primary decoration-signal-cyan/50 underline-offset-4 group-hover:text-signal-cyan group-hover:underline"
                  >
                    {p.village ?? "UNKNOWN"}
                  </Link>
                  <div className="font-mono text-[10px] text-ink-dim">{p.district ?? "—"}</div>
                </td>
                <td className="px-4 py-2.5 font-mono">{p.khata_number ?? "—"}</td>
                <td className="px-4 py-2.5 font-mono">{p.survey_number ?? "—"}</td>
                <td className="px-4 py-2.5 font-mono tabular-nums text-ink-secondary">
                  {formatArea(p.total_area_sq_metre)}
                </td>
                <td className="px-4 py-2.5">
                  <MismatchScore score={p.mismatch_score} />
                </td>
                <td className="px-4 py-2.5 font-mono tabular-nums text-ink-secondary">
                  {p.confidence_score !== null ? p.confidence_score.toFixed(2) : "—"}
                </td>
                <td className="px-4 py-2.5">
                  <ActionBadge action={p.recommended_action} />
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <SeverityBadge severity={p.validation_highest_severity} />
                    {p.validation_issue_count > 0 && (
                      <span className="font-mono text-[10px] text-ink-dim">×{p.validation_issue_count}</span>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-10 text-center font-mono text-xs text-ink-faint">
                  NO RECORDS MATCH CURRENT FILTER
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
