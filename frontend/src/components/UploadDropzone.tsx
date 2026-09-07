"use client";

import { FileText, UploadCloud } from "lucide-react";
import { useCallback, useRef, useState } from "react";

import { cn } from "@/lib/utils";

const ACCEPTED_TYPES = ["application/pdf", "image/png", "image/jpeg", "image/tiff"];

/**
 * The drag-and-drop target. Accepts a drop, a paste-into-browse click, and
 * (implicitly, since it's a real file input under the hood) a keyboard-driven
 * file picker -- drag-and-drop alone would leave keyboard users with no way in.
 */
export function UploadDropzone({
  onFile,
  disabled = false,
}: {
  onFile: (file: File) => void;
  disabled?: boolean;
}) {
  const [isDragging, setIsDragging] = useState(false);
  const [rejected, setRejected] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const acceptFile = useCallback(
    (file: File | undefined) => {
      if (!file) return;
      if (!ACCEPTED_TYPES.includes(file.type)) {
        setRejected(`${file.name} isn't a supported format (PDF, PNG, JPEG, TIFF).`);
        return;
      }
      setRejected(null);
      onFile(file);
    },
    [onFile],
  );

  return (
    <div className="flex flex-col gap-2">
      <div
        role="button"
        tabIndex={0}
        onClick={() => !disabled && inputRef.current?.click()}
        onKeyDown={(e) => {
          if (!disabled && (e.key === "Enter" || e.key === " ")) inputRef.current?.click();
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          if (!disabled) acceptFile(e.dataTransfer.files?.[0]);
        }}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-16 text-center transition-colors",
          disabled && "cursor-not-allowed opacity-60",
          isDragging
            ? "border-navy-600 bg-navy-800/5"
            : "border-slate-300 bg-white hover:border-navy-600/50 hover:bg-slate-50",
        )}
      >
        <div
          className={cn(
            "flex h-14 w-14 items-center justify-center rounded-full transition-colors",
            isDragging ? "bg-navy-800 text-white" : "bg-slate-100 text-slate-400",
          )}
        >
          {isDragging ? <FileText className="h-6 w-6" /> : <UploadCloud className="h-6 w-6" />}
        </div>
        <div>
          <p className="text-sm font-semibold text-slate-700">
            {isDragging ? "Drop to upload" : "Drag & drop a scanned record"}
          </p>
          <p className="mt-1 text-xs text-slate-400">or click to browse — PDF, PNG, JPEG, TIFF</p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_TYPES.join(",")}
          className="hidden"
          disabled={disabled}
          onChange={(e) => acceptFile(e.target.files?.[0])}
        />
      </div>
      {rejected && <p className="text-xs font-medium text-red-600">{rejected}</p>}
    </div>
  );
}
