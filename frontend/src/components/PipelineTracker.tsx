import { Check, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

export interface PipelineStage {
  key: string;
  label: string;
  /** Shown once this stage is active, under the label -- what's actually happening. */
  detail: string;
}

export const PIPELINE_STAGES: PipelineStage[] = [
  { key: "enhance", label: "Enhancing Image", detail: "Deskewing, denoising, and adaptive thresholding the scan" },
  { key: "ocr", label: "Running OCR", detail: "Dual-engine text recognition across the ruled table grid" },
  { key: "extract", label: "Extracting Entities", detail: "Vision-LLM reading owners, areas, and mutation history" },
  { key: "ready", label: "Ready for Review", detail: "Validation and discrepancy checks complete" },
];

/**
 * A vertical stepper showing the extraction pipeline's progress. `activeIndex` is
 * the stage currently running (spinner); everything before it is complete
 * (checkmark), everything after is pending (dimmed). `-1` means nothing has
 * started yet -- all stages render pending.
 */
export function PipelineTracker({ activeIndex, stages = PIPELINE_STAGES }: { activeIndex: number; stages?: PipelineStage[] }) {
  return (
    <ol className="flex flex-col gap-0">
      {stages.map((stage, i) => {
        const status = i < activeIndex ? "done" : i === activeIndex ? "active" : "pending";
        const isLast = i === stages.length - 1;
        return (
          <li key={stage.key} className="relative flex gap-4 pb-8 last:pb-0">
            {!isLast && (
              <span
                className={cn(
                  "absolute left-[15px] top-8 h-[calc(100%-1.75rem)] w-px",
                  status === "done" ? "bg-emerald-400" : "bg-slate-200",
                )}
              />
            )}
            <span
              className={cn(
                "z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 text-sm font-semibold transition-colors",
                status === "done" && "border-emerald-500 bg-emerald-500 text-white",
                status === "active" && "border-navy-700 bg-white text-navy-700",
                status === "pending" && "border-slate-200 bg-white text-slate-300",
              )}
            >
              {status === "done" ? (
                <Check className="h-4 w-4" strokeWidth={3} />
              ) : status === "active" ? (
                <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2.5} />
              ) : (
                i + 1
              )}
            </span>
            <div className="flex-1 pt-0.5">
              <div
                className={cn(
                  "text-sm font-semibold",
                  status === "pending" ? "text-slate-400" : "text-slate-900",
                )}
              >
                {stage.label}
                {status === "active" && <span className="text-navy-700">…</span>}
              </div>
              <div className={cn("mt-0.5 text-xs", status === "pending" ? "text-slate-300" : "text-slate-500")}>
                {stage.detail}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
