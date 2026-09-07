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
 * to avoid float precision loss. The demo fixtures hand-author it as a plain JS
 * number instead, since there's no Decimal round-trip involved there. Both are
 * genuine inputs this function has to handle, not a type to normalize away
 * upstream: `total_area_sq_metre: number | string | null` on `ParcelSummary` is
 * the accurate contract for a value that comes from two different sources.
 */
export function formatArea(sqMetre: number | string | null): string {
  if (sqMetre === null) return "—";
  const value = typeof sqMetre === "string" ? Number(sqMetre) : sqMetre;
  if (Number.isNaN(value)) return "—";
  if (value >= 10_000) return `${(value / 10_000).toFixed(4)} ha`;
  return `${value.toFixed(2)} sq m`;
}
