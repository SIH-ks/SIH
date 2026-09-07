"use client";

import { Check, Loader2 } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

export type ExtractedFieldKey = "ownerName" | "khasraNumber" | "totalArea" | "date";

export interface ExtractedFieldConfig {
  key: ExtractedFieldKey;
  label: string;
  confidence: number | null;
}

export const EXTRACTED_FIELD_ORDER: ExtractedFieldConfig[] = [
  { key: "ownerName", label: "Owner Name", confidence: null },
  { key: "khasraNumber", label: "Khasra / Plot Number", confidence: null },
  { key: "totalArea", label: "Total Area", confidence: null },
  { key: "date", label: "Date", confidence: null },
];

/**
 * The right-hand data-extractor panel: one input per extracted field. Focusing a
 * field is the entire interaction this panel exists to drive -- `onFieldFocus`
 * fires the field key up to the workspace, which is what makes the document
 * viewer's highlight box track the input the reviewer is looking at. Blurring
 * clears the highlight (passes `null`) rather than leaving the last box stuck on
 * screen after the reviewer has moved on.
 */
export function ExtractedDataForm({
  values,
  fieldMeta = EXTRACTED_FIELD_ORDER,
  onChange,
  onFieldFocus,
  onSave,
}: {
  values: Record<ExtractedFieldKey, string>;
  fieldMeta?: ExtractedFieldConfig[];
  onChange: (key: ExtractedFieldKey, value: string) => void;
  onFieldFocus: (key: ExtractedFieldKey | null) => void;
  onSave?: () => Promise<void> | void;
}) {
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle");

  const handleSave = async () => {
    if (!onSave) return;
    setSaveState("saving");
    await onSave();
    setSaveState("saved");
    setTimeout(() => setSaveState("idle"), 2000);
  };

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-card">
      <div className="border-b border-slate-200 px-4 py-3">
        <h2 className="text-sm font-semibold text-slate-700">Extracted Data</h2>
        <p className="text-xs text-slate-400">Focus a field to locate it on the source document</p>
      </div>

      <div className="flex flex-col gap-4 p-4">
        {fieldMeta.map(({ key, label, confidence }) => (
          <div key={key}>
            <div className="mb-1.5 flex items-center justify-between">
              <label htmlFor={`field-${key}`} className="text-xs font-medium text-slate-500">
                {label}
              </label>
              {confidence !== null && (
                <span
                  className={cn(
                    "font-mono text-[10px]",
                    confidence >= 0.85 ? "text-emerald-600" : confidence >= 0.6 ? "text-amber-600" : "text-red-600",
                  )}
                >
                  {Math.round(confidence * 100)}% confidence
                </span>
              )}
            </div>
            <input
              id={`field-${key}`}
              type="text"
              value={values[key]}
              onChange={(e) => onChange(key, e.target.value)}
              onFocus={() => onFieldFocus(key)}
              onBlur={() => onFieldFocus(null)}
              className="w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 transition-colors focus:border-amber-500 focus:outline-none focus:ring-2 focus:ring-amber-500/20"
            />
          </div>
        ))}
      </div>

      {onSave && (
        <div className="border-t border-slate-200 px-4 py-3">
          <button
            type="button"
            onClick={handleSave}
            disabled={saveState !== "idle"}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-navy-800 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-navy-700 disabled:opacity-70"
          >
            {saveState === "saving" && <Loader2 className="h-4 w-4 animate-spin" />}
            {saveState === "saved" && <Check className="h-4 w-4" />}
            {saveState === "idle" ? "Confirm & Save Corrections" : saveState === "saving" ? "Saving…" : "Saved"}
          </button>
        </div>
      )}
    </div>
  );
}
