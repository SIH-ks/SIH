"use client";

import { useId, useState } from "react";

import { cn, formatCount } from "@/lib/format";

/**
 * A horizontal bar list — the right form for "which of these categories is
 * biggest", which is most of what this console's analytics ask.
 *
 * Horizontal rather than vertical because the categories are long text labels
 * (district names, rule codes like `MUTATION_DATE_IN_FUTURE`). A vertical bar
 * chart would rotate them to 45°, and rotated labels are measurably slower to
 * read than horizontal ones.
 *
 * One series → one colour for every bar. Colouring each bar darker-where-bigger
 * would double-encode the length the bar already shows and burn the only free
 * channel on nothing. Where a bar genuinely carries a *state* (a rule's worst
 * severity) that is a status colour, and it arrives with a written label beside
 * it, never as hue alone.
 */

export interface BarDatum {
  label: string;
  value: number;
  /** Optional secondary line under the label — a district's state, a rule's group. */
  sublabel?: string;
  /** Fill override for status-carrying bars. Must be a CSS colour (a token). */
  color?: string;
  /** Rendered at the right of the row instead of the raw count. */
  valueLabel?: string;
  href?: string;
}

export function BarList({
  data,
  max,
  emptyMessage = "No data in range.",
  showValues = true,
  compact = false,
  className,
}: {
  data: BarDatum[];
  /** Scale ceiling. Defaults to the largest value; pass a fixed number when two
   * lists must be visually comparable. */
  max?: number;
  emptyMessage?: string;
  showValues?: boolean;
  compact?: boolean;
  className?: string;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const ceiling = max ?? Math.max(...data.map((d) => d.value), 1);

  if (data.length === 0) {
    return <p className="px-4 py-8 text-center text-sm text-ink-muted">{emptyMessage}</p>;
  }

  return (
    <ul className={cn("flex flex-col", compact ? "gap-2.5" : "gap-3.5", className)}>
      {data.map((datum, index) => {
        const fraction = ceiling > 0 ? Math.max(datum.value / ceiling, 0) : 0;
        const active = hovered === index;
        const Row = datum.href ? "a" : "div";

        return (
          <li key={`${datum.label}-${index}`}>
            <Row
              {...(datum.href ? { href: datum.href } : {})}
              onMouseEnter={() => setHovered(index)}
              onMouseLeave={() => setHovered(null)}
              className={cn("block", datum.href && "cursor-pointer")}
              title={`${datum.label}: ${formatCount(datum.value)}`}
            >
              <div className="flex items-baseline justify-between gap-3">
                <span
                  className={cn(
                    "min-w-0 truncate text-[13px] font-medium transition-colors",
                    active ? "text-ink-primary" : "text-ink-secondary",
                  )}
                >
                  {datum.label}
                  {datum.sublabel && (
                    <span className="ml-1.5 text-[11px] font-normal text-ink-muted">{datum.sublabel}</span>
                  )}
                </span>
                {showValues && (
                  <span className="shrink-0 font-mono text-xs font-semibold tabular-nums text-ink-primary">
                    {datum.valueLabel ?? formatCount(datum.value)}
                  </span>
                )}
              </div>

              {/* The track is a hairline recess, not a competing bar: at 6px with a
                  surface-adjacent fill it reads as the axis, which is what lets the
                  data bar stay thin and still be the only thing you see. */}
              <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken">
                <div
                  className="h-full rounded-full transition-[width,opacity] duration-500 ease-out"
                  style={{
                    width: `${Math.max(fraction * 100, datum.value > 0 ? 1.5 : 0)}%`,
                    background: datum.color ?? "var(--series-1)",
                    opacity: hovered === null || active ? 1 : 0.45,
                  }}
                />
              </div>
            </Row>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * A stacked proportion bar: one row, several segments, part-to-whole at a glance.
 *
 * Segments are separated by a 2px surface gap rather than a stroke — a border
 * drawn around a mark competes with the mark, while a gap just lets the surface
 * through. Every segment is also named in the legend below, so no meaning is
 * carried by colour alone.
 */
export function ProportionBar({
  segments,
  className,
  height = "h-2.5",
}: {
  segments: { label: string; value: number; color: string }[];
  className?: string;
  height?: string;
}) {
  const id = useId();
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  const visible = segments.filter((s) => s.value > 0);

  if (total === 0) {
    return <div className={cn("w-full rounded-full bg-surface-sunken", height, className)} />;
  }

  return (
    <div className={className}>
      <div className={cn("flex w-full gap-[2px] overflow-hidden rounded-full", height)}>
        {visible.map((segment) => (
          <div
            key={`${id}-${segment.label}`}
            className="h-full first:rounded-l-full last:rounded-r-full"
            style={{ width: `${(segment.value / total) * 100}%`, background: segment.color }}
            title={`${segment.label}: ${formatCount(segment.value)} (${Math.round((segment.value / total) * 100)}%)`}
          />
        ))}
      </div>
      <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5">
        {segments.map((segment) => (
          <li key={`${id}-legend-${segment.label}`} className="flex items-center gap-1.5 text-xs">
            <span
              className="h-2 w-2 shrink-0 rounded-[2px]"
              style={{ background: segment.color }}
              aria-hidden
            />
            <span className="text-ink-secondary">{segment.label}</span>
            <span className="font-mono font-semibold tabular-nums text-ink-primary">{segment.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
