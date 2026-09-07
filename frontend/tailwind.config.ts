import type { Config } from "tailwindcss";

/**
 * Institutional design system: a deep-navy command bar over a crisp white
 * workspace, with accessible green/amber/red status colors. This is a
 * light-theme rebuild replacing the earlier dark HUD console -- see git history
 * for that version if it's ever wanted back.
 */
const config: Config = {
  darkMode: "media",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: {
          950: "#050b18",
          900: "#0a1530",
          800: "#0f2557",
          700: "#15316b",
          600: "#1c3f85",
        },
        status: {
          green: { bg: "#ecfdf5", border: "#a7f3d0", text: "#047857", dot: "#10b981" },
          amber: { bg: "#fffbeb", border: "#fde68a", text: "#b45309", dot: "#f59e0b" },
          red: { bg: "#fef2f2", border: "#fecaca", text: "#b91c1c", dot: "#ef4444" },
        },
      },
      fontFamily: {
        sans: ["Inter", "-apple-system", "Segoe UI", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px 0 rgba(15, 37, 87, 0.06), 0 1px 3px 0 rgba(15, 37, 87, 0.08)",
        "card-hover": "0 4px 12px 0 rgba(15, 37, 87, 0.10)",
      },
      keyframes: {
        "pulse-soft": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.5" },
        },
        "scan-sweep": {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "pulse-soft": "pulse-soft 1.8s ease-in-out infinite",
        "scan-sweep": "scan-sweep 1.8s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
