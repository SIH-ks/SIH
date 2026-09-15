import type { Config } from "tailwindcss";

/**
 * Every colour here resolves to a CSS custom property defined in
 * `src/app/globals.css`. That indirection is the point: light and dark are two
 * value sets for one token vocabulary, so a component is written once against
 * `bg-surface-card` / `text-ink-secondary` and is correct in both themes
 * without a single `dark:` variant to keep in sync.
 *
 * `darkMode: "class"` (rather than `"media"`) because the console has an
 * explicit theme toggle — a reviewer working a night shift under an office
 * machine's fixed light setting needs to be able to override the OS.
 */
const config: Config = {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          page: "var(--surface-page)",
          card: "var(--surface-card)",
          sunken: "var(--surface-sunken)",
          raised: "var(--surface-raised)",
          inverse: "var(--surface-inverse)",
        },
        ink: {
          DEFAULT: "var(--ink-primary)",
          primary: "var(--ink-primary)",
          secondary: "var(--ink-secondary)",
          muted: "var(--ink-muted)",
          inverse: "var(--ink-inverse)",
        },
        line: {
          DEFAULT: "var(--line-hairline)",
          hairline: "var(--line-hairline)",
          strong: "var(--line-strong)",
        },
        brand: {
          navy: "var(--brand-navy)",
          // Keyed "navy-deep" (not "deep") so the class reads `bg-brand-navy-deep`,
          // matching the CSS custom property it resolves to. A mismatch here emits
          // no rule at all rather than an error: the element simply loses its
          // background, which is invisible on a dark page and glaring on a light one.
          "navy-deep": "var(--brand-navy-deep)",
          saffron: "var(--brand-saffron)",
          green: "var(--brand-green)",
        },
        // Data-visualization slots. Assigned in fixed order, never cycled past 8.
        series: {
          1: "var(--series-1)",
          2: "var(--series-2)",
          3: "var(--series-3)",
          4: "var(--series-4)",
          5: "var(--series-5)",
          6: "var(--series-6)",
          7: "var(--series-7)",
          8: "var(--series-8)",
        },
        status: {
          good: "var(--status-good)",
          warning: "var(--status-warning)",
          serious: "var(--status-serious)",
          critical: "var(--status-critical)",
          "good-ink": "var(--status-good-ink)",
          "warning-ink": "var(--status-warning-ink)",
          "serious-ink": "var(--status-serious-ink)",
          "critical-ink": "var(--status-critical-ink)",
          "good-wash": "var(--status-good-wash)",
          "warning-wash": "var(--status-warning-wash)",
          "serious-wash": "var(--status-serious-wash)",
          "critical-wash": "var(--status-critical-wash)",
        },
        chart: {
          surface: "var(--chart-surface)",
          grid: "var(--grid)",
          axis: "var(--axis)",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "Consolas", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px 0 rgba(15, 37, 87, 0.05), 0 1px 3px 0 rgba(15, 37, 87, 0.07)",
        "card-hover": "0 6px 18px -4px rgba(15, 37, 87, 0.14)",
        pop: "0 16px 40px -12px rgba(15, 37, 87, 0.28)",
      },
      keyframes: {
        "pulse-soft": { "0%, 100%": { opacity: "1" }, "50%": { opacity: "0.45" } },
        "scan-sweep": { "0%": { transform: "translateX(-100%)" }, "100%": { transform: "translateX(220%)" } },
        "fade-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "slide-in": {
          from: { opacity: "0", transform: "translateX(12px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        "draw-in": { from: { strokeDashoffset: "1" }, to: { strokeDashoffset: "0" } },
      },
      animation: {
        "pulse-soft": "pulse-soft 2s ease-in-out infinite",
        "scan-sweep": "scan-sweep 1.6s ease-in-out infinite",
        "fade-up": "fade-up 260ms cubic-bezier(0.22, 1, 0.36, 1) both",
        "slide-in": "slide-in 200ms cubic-bezier(0.22, 1, 0.36, 1) both",
      },
    },
  },
  plugins: [],
};

export default config;
