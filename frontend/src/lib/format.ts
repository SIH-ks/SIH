/**
 * Display formatting. Everything a number or date passes through on its way to a
 * screen lives here, so "8005.0000" never renders two different ways in two
 * different tables.
 */

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Standard shadcn-style className combinator: conditional classes + Tailwind
 * conflict resolution (e.g. `p-2` then `p-4` keeps `p-4`, not both). */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * FastAPI/Pydantic serializes a `Decimal` field (which `total_area_sq_metre` is,
 * backed by `Numeric(18,4)`) as a JSON **string** -- `"8005.0000"`, not `8005` --
 * to avoid float precision loss. Some fixtures hand-author it as a plain JS
 * number instead. Both are genuine inputs this function has to handle, not a
 * type to normalize away upstream.
 */
export function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "string" ? Number(value) : value;
  return Number.isFinite(parsed) ? parsed : null;
}

/** Area in the unit a revenue officer would actually quote: hectares above one,
 * square metres below. */
export function formatArea(sqMetre: number | string | null | undefined): string {
  const value = toNumber(sqMetre);
  if (value === null) return "—";
  if (value >= 10_000) return `${(value / 10_000).toFixed(4)} ha`;
  return `${value.toLocaleString("en-IN", { maximumFractionDigits: 2 })} m²`;
}

export function formatHectares(hectares: number | null | undefined): string {
  if (hectares === null || hectares === undefined) return "—";
  return `${hectares.toLocaleString("en-IN", { maximumFractionDigits: 2 })} ha`;
}

/** Indian digit grouping (1,23,456) — the grouping every figure in a revenue
 * office is read in. */
export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-IN");
}

export function formatPercent(fraction: number | null | undefined, digits = 0): string {
  if (fraction === null || fraction === undefined) return "—";
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function formatScore(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(digits);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * "3 days ago" / "in 4 hours". Uses `Intl.RelativeTimeFormat` so the wording is
 * correct rather than hand-pluralised, and returns a signed phrase in both
 * directions — the SLA badge needs "overdue by" and "due in" from one function.
 */
export function formatRelative(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "—";

  const seconds = (then.getTime() - now.getTime()) / 1000;
  const units: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31_536_000],
    ["month", 2_592_000],
    ["day", 86_400],
    ["hour", 3600],
    ["minute", 60],
  ];
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return formatter.format(Math.round(seconds / size), unit);
  }
  return formatter.format(Math.round(seconds), "second");
}

/** Whole hours between now and an SLA deadline. Negative once breached. */
export function hoursUntil(iso: string | null | undefined, now: Date = new Date()): number | null {
  if (!iso) return null;
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return null;
  return Math.round((then.getTime() - now.getTime()) / 3_600_000);
}

export function formatBytes(bytes: number | null | undefined): string {
  if (!bytes) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

/** `MUTATION_DATE_IN_FUTURE` -> `Mutation date in future`. Rule codes are stable
 * identifiers that appear in audits and must never be renamed; this is purely
 * how they are *shown* beside the raw code, never instead of it. */
export function humaniseRuleCode(code: string): string {
  const words = code.toLowerCase().replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function titleCase(value: string | null | undefined): string {
  if (!value) return "—";
  return value
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

/** Initials for an avatar chip, from a full name. */
export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}
