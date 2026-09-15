"use client";

import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Copy,
  FileText,
  Loader2,
  Trash2,
  UploadCloud,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";

import { Button, Card, CardHeader } from "@/components/ui/Primitives";
import { useToast } from "@/components/ui/Toast";
import { uploadDocument } from "@/lib/client-api";
import { cn, formatBytes } from "@/lib/format";
import type { UploadResponse } from "@/types/parcel";

/**
 * Ingestion: drop a folder of scans, watch each one through the pipeline.
 *
 * Files are uploaded **one at a time, sequentially**, rather than as one batch
 * request. The batch endpoint exists and is the right shape for a server-to-
 * server sync, but from a browser it would report nothing for two minutes and
 * then everything at once. Uploading serially lets each file show its own
 * outcome as it lands — and lets an operator see the third scan fail without
 * waiting for the other forty.
 *
 * Extraction is synchronous on the backend today (OCR + a vision-LLM call per
 * document), so a real scan takes seconds, not milliseconds. The per-file
 * progress states are therefore genuine stages of a real request, not a
 * decorative animation on a fixed timer.
 */

type FileState = "queued" | "uploading" | "done" | "duplicate" | "failed";

interface QueuedFile {
  id: string;
  file: File;
  state: FileState;
  message?: string;
  response?: UploadResponse;
}

const FORMATS = [
  { value: "unknown", label: "Detect automatically" },
  { value: "jamabandi", label: "Jamabandi (Record of Rights)" },
  { value: "satbara_7_12", label: "Satbara — 7/12 Extract" },
  { value: "khasra_girdawari", label: "Khasra Girdawari" },
  { value: "ror_generic", label: "Record of Rights (generic)" },
];

const ACCEPTED = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.webp";

