import type { Metadata, Viewport } from "next";

import { ToastProvider } from "@/components/ui/Toast";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Adhikar — Land Record Console",
    template: "%s · Adhikar",
  },
  description:
    "Intelligent Land Record Digitization and Validation System (SIH26018) — OCR + Vision-LLM extraction, " +
    "22-rule consistency validation, geospatial discrepancy scoring, and an auditable review workflow.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#0f2557" },
    { media: "(prefers-color-scheme: dark)", color: "#080d18" },
  ],
};

/**
 * Applied before first paint, ahead of React hydrating anything.
 *
 * Without this, a reviewer with dark mode selected sees a full-brightness white
 * page for one frame on every navigation — the "theme flash". It has to be an
 * inline, blocking script because the stored preference lives in `localStorage`,
 * which the server cannot read, and any deferred script runs after the browser
 * has already painted.
 */
const THEME_BOOTSTRAP = `
(function () {
  try {
    var choice = localStorage.getItem('adhikar-theme');
    if (choice === 'light' || choice === 'dark') {
      document.documentElement.setAttribute('data-theme', choice);
    }
  } catch (e) {
    /* Private mode or blocked site data: fall through to the OS preference,
       which the CSS media query already handles. */
  }
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body className="min-h-screen bg-surface-page font-sans text-ink-primary antialiased">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-lg focus:bg-surface-card focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:shadow-pop"
        >
          Skip to content
        </a>
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
