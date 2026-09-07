import type { Config } from "tailwindcss";

/**
 * Design system: a dark geospatial-operations console, not a SaaS dashboard.
 * Fixed dark theme (no light mode) — this is a deliberate identity choice for a
 * command-center-style tool, the same way Bloomberg terminals or ATC consoles don't
 * ship a "light mode". Every color below is referenced by name in components, never
 * inlined as a raw hex, so the palette stays a single edit point.
 */
const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        void: "#050708", // page background — near-black, not pure black (keeps depth)
        hull: "#0a0e12", // panel background
        plate: "#0e141a", // raised panel / table header background
        seam: "#1c252d", // hairline borders
        seam2: "#2a3641", // brighter border for focus/hover
        signal: {
          cyan: "#3ee6d8",
          amber: "#f5a623",
          red: "#ff4d5e",
          green: "#3ecf8e",
        },
        ink: {
          primary: "#e8f0f0",
          secondary: "#8fa3a8",
          dim: "#576269",
          faint: "#333e44",
        },
      },
      fontFamily: {
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "Cascadia Code",
          "SFMono-Regular",
          "Consolas",
          "monospace",
        ],
        display: ["Space Grotesk", "Segoe UI", "-apple-system", "sans-serif"],
      },
      boxShadow: {
        "glow-cyan": "0 0 0 1px rgba(62,230,216,0.25), 0 0 16px rgba(62,230,216,0.15)",
        "glow-amber": "0 0 0 1px rgba(245,166,35,0.25), 0 0 16px rgba(245,166,35,0.15)",
        "glow-red": "0 0 0 1px rgba(255,77,94,0.25), 0 0 16px rgba(255,77,94,0.15)",
        "glow-green": "0 0 0 1px rgba(62,207,142,0.25), 0 0 16px rgba(62,207,142,0.15)",
      },
      keyframes: {
        scan: {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100%)" },
        },
        blink: {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.15" },
        },
        "pulse-ring": {
          "0%": { transform: "scale(0.9)", opacity: "0.8" },
          "100%": { transform: "scale(2.2)", opacity: "0" },
        },
      },
      animation: {
        scan: "scan 4s linear infinite",
        blink: "blink 1.6s step-start infinite",
        "pulse-ring": "pulse-ring 2s cubic-bezier(0.2,0.6,0.4,1) infinite",
      },
      backgroundImage: {
        grid: "linear-gradient(rgba(62,230,216,0.05) 1px, transparent 1px), linear-gradient(90deg, rgba(62,230,216,0.05) 1px, transparent 1px)",
      },
      backgroundSize: {
        grid: "32px 32px",
      },
    },
  },
  plugins: [],
};

export default config;
