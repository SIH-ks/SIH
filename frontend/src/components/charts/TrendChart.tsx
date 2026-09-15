"use client";

import { useMemo, useRef, useState } from "react";

import { cn, formatCount } from "@/lib/format";

/**
 * A multi-series trend chart with a crosshair tooltip.
 *
 * Deliberate choices worth reading:
 *
 * * **One y-axis, always.** Ingested / decided / corrections are all counts of
 *   records, so they share a scale honestly. A second axis would let the chart
 *   invent a correlation that is not in the data — the single most common way a
 *   dashboard chart misleads.
 * * **Every day in the window is a point, including zeros.** A sparse series
 *   drawn as a line implies steady throughput across a gap where nothing
 *   happened.
 * * **A legend is always present, and the last point of each series is directly
 *   labelled.** Identity never rests on colour alone; but a number on *every*
 *   point would be noise, so only the endpoint gets one.
 * * **Hover is not optional.** An SVG chart in a browser is an interactive
 *   object; the crosshair is how a reviewer reads Tuesday's figure rather than
 *   estimating it off the axis.
 */

export interface TrendSeries {
  key: string;
  label: string;
  color: string;
  values: number[];
  /** Area fill under the line. Used for the primary series only — stacking
   * translucent fills turns three readable lines into mud. */
  fill?: boolean;
}

const PAD = { top: 14, right: 16, bottom: 24, left: 34 };

export function TrendChart({
  labels,
  series,
  height = 210,
  valueFormatter = formatCount,
  className,
}: {
  /** One label per x position, already in display form ("10 Sep"). */
  labels: string[];
  series: TrendSeries[];
  height?: number;
  valueFormatter?: (value: number) => string;
  className?: string;
}) {
  const wrapper = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  // A fixed viewBox with `preserveAspectRatio="none"` on the plot would distort
  // the marks; instead the SVG scales as a whole and the geometry is computed in
  // viewBox units, so stroke widths stay visually constant at any container width.
  const WIDTH = 720;
  const plotWidth = WIDTH - PAD.left - PAD.right;
  const plotHeight = height - PAD.top - PAD.bottom;

  const { max, ticks } = useMemo(() => {
    const peak = Math.max(1, ...series.flatMap((s) => s.values));
    // Round the ceiling to a friendly step so the axis reads 0/5/10 rather than
    // 0/3.67/7.33 — an axis a human can do arithmetic against.
    const step = niceStep(peak / 3);
    const ceiling = Math.max(step * 3, Math.ceil(peak / step) * step);
    return { max: ceiling, ticks: [0, ceiling / 3, (ceiling / 3) * 2, ceiling] };
  }, [series]);

  const count = labels.length;
  const x = (index: number) => PAD.left + (count <= 1 ? plotWidth / 2 : (index / (count - 1)) * plotWidth);
  const y = (value: number) => PAD.top + plotHeight - (value / max) * plotHeight;

  const handleMove = (event: React.MouseEvent<HTMLDivElement>) => {
    const box = wrapper.current?.getBoundingClientRect();
    if (!box || count === 0) return;
    const ratio = (event.clientX - box.left) / box.width;
    const svgX = ratio * WIDTH;
    const index = Math.round(((svgX - PAD.left) / plotWidth) * (count - 1));
    setHover(Math.max(0, Math.min(count - 1, index)));
  };

  // Show roughly six x labels regardless of window length, so a 90-day range
  // does not print ninety overlapping dates.
  const labelStride = Math.max(1, Math.ceil(count / 6));

  return (
    <div className={cn("w-full", className)}>
      <Legend series={series} />

      <div
        ref={wrapper}
        className="relative mt-2 w-full"
        onMouseMove={handleMove}
        onMouseLeave={() => setHover(null)}
      >
        <svg
          viewBox={`0 0 ${WIDTH} ${height}`}
          className="w-full"
          style={{ height }}
          role="img"
          aria-label={`Trend of ${series.map((s) => s.label).join(", ")} over ${count} days`}
        >
          {/* Gridlines: solid hairlines one shade off the surface. Dashed rules
              read as "threshold" or "projection" when they are just a grid. */}
          {ticks.map((tick) => (
            <g key={tick}>
              <line
                x1={PAD.left}
                x2={WIDTH - PAD.right}
                y1={y(tick)}
                y2={y(tick)}
                stroke="var(--grid)"
                strokeWidth={1}
              />
              <text
                x={PAD.left - 7}
                y={y(tick) + 3.5}
                textAnchor="end"
                className="fill-[var(--ink-muted)] text-[10px] tabular-nums"
              >
                {Math.round(tick)}
              </text>
            </g>
          ))}

          <line
            x1={PAD.left}
            x2={WIDTH - PAD.right}
            y1={PAD.top + plotHeight}
            y2={PAD.top + plotHeight}
            stroke="var(--axis)"
            strokeWidth={1}
          />

          {labels.map((label, index) =>
            index % labelStride === 0 || index === count - 1 ? (
              <text
                key={`${label}-${index}`}
                x={x(index)}
                y={height - 7}
                textAnchor={index === 0 ? "start" : index === count - 1 ? "end" : "middle"}
                className="fill-[var(--ink-muted)] text-[10px]"
              >
                {label}
              </text>
            ) : null,
          )}

          {series.map((s) =>
            s.fill ? (
              <path
                key={`${s.key}-fill`}
                d={`${linePath(s.values, x, y)} L ${x(count - 1)} ${PAD.top + plotHeight} L ${x(0)} ${
                  PAD.top + plotHeight
                } Z`}
                fill={s.color}
                opacity={0.1}
              />
            ) : null,
          )}

          {series.map((s) => (
            <path
              key={s.key}
              d={linePath(s.values, x, y)}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          ))}

          {hover !== null && (
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={PAD.top}
              y2={PAD.top + plotHeight}
              stroke="var(--axis)"
              strokeWidth={1}
            />
          )}

          {series.map((s) => {
            const last = s.values.length - 1;
            if (last < 0) return null;
            return (
              <g key={`${s.key}-end`}>
                {/* A 2px surface ring, not a stroke of the series colour: where two
                    endpoints coincide, the ring separates them without inventing a
                    third colour. */}
                <circle cx={x(last)} cy={y(s.values[last] ?? 0)} r={4} fill={s.color} stroke="var(--chart-surface)" strokeWidth={2} />
              </g>
            );
          })}

          {hover !== null &&
            series.map((s) => (
              <circle
                key={`${s.key}-hover`}
                cx={x(hover)}
                cy={y(s.values[hover] ?? 0)}
                r={4.5}
                fill={s.color}
                stroke="var(--chart-surface)"
                strokeWidth={2}
              />
            ))}
        </svg>

        {hover !== null && (
          <Tooltip
            leftPercent={((x(hover) - PAD.left) / plotWidth) * 100}
            label={labels[hover] ?? ""}
            rows={series.map((s) => ({
              label: s.label,
              color: s.color,
              value: valueFormatter(s.values[hover] ?? 0),
            }))}
          />
        )}
      </div>
    </div>
  );
}

