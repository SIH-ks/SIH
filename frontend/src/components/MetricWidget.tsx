import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * A top-level KPI card for the Command Dashboard. Deliberately plain -- a number,
 * a label, an icon, and an optional trend line -- because the dashboard's job is
 * fast scanning, not chart-reading; anything more elaborate here competes with the
 * table for attention instead of framing it.
 */
export function MetricWidget({
  icon: Icon,
  label,
  value,
  suffix,
  trend,
  tone = "navy",
}: {
  icon: LucideIcon;
  label: string;
  value: string | number;
  suffix?: string;
  trend?: { direction: "up" | "down"; label: string };
  tone?: "navy" | "green" | "amber" | "red";
}) {
  const toneClasses: Record<typeof tone, string> = {
    navy: "bg-navy-800/5 text-navy-800",
    green: "bg-emerald-50 text-emerald-700",
    amber: "bg-amber-50 text-amber-700",
    red: "bg-red-50 text-red-700",
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-card transition-shadow hover:shadow-card-hover">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-slate-500">{label}</span>
        <div className={cn("flex h-9 w-9 items-center justify-center rounded-lg", toneClasses[tone])}>
          <Icon className="h-[18px] w-[18px]" strokeWidth={2} />
        </div>
      </div>
      <div className="mt-3 flex items-baseline gap-1.5">
        <span className="text-3xl font-bold tracking-tight text-slate-900">{value}</span>
        {suffix && <span className="text-lg font-semibold text-slate-400">{suffix}</span>}
      </div>
      {trend && (
        <div
          className={cn(
            "mt-2 text-xs font-medium",
            trend.direction === "up" ? "text-emerald-600" : "text-red-600",
          )}
        >
          {trend.direction === "up" ? "▲" : "▼"} {trend.label}
        </div>
      )}
    </div>
  );
}
