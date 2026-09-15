import { redirect } from "next/navigation";

import { AppShell } from "@/components/shell/AppShell";
import { getSessionProfile, getSystemStatus } from "@/lib/api";

/**
 * The authenticated shell wrapping every console page.
 *
 * Identity and system status are fetched once here rather than per page: both
 * are needed by the chrome on every route, and a per-page fetch would mean the
 * header re-resolving the same two things nine times as an officer moves around.
 *
 * The `redirect` is a second line after `middleware.ts` — the middleware only
 * checks that a cookie *exists*, while this asks the API who the caller actually
 * is. A cookie carrying an expired or revoked token gets past the first check and
 * is caught here, which is the difference between a console full of failed panels
 * and a clean return to the sign-in screen.
 */
export default async function ConsoleLayout({ children }: { children: React.ReactNode }) {
  const [profile, status] = await Promise.all([getSessionProfile(), getSystemStatus()]);

  if (!profile) redirect("/login");

  return (
    <AppShell profile={profile} status={status.data ?? null}>
      <div id="main-content">{children}</div>
    </AppShell>
  );
}
