import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Adhikar — Land Record Console",
  description: "Intelligent Land Record Digitization and Validation System (SIH26018)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="vignette grid-backdrop relative min-h-screen bg-void font-display text-ink-primary antialiased">
        <div className="relative z-10 mx-auto max-w-[1400px] px-6 py-6">{children}</div>
      </body>
    </html>
  );
}
