"use client";

import { AlertCircle, ArrowRight, Eye, EyeOff, Loader2, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { cn } from "@/lib/format";

/**
 * Credentials go to `/api/session`, a server route that exchanges them with the
 * API and stores the returned JWT in an httpOnly cookie — so the token never
 * enters client JavaScript. See `app/api/session/route.ts`.
 *
 * The demo accounts are listed openly because that is what they are: four
 * evaluation logins, one per role, created on first boot and switchable off with
 * `ADHIKAR_API_SEED_DEMO_USERS=false`. Showing them beats a README nobody reads
 * two minutes before a demo, and the panel says plainly that they must not
 * survive into a real deployment.
 */

const DEMO_ACCOUNTS = [
  {
    username: "collector",
    name: "Anitha Raghavan",
    role: "District Administrator",
    can: "Everything, plus user management",
  },
  {
    username: "tehsildar",
    name: "Vikram Deshpande",
    role: "Revenue Inspector",
    can: "Approve, reject, escalate, assign",
  },
  {
    username: "operator",
    name: "Shalini Kamble",
    role: "Data Entry Operator",
    can: "Upload and correct — cannot approve",
  },
  {
    username: "auditor",
    name: "R. Sundaram",
    role: "Auditor",
    can: "Read everything, change nothing",
  },
];

const DEMO_PASSWORD = "adhikar@2026";

export function LoginForm({ next }: { next?: string }) {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<{ message: string; unreachable?: boolean } | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError(null);

    try {
      const response = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const body = await response.json().catch(() => ({}));

      if (!response.ok) {
        setError({ message: body?.message ?? "Sign-in failed.", unreachable: body?.unreachable });
        setPending(false);
        return;
      }

      // `refresh()` before `push()` so the server components on the destination
      // re-render with the new session rather than replaying a cached
      // unauthenticated tree.
      router.refresh();
      router.push(next && next.startsWith("/") ? next : "/");
    } catch {
      setError({
        message: "Could not reach the sign-in service. Check that the Next.js server is running.",
        unreachable: true,
      });
      setPending(false);
    }
  };

  const useAccount = (account: (typeof DEMO_ACCOUNTS)[number]) => {
    setUsername(account.username);
    setPassword(DEMO_PASSWORD);
    setError(null);
  };

  return (
    <div className="w-full max-w-md">
      <div className="lg:hidden">
        <div className="mb-8 flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-brand-saffron to-brand-green text-lg font-bold text-white">
            अ
          </span>
          <div className="leading-tight">
            <p className="text-lg font-bold tracking-tight text-ink-primary">Adhikar</p>
            <p className="text-[11px] text-ink-muted">Land Record Intelligence</p>
          </div>
        </div>
      </div>

      <h2 className="text-2xl font-bold tracking-tight text-ink-primary">Sign in to the console</h2>
      <p className="mt-1.5 text-sm text-ink-secondary">
        Access is role-based. What you can do here is decided by your designation in the revenue
        department, not by this screen.
      </p>

      <form onSubmit={submit} className="mt-7 flex flex-col gap-4">
        <div>
          <label htmlFor="username" className="mb-1.5 block text-xs font-semibold text-ink-secondary">
            Username
          </label>
          <input
            id="username"
            name="username"
            autoComplete="username"
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="tehsildar"
            className="h-11 w-full rounded-lg border border-line-strong bg-surface-card px-3.5 text-sm text-ink-primary outline-none transition-colors placeholder:text-ink-muted focus:border-series-1"
          />
        </div>

        <div>
          <label htmlFor="password" className="mb-1.5 block text-xs font-semibold text-ink-secondary">
            Password
          </label>
          <div className="relative">
            <input
              id="password"
              name="password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="h-11 w-full rounded-lg border border-line-strong bg-surface-card px-3.5 pr-11 text-sm text-ink-primary outline-none transition-colors placeholder:text-ink-muted focus:border-series-1"
            />
            <button
              type="button"
              onClick={() => setShowPassword((current) => !current)}
              aria-label={showPassword ? "Hide password" : "Show password"}
              className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md p-2 text-ink-muted transition-colors hover:bg-surface-sunken hover:text-ink-primary"
            >
              {showPassword ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
            </button>
          </div>
        </div>

        {error && (
          <div
            role="alert"
            className={cn(
              "flex items-start gap-2.5 rounded-lg px-3.5 py-3 text-sm ring-1 ring-inset",
              error.unreachable
                ? "bg-status-warning-wash text-status-warning-ink ring-status-warning/35"
                : "bg-status-critical-wash text-status-critical-ink ring-status-critical/35",
            )}
          >
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <div>
              <p className="font-medium">{error.message}</p>
              {error.unreachable && (
                <p className="mt-1 font-mono text-xs opacity-80">
                  cd backend &amp;&amp; uvicorn app.main:app --reload
                </p>
              )}
            </div>
          </div>
        )}

        <button
          type="submit"
          disabled={pending}
          className="mt-1 flex h-11 items-center justify-center gap-2 rounded-lg bg-brand-navy text-sm font-semibold text-white transition-colors hover:bg-brand-navy/90 disabled:opacity-60 dark:bg-series-1 dark:hover:bg-series-1/90"
        >
          {pending ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Signing in…
            </>
          ) : (
            <>
              Sign in <ArrowRight className="h-4 w-4" aria-hidden />
            </>
          )}
        </button>
      </form>

      <section className="mt-8 rounded-xl border border-line bg-surface-card p-4">
        <header className="flex items-start gap-2">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-brand-green" aria-hidden />
          <div>
            <h3 className="text-[13px] font-semibold text-ink-primary">Evaluation accounts</h3>
            <p className="mt-0.5 text-xs text-ink-muted">
              One per role, so the permission model can be seen rather than described. Created on
              first boot; disable with{" "}
              <code className="font-mono text-[11px]">ADHIKAR_API_SEED_DEMO_USERS=false</code> before
              any real deployment.
            </p>
          </div>
        </header>

        <ul className="mt-3 flex flex-col gap-1.5">
          {DEMO_ACCOUNTS.map((account) => (
            <li key={account.username}>
              <button
                type="button"
                onClick={() => useAccount(account)}
                className="flex w-full items-center gap-3 rounded-lg border border-line px-3 py-2 text-left transition-colors hover:border-series-1/40 hover:bg-surface-sunken"
              >
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-semibold text-ink-primary">
                    {account.role}
                  </span>
                  <span className="block truncate text-[11px] text-ink-muted">{account.can}</span>
                </span>
                <span className="shrink-0 rounded bg-surface-sunken px-2 py-1 font-mono text-[11px] text-ink-secondary">
                  {account.username}
                </span>
              </button>
            </li>
          ))}
        </ul>

        <p className="mt-3 text-[11px] text-ink-muted">
          Password for all four: <code className="font-mono">{DEMO_PASSWORD}</code>
        </p>
      </section>
    </div>
  );
}
