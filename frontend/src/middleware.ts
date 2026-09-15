/**
 * Route guard: an unauthenticated visitor never reaches a console page.
 *
 * Checking only for the *presence* of the session cookie is deliberate. Its
 * validity is decided by the API on every request (`app/api/deps.py`), and
 * verifying the JWT signature here as well would put a second, independently
 * maintained copy of that logic on the edge — the classic way two layers drift
 * until one of them is wrong. This is a redirect for the common case, not a
 * security boundary: a forged cookie gets you a console shell whose every panel
 * answers 401.
 */

import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE } from "@/lib/session";

const PUBLIC_PATHS = ["/login"];

export function middleware(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const signedIn = Boolean(request.cookies.get(SESSION_COOKIE)?.value);

  if (PUBLIC_PATHS.some((path) => pathname.startsWith(path))) {
    // Already signed in and staring at the login page: send them where they
    // were trying to go, or to the dashboard.
    if (signedIn) {
      const next = request.nextUrl.searchParams.get("next");
      return NextResponse.redirect(new URL(next && next.startsWith("/") ? next : "/", request.url));
    }
    return NextResponse.next();
  }

  if (!signedIn) {
    const login = new URL("/login", request.url);
    // Round-trip the intended destination so a deep link to a specific parcel
    // survives the sign-in — an officer following a link from an email should
    // land on that record, not on a generic dashboard.
    if (pathname !== "/") login.searchParams.set("next", `${pathname}${search}`);
    return NextResponse.redirect(login);
  }

  return NextResponse.next();
}

export const config = {
  // Everything except Next's own assets, the API route handlers (which do their
  // own auth), and static files.
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)"],
};
