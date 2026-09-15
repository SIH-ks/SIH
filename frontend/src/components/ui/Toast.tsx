"use client";

import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState } from "react";

import { cn } from "@/lib/format";

/**
 * Transient feedback for actions that happen without a page change.
 *
 * A reviewer who approves a record needs to know it landed; a correction that
 * failed validation needs to say why. Errors are given a longer life than
 * successes and can be dismissed but never auto-hide below eight seconds —
 * a message a reviewer misses is the same as no message, and "did that save?"
 * is the question this component exists to prevent.
 */

type ToastTone = "success" | "error" | "info" | "warning";

interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
}

interface ToastApi {
  push: (toast: Omit<Toast, "id">) => void;
  success: (title: string, description?: string) => void;
  error: (title: string, description?: string) => void;
  info: (title: string, description?: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside <ToastProvider>");
  return context;
}

const TONE = {
  success: { icon: CheckCircle2, ring: "ring-status-good/35", accent: "bg-status-good", ink: "text-status-good-ink" },
  error: { icon: XCircle, ring: "ring-status-critical/35", accent: "bg-status-critical", ink: "text-status-critical-ink" },
  warning: { icon: AlertTriangle, ring: "ring-status-warning/35", accent: "bg-status-warning", ink: "text-status-warning-ink" },
  info: { icon: Info, ring: "ring-series-1/30", accent: "bg-series-1", ink: "text-series-1" },
} as const;

let nextId = 1;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = nextId++;
      setToasts((current) => [...current.slice(-3), { ...toast, id }]);
      const lifetime = toast.tone === "error" ? 8000 : 4000;
      window.setTimeout(() => dismiss(id), lifetime);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      push,
      success: (title, description) => push({ tone: "success", title, description }),
      error: (title, description) => push({ tone: "error", title, description }),
      info: (title, description) => push({ tone: "info", title, description }),
    }),
    [push],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        // `aria-live="polite"` rather than "assertive": these announce completed
        // work, and interrupting a screen reader mid-sentence to say "saved" is
        // more disruptive than waiting for a pause.
        aria-live="polite"
        className="pointer-events-none fixed bottom-5 right-5 z-[80] flex w-[min(360px,calc(100vw-2.5rem))] flex-col gap-2.5"
      >
        {toasts.map((toast) => {
          const tone = TONE[toast.tone];
          const Icon = tone.icon;
          return (
            <div
              key={toast.id}
              className={cn(
                "pointer-events-auto relative flex animate-slide-in items-start gap-3 overflow-hidden rounded-xl bg-surface-card py-3 pl-4 pr-9 shadow-pop ring-1",
                tone.ring,
              )}
            >
              <span className={cn("absolute inset-y-0 left-0 w-[3px]", tone.accent)} aria-hidden />
              <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", tone.ink)} strokeWidth={2.2} aria-hidden />
              <div className="min-w-0">
                <p className="text-[13px] font-semibold text-ink-primary">{toast.title}</p>
                {toast.description && (
                  <p className="mt-0.5 break-anywhere text-xs text-ink-secondary">{toast.description}</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => dismiss(toast.id)}
                aria-label="Dismiss notification"
                className="absolute right-2 top-2.5 rounded p-1 text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink-primary"
              >
                <X className="h-3.5 w-3.5" aria-hidden />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
