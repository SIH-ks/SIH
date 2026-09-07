const CIRCUMFERENCE = 2 * Math.PI * 42;

/**
 * A radial arc readout for the mismatch/confidence scores -- an instrument dial
 * reads as "measured" in a way a bare number in a stat card doesn't, which matters
 * for a system whose whole point is telling a reviewer how much to trust a value.
 *
 * `higherIsBetter` flips which end of the scale reads as good (confidence: high is
 * good; mismatch: low is good) so the color ramp is always correct without the
 * caller inverting anything.
 */
export function Gauge({
  value,
  max = 100,
  label,
  unit = "",
  higherIsBetter = true,
  size = 120,
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
    value === null ? "#cbd5e1" : goodness > 0.8 ? "#10b981" : goodness > 0.5 ? "#f59e0b" : "#ef4444";
  const offset = CIRCUMFERENCE * (1 - pct);

  return (
    <div className="flex flex-col items-center gap-2" style={{ width: size }}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg viewBox="0 0 100 100" className="-rotate-90" width={size} height={size}>
          <circle cx="50" cy="50" r="42" fill="none" stroke="#e2e8f0" strokeWidth="7" />
          <circle
            cx="50"
            cy="50"
            r="42"
            fill="none"
            stroke={color}
            strokeWidth="7"
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            strokeDashoffset={offset}
            style={{ transition: "stroke-dashoffset 0.6s ease" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-mono text-2xl font-bold tabular-nums" style={{ color }}>
            {value === null ? "—" : value.toFixed(value % 1 === 0 ? 0 : 1)}
          </span>
          {unit && <span className="text-[10px] font-medium text-slate-400">{unit}</span>}
        </div>
      </div>
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>
    </div>
  );
}
