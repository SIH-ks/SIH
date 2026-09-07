import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * The base HUD panel: sharp corners (no border-radius), a hairline border, a
 * bracket accent at each corner, and an optional title bar with a live status dot.
 * Every data surface in this app is one of these — the console reads as one
 * instrument panel, not a stack of unrelated cards.
 */
export function Panel({
  title,
  eyebrow,
  right,
  live,
  className,
  bodyClassName,
  children,
}: {
  title?: string;
  eyebrow?: string;
  right?: ReactNode;
  live?: boolean;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        "hud-corners relative border border-seam bg-hull text-signal-cyan",
        className,
      )}
    >
      <span className="corner-tl" />
      <span className="corner-br" />
      {(title || eyebrow) && (
        <div className="flex items-center justify-between border-b border-seam bg-plate px-3.5 py-2">
          <div className="flex items-center gap-2">
            {live && <LiveDot />}
            <div>
              {eyebrow && (
                <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink-dim">
                  {eyebrow}
                </div>
              )}
              {title && (
                <div className="font-display text-xs font-semibold uppercase tracking-wide text-ink-primary">
                  {title}
                </div>
              )}
            </div>
          </div>
          {right}
        </div>
      )}
      <div className={cn("text-ink-primary", bodyClassName)}>{children}</div>
    </div>
  );
}

export function LiveDot({ color = "signal-green" }: { color?: "signal-green" | "signal-amber" | "signal-red" }) {
  const dot = {
    "signal-green": "bg-signal-green",
    "signal-amber": "bg-signal-amber",
    "signal-red": "bg-signal-red",
  }[color];
  return (
    <span className="relative flex h-1.5 w-1.5">
      <span className={cn("absolute inline-flex h-full w-full animate-pulse-ring rounded-full", dot)} />
      <span className={cn("relative inline-flex h-1.5 w-1.5 rounded-full", dot)} />
    </span>
  );
}
