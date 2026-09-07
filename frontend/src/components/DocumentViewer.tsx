"use client";

import { Maximize2, Minimize2, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";
import type { RealBoundingBox } from "@/types/parcel";

import type { ExtractedFieldKey } from "./ExtractedDataForm";

/**
 * Where each extracted field's value sits on the *mock* scanned page, as a
 * percentage box. This is the fallback source of truth used only when there is no
 * real page image to show (a demo-fixture record, or a field the extraction
 * pipeline doesn't yet attribute a bounding box for) -- the same coordinates draw
 * the placeholder "printed text" block and position its highlight, so the two can
 * never drift out of alignment with each other. A real record with a real bbox
 * (see `adhikar.llm.bbox_attribution`) never touches this table at all.
 */
export const DOCUMENT_FIELD_LAYOUT: Record<
  ExtractedFieldKey,
  { top: number; left: number; width: number; height: number }
> = {
  ownerName: { top: 34, left: 8, width: 52, height: 6 },
  khasraNumber: { top: 22, left: 62, width: 30, height: 6 },
  totalArea: { top: 48, left: 8, width: 38, height: 6 },
  date: { top: 62, left: 8, width: 28, height: 6 },
};

const ZOOM_STEP = 0.25;
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 2.5;

function realBoxToPercent(box: RealBoundingBox) {
  // A small expansion around the matched OCR line, same idea as the mock's -1.5/+3
  // padding: a highlight drawn exactly to the text's own box reads as clipped.
  const pad = 1.5;
  return {
    top: `${Math.max(0, box.y0 * 100 - pad)}%`,
    left: `${Math.max(0, box.x0 * 100 - pad)}%`,
    width: `${Math.min(100, (box.x1 - box.x0) * 100 + pad * 2)}%`,
    height: `${Math.min(100, (box.y1 - box.y0) * 100 + pad * 2)}%`,
  };
}

export function DocumentViewer({
  fileName,
  fields,
  activeField,
  realImageUrl = null,
  realBoxes = {},
}: {
  fileName: string;
  fields: Record<ExtractedFieldKey, string>;
  activeField: ExtractedFieldKey | null;
  /** The actual uploaded page, when this is a real (non-demo) record. `null`
   * falls back to the synthetic mock document. */
  realImageUrl?: string | null;
  /** Real bbox per field, from the pipeline's OCR-line fuzzy match -- only as
   * complete as `adhikar.llm.bbox_attribution` currently covers (today: owner
   * name and total area, not every field). A field with no entry here shows no
   * highlight when focused, rather than a mock position overlaid on real pixels,
   * which would be actively misleading. */
  realBoxes?: Partial<Record<ExtractedFieldKey, RealBoundingBox>>;
}) {
  const [zoom, setZoom] = useState(1);
  const [fullscreen, setFullscreen] = useState(false);
  const isReal = realImageUrl !== null;

  return (
    <div className={cn("flex flex-col rounded-xl border border-slate-200 bg-white shadow-card", fullscreen && "fixed inset-6 z-40")}>
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-700">Document Viewer</h2>
          <p className="text-xs text-slate-400">
            {fileName} · Page 1 of 1
            {!isReal && <span className="ml-1.5 text-amber-600">(simulated document)</span>}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <ToolbarButton onClick={() => setZoom((z) => Math.max(ZOOM_MIN, z - ZOOM_STEP))} title="Zoom out">
            <ZoomOut className="h-4 w-4" />
          </ToolbarButton>
          <span className="w-12 text-center font-mono text-xs text-slate-500">{Math.round(zoom * 100)}%</span>
          <ToolbarButton onClick={() => setZoom((z) => Math.min(ZOOM_MAX, z + ZOOM_STEP))} title="Zoom in">
            <ZoomIn className="h-4 w-4" />
          </ToolbarButton>
          <ToolbarButton onClick={() => setZoom(1)} title="Reset zoom">
            <RotateCcw className="h-4 w-4" />
          </ToolbarButton>
          <ToolbarButton onClick={() => setFullscreen((f) => !f)} title={fullscreen ? "Exit fullscreen" : "Fullscreen"}>
            {fullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </ToolbarButton>
        </div>
      </div>

      <div className="flex-1 overflow-auto bg-slate-100 p-6">
        {isReal ? (
          <div
            className="relative mx-auto w-full max-w-2xl origin-top shadow-lg ring-1 ring-slate-200 transition-transform duration-150"
            style={{ transform: `scale(${zoom})` }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- a dynamic,
                backend-served URL; next/image's remote-pattern allowlist buys
                nothing here and the image is already served pre-sized. */}
            <img src={realImageUrl} alt="Scanned source document" className="block w-full" />

            {activeField && realBoxes[activeField] && (
              <div
                className="absolute rounded-sm border-2 border-amber-500 bg-amber-400/20 shadow-[0_0_0_4px_rgba(245,158,11,0.15)] transition-all duration-200"
                style={realBoxToPercent(realBoxes[activeField]!)}
              />
            )}
          </div>
        ) : (
          <div
            className="relative mx-auto aspect-[8.5/11] w-full max-w-2xl origin-top bg-[#fdfcf8] shadow-lg ring-1 ring-slate-200 transition-transform duration-150"
            style={{ transform: `scale(${zoom})` }}
          >
            {/* Mock printed form -- placeholder text blocks standing in for a real
                scanned document, per the brief. Positions match DOCUMENT_FIELD_LAYOUT
                exactly so the highlight overlay below always lands on the right row. */}
            <div className="absolute left-[8%] top-[6%] w-[84%] border-b border-slate-300 pb-2 text-center">
              <div className="mx-auto h-2.5 w-2/3 rounded-sm bg-slate-700/80" />
              <div className="mx-auto mt-1.5 h-1.5 w-1/3 rounded-sm bg-slate-400/60" />
            </div>

            <MockLabel top={19} left={8} text="Owner Name" />
            <MockField layout={DOCUMENT_FIELD_LAYOUT.ownerName} value={fields.ownerName} />

            <MockLabel top={19} left={62} text="Khasra / Plot No." />
            <MockField layout={DOCUMENT_FIELD_LAYOUT.khasraNumber} value={fields.khasraNumber} />

            <MockLabel top={45} left={8} text="Total Area" />
            <MockField layout={DOCUMENT_FIELD_LAYOUT.totalArea} value={fields.totalArea} />

            <MockLabel top={59} left={8} text="Mutation Date" />
            <MockField layout={DOCUMENT_FIELD_LAYOUT.date} value={fields.date} />

            {/* decorative unrelated rows so the page reads as a real dense form,
                not four isolated fields floating in whitespace */}
            <div className="absolute left-[8%] top-[76%] h-1.5 w-[70%] rounded-sm bg-slate-200" />
            <div className="absolute left-[8%] top-[80%] h-1.5 w-[55%] rounded-sm bg-slate-200" />
            <div className="absolute left-[8%] top-[84%] h-1.5 w-[60%] rounded-sm bg-slate-200" />

            {/* the highlight overlay -- appears only over the currently-focused
                field's mock text block, simulating the extractor "pointing to" the
                source text on the page */}
            {activeField && (
              <div
                className="absolute rounded-sm border-2 border-amber-500 bg-amber-400/20 shadow-[0_0_0_4px_rgba(245,158,11,0.15)] transition-all duration-200"
                style={{
                  top: `${DOCUMENT_FIELD_LAYOUT[activeField].top - 1.5}%`,
                  left: `${DOCUMENT_FIELD_LAYOUT[activeField].left - 1.5}%`,
                  width: `${DOCUMENT_FIELD_LAYOUT[activeField].width + 3}%`,
                  height: `${DOCUMENT_FIELD_LAYOUT[activeField].height + 3}%`,
                }}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function MockLabel({ top, left, text }: { top: number; left: number; text: string }) {
  return (
    <div
      className="absolute text-[9px] font-medium uppercase tracking-wide text-slate-400"
      style={{ top: `${top}%`, left: `${left}%` }}
    >
      {text}
    </div>
  );
}

function MockField({
  layout,
  value,
}: {
  layout: { top: number; left: number; width: number; height: number };
  value: string;
}) {
  return (
    <div
      className="absolute flex items-center rounded-sm bg-slate-800/[0.06] px-1.5 font-mono text-[11px] text-slate-700"
      style={{ top: `${layout.top}%`, left: `${layout.left}%`, width: `${layout.width}%`, height: `${layout.height}%` }}
    >
      <span className="truncate">{value || "—"}</span>
    </div>
  );
}

function ToolbarButton({
  children,
  onClick,
  title,
}: {
  children: React.ReactNode;
  onClick: () => void;
  title: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="flex h-8 w-8 items-center justify-center rounded-md text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-800"
    >
      {children}
    </button>
  );
}
