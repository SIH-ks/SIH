import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Standard shadcn-style className combinator: conditional classes + Tailwind
 * conflict resolution (e.g. `p-2` then `p-4` keeps `p-4`, not both). */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function formatArea(sqMetre: number | null): string {
  if (sqMetre === null) return "—";
  if (sqMetre >= 10_000) return `${(sqMetre / 10_000).toFixed(4)} ha`;
  return `${sqMetre.toFixed(2)} sq m`;
}
