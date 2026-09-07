import { cn } from "@/lib/utils";

const CIRC = 2 * Math.PI * 42;

/**
 * Radial arc readout — the mismatch/confidence score rendered as an instrument dial
 * rather than a labelled number in a box. `higherIsBetter` flips which end of the
 * scale reads as "good" (confidence: high is good; mismatch: low is good) so the
 * color ramp is always correct without the caller doing the inversion.
 */
export function Gauge({
  value,
  max = 100,
  label,
  unit = "",
  higherIsBetter = true,
  size = 128,
}: {
  value: number | null;
  max?: number;
  label: string;
  unit?: string;
  higherIsBetter?: boolean;
  size?: number;
}) {
  const pct = value === null ? 0 : Math.max(0, Math.min(1, value / max));
  const goodness = higherIsBetter ? pct : 1 - pct;
  const color =
    value === null
      ? "#576269"
      : goodness > 0.8
        ? "#3ecf8e"
        : goodness > 0.5
          ? "#f5a623"
          : "#ff4d5e";
  const offset = CIRC * (1 - pct);

  return (
    <div className="flex flex-col items-center gap-2" style={{ width: size }}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg viewBox="0 0 100 100" className="-rotate-90" width={size} height={size}>
          <circle cx="50" cy="50" r="42" fill="none" stroke="#1c252d" strokeWidth="6" />
          <circle
            cx="50"
            cy="50"
            r="42"
            fill="none"
            stroke={color}
            strokeWidth="6"
            strokeLinecap="butt"
            strokeDasharray={CIRC}
            strokeDashoffset={offset}
            style={{ filter: `drop-shadow(0 0 4px ${color}80)`, transition: "stroke-dashoffset 0.6s ease" }}
          />
          {/* tick marks every 10% */}
          {Array.from({ length: 10 }).map((_, i) => (
            <line
              key={i}
              x1="50"
              y1="4"
              x2="50"
              y2="8"
              stroke="#2a3641"
              strokeWidth="1"
              transform={`rotate(${i * 36} 50 50)`}
            />
          ))}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-mono text-2xl font-semibold tabular-nums" style={{ color }}>
            {value === null ? "—" : value.toFixed(value % 1 === 0 ? 0 : 1)}
          </span>
          {unit && <span className="font-mono text-[10px] text-ink-dim">{unit}</span>}
        </div>
      </div>
      <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink-dim">{label}</span>
    </div>
  );
}

/** Horizontal segmented meter — used where a compact inline readout fits better
 * than a full radial dial (e.g. inside a table row). */
export function SegmentBar({
  value,
  max = 1,
  segments = 10,
  higherIsBetter = true,
  className,
}: {
  value: number | null;
  max?: number;
  segments?: number;
  higherIsBetter?: boolean;
  className?: string;
}) {
  const pct = value === null ? 0 : Math.max(0, Math.min(1, value / max));
  const filled = Math.round(pct * segments);
  const goodness = higherIsBetter ? pct : 1 - pct;
  const color = value === null ? "bg-ink-faint" : goodness > 0.8 ? "bg-signal-green" : goodness > 0.5 ? "bg-signal-amber" : "bg-signal-red";

  return (
    <div className={cn("flex items-center gap-0.5", className)}>
      {Array.from({ length: segments }).map((_, i) => (
        <span
          key={i}
          className={cn("h-2.5 w-1 shrink-0", i < filled ? color : "bg-seam")}
        />
      ))}
    </div>
  );
}
