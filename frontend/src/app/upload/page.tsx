"use client";

import { CheckCircle2, FileWarning, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";

import { PIPELINE_STAGES, PipelineTracker } from "@/components/PipelineTracker";
import { UploadDropzone } from "@/components/UploadDropzone";
import { uploadDocument } from "@/lib/api";
import { DEMO_PARCELS } from "@/lib/demoData";

type Phase = "idle" | "processing" | "done" | "error";

/** How long each simulated stage holds, in ms -- tuned to feel like real work
 * without making a reviewer wait: fast enough to demo, slow enough to read. */
const STAGE_DURATIONS_MS = [1100, 1400, 1600, 700];

/**
 * Intelligent Upload Zone: a drag-and-drop target driving a staged pipeline
 * tracker. The stage timing is a client-side simulation (explicitly requested,
 * and it also means the page demos correctly with no backend running) -- but a
 * real upload is attempted in parallel via the actual `/documents/upload`
 * endpoint, so "Ready for Review" links to a genuine newly-created record
 * whenever the backend is reachable, falling back to a demo record otherwise.
 */
export default function UploadPage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [activeStage, setActiveStage] = useState(-1);
  const [fileName, setFileName] = useState<string | null>(null);
  const [resultParcelId, setResultParcelId] = useState<string | null>(null);
  const [usedFallback, setUsedFallback] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  const clearTimers = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };

  const handleFile = (file: File) => {
    clearTimers();
    setPhase("processing");
    setFileName(file.name);
    setActiveStage(0);
    setResultParcelId(null);
    setUsedFallback(false);

    // The real call runs alongside the simulated timer sequence below -- neither
    // waits for the other, since the simulation's purpose is showing the stages
    // regardless of how long (or whether) the actual backend responds.
    const realUpload = uploadDocument(file, "unknown").catch(() => null);

    // Advance one stage index at each stage's own duration boundary. The final
    // timer sets activeStage past the last index (PIPELINE_STAGES.length, not
    // .length - 1) so the "Ready for Review" step itself renders its checkmark
    // rather than sitting at "active" forever.
    let elapsed = 0;
    for (const [i, duration] of STAGE_DURATIONS_MS.slice(0, -1).entries()) {
      elapsed += duration;
      const nextStage = i + 1;
      timers.current.push(setTimeout(() => setActiveStage(nextStage), elapsed));
    }
    elapsed += STAGE_DURATIONS_MS.at(-1) ?? 0;

    timers.current.push(
      setTimeout(async () => {
        setActiveStage(PIPELINE_STAGES.length);
        const uploaded = await realUpload;
        const firstParcel = uploaded?.parcels[0];
        if (firstParcel) {
          setResultParcelId(firstParcel.id);
        } else {
          // Backend unreachable or the upload failed -- fall back to a demo
          // record so "Review this record" still leads somewhere real to click.
          setUsedFallback(true);
          setResultParcelId(DEMO_PARCELS[0]?.id ?? null);
        }
        setPhase("done");
      }, elapsed),
    );
  };

  const reset = () => {
    clearTimers();
    setPhase("idle");
    setActiveStage(-1);
    setFileName(null);
    setResultParcelId(null);
    setUsedFallback(false);
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">Intelligent Upload Zone</h1>
        <p className="mt-1 text-sm text-slate-500">
          Drop a scanned Jamabandi or 7/12 extract to run it through the extraction pipeline.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-card">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">Source Document</h2>
          {phase === "idle" ? (
            <UploadDropzone onFile={handleFile} />
          ) : (
            <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50 px-6 py-16 text-center">
              <div
                className={
                  phase === "done"
                    ? "flex h-14 w-14 items-center justify-center rounded-full bg-emerald-100 text-emerald-600"
                    : "flex h-14 w-14 items-center justify-center rounded-full bg-navy-800/10 text-navy-700"
                }
              >
                {phase === "done" ? <CheckCircle2 className="h-6 w-6" /> : <FileWarning className="h-6 w-6" />}
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-700">{fileName}</p>
                <p className="mt-1 text-xs text-slate-400">
                  {phase === "done" ? "Processing complete" : "Processing…"}
                </p>
              </div>
              <button
                onClick={reset}
                className="mt-2 flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-50"
              >
                <RotateCcw className="h-3.5 w-3.5" /> Upload another
              </button>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-card">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-slate-500">Pipeline Status</h2>
          <PipelineTracker activeIndex={activeStage} />

          {phase === "done" && resultParcelId && (
            <div className="mt-6 rounded-lg border border-emerald-200 bg-emerald-50 p-4">
              <p className="text-sm font-medium text-emerald-800">
                Extraction complete{usedFallback ? " (demo record shown — backend unreachable)" : ""}.
              </p>
              <Link
                href={`/parcels/${resultParcelId}`}
                className="mt-2 inline-flex items-center gap-1 text-sm font-semibold text-navy-700 hover:underline"
              >
                Open in Validation Workspace →
              </Link>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
