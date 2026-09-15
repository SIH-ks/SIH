import type { Metadata } from "next";

import { LoginForm } from "./LoginForm";

export const metadata: Metadata = { title: "Sign in" };

/**
 * The sign-in screen.
 *
 * The left panel is not decoration: it states what the system does and what it
 * deliberately does *not* store, because the first question anyone asks about a
 * land-records system is what it knows about them. The right panel is the form.
 */
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string }>;
}) {
  const { next } = await searchParams;

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <aside className="relative hidden flex-col justify-between overflow-hidden bg-brand-navy-deep p-12 lg:flex">
        {/* A faint cadastral grid: the subject matter, at a weight that stays
            behind the text rather than competing with it. */}
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.13]"
          aria-hidden
          style={{
            backgroundImage:
              "linear-gradient(rgba(255,255,255,.5) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,.5) 1px, transparent 1px)",
            backgroundSize: "56px 56px",
          }}
        />
        <div
          className="pointer-events-none absolute -right-24 -top-24 h-96 w-96 rounded-full bg-brand-saffron/18 blur-3xl"
          aria-hidden
        />
        <div
          className="pointer-events-none absolute -bottom-32 -left-20 h-96 w-96 rounded-full bg-brand-green/14 blur-3xl"
          aria-hidden
        />

        <div className="relative">
          <div className="flex items-center gap-3">
            <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-brand-saffron to-brand-green text-xl font-bold text-white">
              अ
            </span>
            <div className="leading-tight">
              <p className="text-xl font-bold tracking-tight text-white">Adhikar</p>
              <p className="text-xs font-medium text-white/55">Land Record Intelligence Platform</p>
            </div>
          </div>
        </div>

        <div className="relative max-w-lg">
          <p className="text-[11px] font-bold uppercase tracking-[0.2em] text-brand-saffron">
            SIH26018 · Ministry of Rural Development
          </p>
          <h1 className="mt-4 text-[34px] font-bold leading-[1.15] tracking-tight text-white">
            Every Jamabandi page, checked twice —
            <span className="text-brand-saffron"> once by the rules, once by an officer.</span>
          </h1>
          <p className="mt-5 text-[15px] leading-relaxed text-white/70">
            Scanned Records of Rights are read by an OCR + Vision-LLM pipeline, checked against 22
            consistency rules and the cadastral map, then queued for a revenue officer worst-first.
            Every correction is applied to the record <em>and</em> written to an audit trail that
            cannot be edited in place.
          </p>

          <dl className="mt-9 grid grid-cols-3 gap-6 border-t border-white/12 pt-6">
            <Stat value="22" label="Consistency rules" />
            <Stat value="4" label="Separated duties" />
            <Stat value="100%" label="Actions audited" />
          </dl>
        </div>

        <p className="relative max-w-lg text-xs leading-relaxed text-white/45">
          <span className="font-semibold text-white/70">Data governance.</span> Aadhaar numbers,
          mobile numbers and bank details are never extracted or stored — enforced by the extraction
          schema itself, not by a filter that could be turned off.
        </p>
      </aside>

      <main className="flex items-center justify-center px-6 py-12">
        <LoginForm next={next} />
      </main>
    </div>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <dd className="text-2xl font-bold tracking-tight text-white">{value}</dd>
      <dt className="mt-0.5 text-[11px] font-medium leading-tight text-white/50">{label}</dt>
    </div>
  );
}
