"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/format";

/**
 * Three states, not two: light, dark, and *system*.
 *
 * A two-way toggle silently overrides the OS preference the first time it is
 * touched and never gives it back, which is why "follow the system" has to be a
 * reachable state rather than only the initial default.
 *
 * The chosen value is written to `data-theme` on `<html>` and mirrored to
 * `localStorage`; the inline script in `app/layout.tsx` replays it before first
 * paint so a dark-mode user never sees a white flash on navigation.
 */

type ThemeChoice = "light" | "dark" | "system";

export const THEME_STORAGE_KEY = "adhikar-theme";

const OPTIONS: { value: ThemeChoice; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "system", label: "System", icon: Monitor },
  { value: "dark", label: "Dark", icon: Moon },
];

function apply(choice: ThemeChoice) {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, choice);
  } catch {
    // Private browsing, or site data blocked. The theme still applies for this
    // page view; it simply will not be remembered — which is a strictly better
    // outcome than the toggle throwing and taking the header down with it.
  }
}

export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const [choice, setChoice] = useState<ThemeChoice>("system");

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(THEME_STORAGE_KEY) as ThemeChoice | null;
      if (stored === "light" || stored === "dark" || stored === "system") setChoice(stored);
    } catch {
      /* see apply() */
    }
  }, []);

  const select = (value: ThemeChoice) => {
    setChoice(value);
    apply(value);
  };

  if (compact) {
    const next: ThemeChoice = choice === "dark" ? "light" : "dark";
    const Icon = choice === "dark" ? Sun : Moon;
    return (
      <button
        type="button"
        onClick={() => select(next)}
        aria-label={`Switch to ${next} theme`}
        title={`Switch to ${next} theme`}
        className="flex h-8 w-8 items-center justify-center rounded-lg text-white/70 transition-colors hover:bg-white/10 hover:text-white"
      >
        <Icon className="h-4 w-4" strokeWidth={2} aria-hidden />
      </button>
    );
  }

  return (
    <div
      role="radiogroup"
      aria-label="Colour theme"
      className="flex items-center gap-0.5 rounded-lg border border-white/15 bg-white/5 p-0.5"
    >
      {OPTIONS.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={choice === value}
          aria-label={`${label} theme`}
          title={`${label} theme`}
          onClick={() => select(value)}
          className={cn(
            "flex h-6 w-7 items-center justify-center rounded-md transition-colors",
            choice === value ? "bg-white/15 text-white" : "text-white/55 hover:text-white",
          )}
        >
          <Icon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
        </button>
      ))}
    </div>
  );
}