export function UploadWorkbench({ maxFiles, maxSizeMb }: { maxFiles: number; maxSizeMb: number }) {
  const router = useRouter();
  const toast = useToast();
  const inputRef = useRef<HTMLInputElement>(null);

  const [files, setFiles] = useState<QueuedFile[]>([]);
  const [format, setFormat] = useState("unknown");
  const [dragging, setDragging] = useState(false);
  const [running, setRunning] = useState(false);

  const addFiles = useCallback(
    (incoming: FileList | File[]) => {
      const accepted: QueuedFile[] = [];
      for (const file of Array.from(incoming)) {
        if (file.size > maxSizeMb * 1024 * 1024) {
          toast.error(`${file.name} is too large`, `The API accepts files up to ${maxSizeMb} MB.`);
          continue;
        }
        accepted.push({ id: `${file.name}-${file.size}-${file.lastModified}`, file, state: "queued" });
      }
      setFiles((current) => {
        // De-duplicate by name+size+mtime so dropping the same folder twice does
        // not queue every file again.
        const seen = new Set(current.map((entry) => entry.id));
        const merged = [...current, ...accepted.filter((entry) => !seen.has(entry.id))];
        if (merged.length > maxFiles) {
          toast.push({
            tone: "warning",
            title: `Queue capped at ${maxFiles} files`,
            description: "The rest were not added. Upload this batch, then add more.",
          });
        }
        return merged.slice(0, maxFiles);
      });
    },
    [maxFiles, maxSizeMb, toast],
  );

  const start = async () => {
    const pending = files.filter((entry) => entry.state === "queued" || entry.state === "failed");
    if (pending.length === 0) return;

    setRunning(true);
    let succeeded = 0;
    let failed = 0;

    for (const entry of pending) {
      setFiles((current) =>
        current.map((f) => (f.id === entry.id ? { ...f, state: "uploading", message: undefined } : f)),
      );
      try {
        const response = await uploadDocument(entry.file, format);
        const duplicate = response.duplicate_of !== null;
        succeeded += 1;
        setFiles((current) =>
          current.map((f) =>
            f.id === entry.id
              ? {
                  ...f,
                  state: duplicate ? "duplicate" : "done",
                  response,
                  message: response.warnings[0],
                }
              : f,
          ),
        );
      } catch (error) {
        failed += 1;
        setFiles((current) =>
          current.map((f) =>
            f.id === entry.id
              ? {
                  ...f,
                  state: "failed",
                  message: error instanceof Error ? error.message : "Extraction failed.",
                }
              : f,
          ),
        );
      }
    }

    setRunning(false);
    if (succeeded > 0) {
      toast.success(
        `${succeeded} scan${succeeded === 1 ? "" : "s"} ingested`,
        failed > 0 ? `${failed} could not be processed — see the list.` : "Records are in the review queue.",
      );
      router.refresh();
    } else if (failed > 0) {
      toast.error("No scans could be ingested", "Every file in this batch failed — see the reasons below.");
    }
  };

  const totalParcels = files.reduce((sum, entry) => sum + (entry.response?.parcels.length ?? 0), 0);
  const done = files.filter((entry) => entry.state === "done" || entry.state === "duplicate");

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1.1fr_1fr]">
      <div className="flex flex-col gap-5">
        <Card>
          <CardHeader
            title="Add scans"
            subtitle="PDF or image. Drop a whole folder — a bound register is two hundred pages, not two hundred visits to a form."
            icon={UploadCloud}
          />

          <div className="p-4">
            <div
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                if (event.dataTransfer.files.length) addFiles(event.dataTransfer.files);
              }}
              onClick={() => inputRef.current?.click()}
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") inputRef.current?.click();
              }}
              className={cn(
                "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition-colors",
                dragging
                  ? "border-series-1 bg-series-1/[0.06]"
                  : "border-line-strong hover:border-series-1/50 hover:bg-surface-sunken",
              )}
            >
              <UploadCloud className="h-7 w-7 text-ink-muted" strokeWidth={1.7} aria-hidden />
              <p className="mt-3 text-sm font-semibold text-ink-primary">
                Drop scans here, or click to browse
              </p>
              <p className="mt-1 text-xs text-ink-muted">
                Up to {maxFiles} files per batch · {maxSizeMb} MB each · PDF, PNG, JPG, TIFF
              </p>
              <input
                ref={inputRef}
                type="file"
                multiple
                accept={ACCEPTED}
                className="hidden"
                onChange={(event) => {
                  if (event.target.files) addFiles(event.target.files);
                  event.target.value = "";
                }}
              />
            </div>

            <div className="mt-4 flex flex-wrap items-end gap-3">
              <label className="flex flex-1 flex-col gap-1">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
                  Record format
                </span>
                <select
                  value={format}
                  onChange={(event) => setFormat(event.target.value)}
                  className="h-9 rounded-lg border border-line-strong bg-surface-card px-2.5 text-sm text-ink-primary outline-none focus:border-series-1"
                >
                  {FORMATS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </label>

              <Button
                variant="primary"
                icon={running ? Loader2 : UploadCloud}
                disabled={running || files.every((f) => f.state === "done" || f.state === "duplicate")}
                onClick={start}
                className={running ? "[&_svg]:animate-spin" : undefined}
              >
                {running ? "Extracting…" : `Extract ${files.filter((f) => f.state !== "done" && f.state !== "duplicate").length || ""} scan(s)`}
              </Button>

              {files.length > 0 && !running && (
                <Button variant="ghost" icon={Trash2} onClick={() => setFiles([])}>
                  Clear
                </Button>
              )}
            </div>

            <p className="mt-3 text-[11px] leading-relaxed text-ink-muted">
              Each file runs the full pipeline: deskew and denoise → dual-engine OCR → table-grid
              detection → vision-LLM extraction → numeral and vocabulary normalisation → 22 validation
              rules → cadastral discrepancy scoring. Extraction is synchronous here, so a scan takes a
              few seconds; a production deployment would enqueue it and return a polling location.
            </p>
          </div>
        </Card>

        {files.length > 0 && (
          <Card>
            <CardHeader
              title={`Batch (${files.length})`}
              subtitle={
                done.length > 0
                  ? `${done.length} processed · ${totalParcels} parcel${totalParcels === 1 ? "" : "s"} extracted`
                  : "Nothing processed yet"
              }
              icon={FileText}
            />
            <ul className="divide-y divide-line">
              {files.map((entry) => (
                <li key={entry.id} className="flex items-start gap-3 px-4 py-3">
                  <StateIcon state={entry.state} />
                  <div className="min-w-0 flex-1">
                    <p className="flex items-baseline gap-2">
                      <span className="truncate text-[13px] font-medium text-ink-primary">
                        {entry.file.name}
                      </span>
                      <span className="shrink-0 font-mono text-[11px] text-ink-muted">
                        {formatBytes(entry.file.size)}
                      </span>
                    </p>

                    {entry.state === "uploading" && (
                      <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-surface-sunken">
                        <div className="h-full w-1/3 animate-scan-sweep rounded-full bg-series-1" />
                      </div>
                    )}

                    {entry.response && (
                      <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-secondary">
                        <span>
                          <strong className="font-semibold text-ink-primary">
                            {entry.response.parcels.length}
                          </strong>{" "}
                          parcel{entry.response.parcels.length === 1 ? "" : "s"}
                        </span>
                        {entry.response.processing_ms !== null && (
                          <span className="text-ink-muted">
                            · {(entry.response.processing_ms / 1000).toFixed(1)}s
                          </span>
                        )}
                        {entry.response.parcels[0] && (
                          <Link
                            href={`/parcels/${entry.response.parcels[0].id}`}
                            className="inline-flex items-center gap-1 font-semibold text-series-1 hover:underline"
                          >
                            Open <ArrowRight className="h-3 w-3" aria-hidden />
                          </Link>
                        )}
                      </p>
                    )}

                    {entry.message && (
                      <p
                        className={cn(
                          "mt-1 break-anywhere text-xs",
                          entry.state === "failed" ? "text-status-critical-ink" : "text-status-warning-ink",
                        )}
                      >
                        {entry.message}
                      </p>
                    )}
                  </div>

                  {entry.state === "queued" && !running && (
                    <button
                      type="button"
                      onClick={() => setFiles((current) => current.filter((f) => f.id !== entry.id))}
                      aria-label={`Remove ${entry.file.name}`}
                      className="rounded p-1 text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink-primary"
                    >
                      <XCircle className="h-4 w-4" aria-hidden />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>

      <div className="flex flex-col gap-5">
        <Card>
          <CardHeader title="What happens to each page" subtitle="The pipeline, in order" />
          <ol className="flex flex-col gap-0 px-4 py-4">
            {[
              ["Preprocess", "Deskew, denoise and adaptively threshold the raster — OpenCV, with a NumPy-only fallback."],
              ["OCR ensemble", "EasyOCR and Tesseract read the page independently; their boxes are reconciled by IoU overlap."],
              ["Table grid", "Ruled lines are recovered morphologically, so a cell's row and column are known before anything is read from it."],
              ["Vision LLM", "Groq's free tier by default (JSON mode with repair), or Claude Opus with strict tool use for higher accuracy."],
              ["Normalise", "Devanagari numerals, bigha-family units and vernacular classification terms resolved deterministically — never by the model."],
              ["Validate", "22 registered rules for arithmetic, ownership, mutation chain and encumbrance."],
              ["Discrepancy", "Geodesic area against the matched cadastral polygon; a confidence and mismatch score."],
            ].map(([label, detail], index, all) => (
              <li key={label} className="relative flex gap-3.5 pb-4 last:pb-0">
                {index !== all.length - 1 && (
                  <span className="absolute left-[11px] top-6 h-[calc(100%-1rem)] w-px bg-line" aria-hidden />
                )}
                <span className="z-10 mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface-sunken text-[10px] font-bold text-ink-secondary">
                  {index + 1}
                </span>
                <div>
                  <p className="text-[13px] font-semibold text-ink-primary">{label}</p>
                  <p className="mt-0.5 text-xs leading-snug text-ink-muted">{detail}</p>
                </div>
              </li>
            ))}
          </ol>
        </Card>

        <Card className="border-series-1/25 bg-series-1/[0.04]">
          <div className="flex gap-3 px-4 py-4">
            <Copy className="mt-0.5 h-4 w-4 shrink-0 text-series-1" aria-hidden />
            <div>
              <p className="text-[13px] font-semibold text-ink-primary">Re-uploading the same scan is safe</p>
              <p className="mt-1 text-xs leading-relaxed text-ink-secondary">
                Documents are deduplicated by SHA-256 of their contents. A byte-identical file returns
                the existing extraction instead of running OCR again and creating a second set of
                parcels somebody then has to reconcile against the first.
              </p>
            </div>
          </div>
        </Card>

        <Card className="border-brand-green/25 bg-brand-green/[0.04]">
          <div className="flex gap-3 px-4 py-4">
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-brand-green" aria-hidden />
            <div>
              <p className="text-[13px] font-semibold text-ink-primary">What is never extracted</p>
              <p className="mt-1 text-xs leading-relaxed text-ink-secondary">
                Aadhaar numbers, mobile numbers and bank details have no field in the extraction
                schema at all. That is enforced by the Pydantic model the LLM's output is validated
                against — not by a downstream filter that could be misconfigured or switched off.
              </p>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function StateIcon({ state }: { state: FileState }) {
  const shared = "mt-0.5 h-4 w-4 shrink-0";
  switch (state) {
    case "uploading":
      return <Loader2 className={cn(shared, "animate-spin text-series-1")} aria-label="Extracting" />;
    case "done":
      return <CheckCircle2 className={cn(shared, "text-status-good")} aria-label="Extracted" />;
    case "duplicate":
      return <Copy className={cn(shared, "text-status-warning-ink")} aria-label="Already ingested" />;
    case "failed":
      return <AlertTriangle className={cn(shared, "text-status-critical")} aria-label="Failed" />;
    default:
      return <FileText className={cn(shared, "text-ink-muted")} aria-label="Queued" />;
  }
}