function Legend({ series }: { series: TrendSeries[] }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5 text-xs">
          <span className="h-0.5 w-4 rounded-full" style={{ background: s.color }} aria-hidden />
          <span className="text-ink-secondary">{s.label}</span>
        </li>
      ))}
    </ul>
  );
}

function Tooltip({
  leftPercent,
  label,
  rows,
}: {
  leftPercent: number;
  label: string;
  rows: { label: string; color: string; value: string }[];
}) {
  // Flip the anchor near the right edge so the panel never hangs off the card.
  const flip = leftPercent > 62;
  return (
    <div
      className="pointer-events-none absolute top-1 z-10 min-w-[152px] rounded-lg border border-line bg-surface-card px-3 py-2 shadow-pop"
      style={{
        left: `${Math.min(Math.max(leftPercent, 2), 98)}%`,
        transform: flip ? "translateX(-104%)" : "translateX(4%)",
      }}
    >
      <p className="text-[11px] font-semibold text-ink-primary">{label}</p>
      <ul className="mt-1.5 flex flex-col gap-1">
        {rows.map((row) => (
          <li key={row.label} className="flex items-center justify-between gap-4 text-[11px]">
            <span className="flex items-center gap-1.5 text-ink-secondary">
              <span className="h-2 w-2 rounded-full" style={{ background: row.color }} aria-hidden />
              {row.label}
            </span>
            <span className="font-mono font-semibold tabular-nums text-ink-primary">{row.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function linePath(
  values: number[],
  x: (index: number) => number,
  y: (value: number) => number,
): string {
  if (values.length === 0) return "";
  return values.map((value, index) => `${index === 0 ? "M" : "L"} ${x(index)} ${y(value)}`).join(" ");
}

/** 1, 2, 5, 10, 20, 50, … — the step sizes people actually count in. */
function niceStep(raw: number): number {
  if (raw <= 1) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}
