"use client";

import { useState } from "react";

import { cn, formatCount } from "@/lib/format";

/**
 * Part-to-whole at a glance, with the total as the hero number in the middle.
 *
 * Constraints this deliberately keeps: at most six segments (past that, adjacent
 * classes blur and a table is the honest form), a 2px surface gap between arcs
 * instead of a stroke, and a legend that names and counts every segment — so the
 * ring is the glance and the legend is the reading. A donut is the wrong chart
 * for comparing two close values; those live in the legend's numbers.
 */

export interface DonutSegment {
  label: string;
  value: number;
  color: string;
}

export function DonutChart({
  segments,
  total,
  centerLabel,
  size = 168,
  thickness = 18,
  className,
}: {
  segments: DonutSegment[];
  /** Overrides the summed total in the centre — useful when the ring shows a
   * subset ("open work") of a larger population. */
  total?: number;
  centerLabel?: string;
  size?: number;
  thickness?: number;
  className?: string;
}) {
  const [hovered, setHovered] = useState<string | null>(null);

  const sum = segments.reduce((acc, s) => acc + s.value, 0);
  const displayTotal = total ?? sum;
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;
  const gap = 2; // px of surface between arcs

  let offset = 0;

  return (
    <div className={cn("flex flex-wrap items-center gap-6", className)}>
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <svg
          width={size}
          height={size}
          viewBox={`0 0 ${size} ${size}`}
          role="img"
          aria-label={`Breakdown of ${displayTotal} records`}
          className="-rotate-90"
        >
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke="var(--surface-sunken)"
            strokeWidth={thickness}
          />
          {sum > 0 &&
            segments.map((segment) => {
              if (segment.value <= 0) return null;
              const fraction = segment.value / sum;
              const length = Math.max(fraction * circumference - gap, 0.5);
              const dash = `${length} ${circumference - length}`;
              const rotation = offset;
              offset += fraction * circumference;
              const dim = hovered !== null && hovered !== segment.label;

              return (
                <circle
                  key={segment.label}
                  cx={size / 2}
                  cy={size / 2}
                  r={radius}
                  fill="none"
                  stroke={segment.color}
                  strokeWidth={thickness}
                  strokeDasharray={dash}
                  strokeDashoffset={-rotation}
                  strokeLinecap="butt"
                  opacity={dim ? 0.32 : 1}
                  className="transition-opacity duration-150"
                  onMouseEnter={() => setHovered(segment.label)}
                  onMouseLeave={() => setHovered(null)}
                >
                  <title>{`${segment.label}: ${formatCount(segment.value)} (${Math.round(fraction * 100)}%)`}</title>
                </circle>
              );
            })}
        </svg>

        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-[26px] font-bold leading-none tracking-tight text-ink-primary">
            {formatCount(hoveredValue(segments, hovered) ?? displayTotal)}
          </span>
          <span className="mt-1 max-w-[80%] text-center text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
            {hovered ?? centerLabel ?? "Total"}
          </span>
        </div>
      </div>

      <ul className="flex min-w-[150px] flex-1 flex-col gap-2">
        {segments.map((segment) => {
          const percent = sum > 0 ? Math.round((segment.value / sum) * 100) : 0;
          return (
            <li
              key={segment.label}
              onMouseEnter={() => setHovered(segment.label)}
              onMouseLeave={() => setHovered(null)}
              className={cn(
                "flex items-center justify-between gap-3 rounded-md px-1.5 py-1 text-xs transition-colors",
                hovered === segment.label && "bg-surface-sunken",
              )}
            >
              <span className="flex min-w-0 items-center gap-2">
                <span
                  className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
                  style={{ background: segment.color }}
                  aria-hidden
                />
                <span className="truncate text-ink-secondary">{segment.label}</span>
              </span>
              <span className="shrink-0 font-mono tabular-nums">
                <span className="font-semibold text-ink-primary">{formatCount(segment.value)}</span>
                <span className="ml-1.5 text-ink-muted">{percent}%</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function hoveredValue(segments: DonutSegment[], hovered: string | null): number | null {
  if (hovered === null) return null;
  return segments.find((s) => s.label === hovered)?.value ?? null;
}
