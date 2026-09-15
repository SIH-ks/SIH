"use client";

import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  FileWarning,
  Maximize2,
  Minimize2,
  RotateCcw,
  RotateCw,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/format";
import type { RealBoundingBox } from "@/types/parcel";

const ZOOM_STEP = 0.25;
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 3;

/**
 * The source scan, beside the data extracted from it.
 *
 * Two behaviours matter more than the toolbar:
 *
 * * **The highlight is drawn only from a real bounding box.** When the pipeline
 *   attributed a field to a specific OCR line (`adhikar.llm.bbox_attribution`),
 *   focusing that field outlines it on the page. When it did not, *nothing* is
 *   drawn — a plausible-looking rectangle in roughly the right place would be a
 *   claim the system cannot support, and a reviewer would trust it.
 * * **Rotation exists because scans arrive sideways.** A bound register
 *   photographed on a phone is routinely 90° out, and re-scanning it is a trip
 *   back to the record room.
 */
export function DocumentViewer({
  pageUrls,
  fileName,
  activeBox,
  activeLabel,
  className,
}: {
  /** Absolute URLs of the rendered pages, in order. Empty when the record has no
   * stored raster (a seeded row, or an ingestion that stored only text). */
  pageUrls: string[];
  fileName: string;
  /** The box to outline, when the focused field has real attribution. */
  activeBox?: RealBoundingBox | null;
  activeLabel?: string;
  className?: string;
}) {
  const [pageIndex, setPageIndex] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [rotation, setRotation] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);

  // A bbox carries the page it was found on; following it is what makes
  // "focus the owner name" work on a multi-page Jamabandi rather than only on
  // whichever page happens to be open.
  useEffect(() => {
    if (activeBox && activeBox.page_index !== pageIndex && activeBox.page_index < pageUrls.length) {
      setPageIndex(activeBox.page_index);
    }
  }, [activeBox, pageIndex, pageUrls.length]);

  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFullscreen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fullscreen]);

  const hasPages = pageUrls.length > 0;
  const currentUrl = pageUrls[pageIndex];
  const boxOnThisPage = activeBox && activeBox.page_index === pageIndex ? activeBox : null;

  return (
    <div
      className={cn(
        "flex flex-col overflow-hidden rounded-xl border border-line bg-surface-card shadow-card",
        fullscreen && "fixed inset-4 z-[60] shadow-pop",
        className,
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2.5">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-ink-primary">Source scan</h2>
          <p className="truncate text-xs text-ink-muted">
            {fileName}
            {hasPages ? ` · page ${pageIndex + 1} of ${pageUrls.length}` : " · no raster stored"}
          </p>
        </div>

        <div className="flex items-center gap-0.5">
          {pageUrls.length > 1 && (
            <>
              <ToolbarButton
                onClick={() => setPageIndex((index) => Math.max(0, index - 1))}
                disabled={pageIndex === 0}
                title="Previous page"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden />
              </ToolbarButton>
              <ToolbarButton
                onClick={() => setPageIndex((index) => Math.min(pageUrls.length - 1, index + 1))}
                disabled={pageIndex === pageUrls.length - 1}
                title="Next page"
              >
                <ChevronRight className="h-4 w-4" aria-hidden />
              </ToolbarButton>
              <span className="mx-1 h-4 w-px bg-line" aria-hidden />
            </>
          )}
          <ToolbarButton onClick={() => setZoom((z) => Math.max(ZOOM_MIN, z - ZOOM_STEP))} title="Zoom out">
            <ZoomOut className="h-4 w-4" aria-hidden />
          </ToolbarButton>
          <span className="w-11 text-center font-mono text-xs tabular-nums text-ink-muted">
            {Math.round(zoom * 100)}%
          </span>
          <ToolbarButton onClick={() => setZoom((z) => Math.min(ZOOM_MAX, z + ZOOM_STEP))} title="Zoom in">
            <ZoomIn className="h-4 w-4" aria-hidden />
          </ToolbarButton>
          <ToolbarButton onClick={() => setRotation((r) => (r + 270) % 360)} title="Rotate left">
            <RotateCcw className="h-4 w-4" aria-hidden />
          </ToolbarButton>
          <ToolbarButton onClick={() => setRotation((r) => (r + 90) % 360)} title="Rotate right">
            <RotateCw className="h-4 w-4" aria-hidden />
          </ToolbarButton>
          {currentUrl && (
            <ToolbarButton
              onClick={() => window.open(currentUrl, "_blank", "noopener")}
              title="Open the full-resolution page in a new tab"
            >
              <ExternalLink className="h-4 w-4" aria-hidden />
            </ToolbarButton>
          )}
          <ToolbarButton
            onClick={() => setFullscreen((current) => !current)}
            title={fullscreen ? "Exit fullscreen (Esc)" : "Fullscreen"}
          >
            {fullscreen ? <Minimize2 className="h-4 w-4" aria-hidden /> : <Maximize2 className="h-4 w-4" aria-hidden />}
          </ToolbarButton>
        </div>
      </div>

      <div className={cn("flex-1 overflow-auto bg-surface-sunken p-5", fullscreen ? "" : "max-h-[560px]")}>
        {hasPages ? (
          <div
            className="relative mx-auto w-full max-w-2xl origin-top ring-1 ring-line transition-transform duration-150"
            style={{ transform: `scale(${zoom}) rotate(${rotation}deg)` }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- a dynamic,
                backend-served URL; next/image's remote-pattern allowlist buys
                nothing here and the image is already served pre-sized. */}
            <img src={currentUrl} alt={`Scanned page ${pageIndex + 1} of ${fileName}`} className="block w-full" />

            {boxOnThisPage && (
              <div
                className="pointer-events-none absolute rounded-sm border-2 border-brand-saffron bg-brand-saffron/20 shadow-[0_0_0_4px_rgba(217,119,6,0.15)] transition-all duration-200"
                style={toPercent(boxOnThisPage)}
              >
                {activeLabel && (
                  <span className="absolute -top-5 left-0 whitespace-nowrap rounded bg-brand-saffron px-1.5 py-0.5 text-[10px] font-semibold text-white">
                    {activeLabel}
                  </span>
                )}
              </div>
            )}
          </div>
        ) : (
          <div className="flex h-full min-h-[280px] flex-col items-center justify-center gap-2 text-center">
            <FileWarning className="h-6 w-6 text-ink-muted" aria-hidden />
            <p className="text-sm font-semibold text-ink-primary">No page image stored for this record</p>
            <p className="max-w-sm text-xs text-ink-muted">
              The extraction artifact carries OCR text, never pixels. Records ingested through the
              upload endpoint keep their rendered pages; this one was written directly to the
              database.
            </p>
          </div>
        )}
      </div>

      {hasPages && (
        <p className="border-t border-line px-4 py-2 text-[11px] text-ink-muted">
          {activeBox
            ? "Highlight drawn from the OCR line the extractor actually matched this value to."
            : "Focus a field on the right to locate it on the page — only fields with real bounding-box attribution can be highlighted."}
        </p>
      )}
    </div>
  );
}

function toPercent(box: RealBoundingBox) {
  // A small expansion around the matched OCR line: a highlight drawn exactly to
  // the text's own box reads as clipped.
  const pad = 1.5;
  return {
    top: `${Math.max(0, box.y0 * 100 - pad)}%`,
    left: `${Math.max(0, box.x0 * 100 - pad)}%`,
    width: `${Math.min(100, (box.x1 - box.x0) * 100 + pad * 2)}%`,
    height: `${Math.min(100, (box.y1 - box.y0) * 100 + pad * 2)}%`,
  };
}

function ToolbarButton({
  children,
  onClick,
  title,
  disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  title: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      disabled={disabled}
      className="flex h-8 w-8 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink-primary disabled:cursor-not-allowed disabled:opacity-35"
    >
      {children}
    </button>
  );
}
