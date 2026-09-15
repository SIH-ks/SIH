/**
 * Sign-in and sign-out, handled server-side so the bearer token never reaches
 * client JavaScript.
 *
 * The browser posts credentials here; this handler exchanges them with the
 * FastAPI backend and stores the returned JWT in an **httpOnly** cookie. Nothing
 * in the client bundle can read it — which means an XSS bug in a chart component
 * cannot exfiltrate a Tehsildar's session token. A second, readable cookie
 * carries only display identity (name, role, district) so the UI can grey out
 * actions the role cannot perform; see `lib/session.ts` on why that split is
 * presentation and not authorization.
 */

import { NextResponse } from "next/server";

import { API_BASE } from "@/lib/api-config";
import { PROFILE_COOKIE, SESSION_COOKIE } from "@/lib/session";

export async function POST(request: Request) {
  let credentials: { username?: string; password?: string };
  try {
    credentials = await request.json();
  } catch {
    return NextResponse.json({ message: "Malformed request body." }, { status: 400 });
  }

  if (!credentials.username || !credentials.password) {
    return NextResponse.json({ message: "Username and password are both required." }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: credentials.username, password: credentials.password }),
      cache: "no-store",
    });
  } catch {
    // Distinguished from a rejected credential on purpose: "the server is not
    // running" and "that password is wrong" need completely different actions
    // from whoever is standing at the login screen.
    return NextResponse.json(
      {
        message:
          "Could not reach the Adhikar API. Start the backend (uvicorn app.main:app --reload) and try again.",
        unreachable: true,
      },
      { status: 503 },
    );
  }

  if (!upstream.ok) {
    const body = await upstream.json().catch(() => null);
    return NextResponse.json(
      { message: body?.detail ?? "Invalid username or password." },
      { status: upstream.status },
    );
  }

  const session = await upstream.json();
  const response = NextResponse.json({ user: session.user });
  const maxAge = session.expires_in ?? 60 * 60 * 12;
  const secure = isHttps(request);

  response.cookies.set(SESSION_COOKIE, session.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge,
  });
  response.cookies.set(PROFILE_COOKIE, encodeURIComponent(JSON.stringify(session.user)), {
    httpOnly: false,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge,
  });
  return response;
}

/**
 * Whether the session cookie should carry the `Secure` attribute.
 *
 * Keyed to the *actual request scheme*, not to `NODE_ENV`. Those come apart in
 * both directions and each mistake is real: a production build run locally over
 * http would set `Secure` and the browser would silently discard the cookie
 * (every sign-in appearing to succeed and then landing back on the login page),
 * while a deployment behind a TLS-terminating proxy sees plain http on the
 * socket and would omit `Secure` exactly where it matters most. The
 * `x-forwarded-proto` header is what the proxy sets for the second case.
 */
function isHttps(request: Request): boolean {
  const forwarded = request.headers.get("x-forwarded-proto");
  if (forwarded) return forwarded.split(",")[0]?.trim() === "https";
  return new URL(request.url).protocol === "https:";
}

export async function DELETE() {
  const response = NextResponse.json({ ok: true });
  response.cookies.delete(SESSION_COOKIE);
  response.cookies.delete(PROFILE_COOKIE);
  return response;
}
