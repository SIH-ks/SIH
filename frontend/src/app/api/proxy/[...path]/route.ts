/**
 * Same-origin proxy to the FastAPI backend for browser-initiated requests.
 *
 * Client components cannot attach the bearer token themselves — it lives in an
 * httpOnly cookie precisely so that script cannot read it. They call
 * `/api/proxy/<path>` instead, and this handler re-issues the request upstream
 * with the `Authorization` header attached.
 *
 * Three properties worth stating, because each one is a decision:
 *
 * * **Streaming passthrough.** The upstream body is forwarded as-is rather than
 *   parsed, so a 40 MB CSV export downloads through here without the Node
 *   process holding it in memory, and the `Content-Disposition` filename the API
 *   chose survives to the browser's save dialog.
 * * **A 401 upstream becomes a 401 here with the cookies cleared.** An expired
 *   token otherwise leaves the console in a state where every panel fails and
 *   the user has no way to notice they need to sign in again.
 * * **It proxies to one fixed origin only.** The `[...path]` segment is appended
 *   to `API_BASE`; there is no caller-supplied host, so this cannot be turned
 *   into an SSRF pivot by crafting a path.
 */

import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { API_BASE } from "@/lib/api-config";
import { PROFILE_COOKIE, SESSION_COOKIE } from "@/lib/session";

export const dynamic = "force-dynamic";

const HOP_BY_HOP = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

async function forward(request: Request, segments: string[]): Promise<Response> {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  const search = new URL(request.url).search;

  // Each segment is re-encoded rather than trusted verbatim: a path element is
  // data (a UUID, a filename) and must not be able to introduce `?`, `#` or a
  // second path root into the upstream URL.
  const path = segments.map(encodeURIComponent).join("/");
  const target = `${API_BASE}/${path}${search}`;

  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && key.toLowerCase() !== "cookie") headers.set(key, value);
  });
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const hasBody = request.method !== "GET" && request.method !== "HEAD";

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  } catch {
    return NextResponse.json(
      { detail: "The Adhikar API is unreachable. Is the backend running on :8000?", unreachable: true },
      { status: 503 },
    );
  }

  if (upstream.status === 401) {
    const expired = NextResponse.json(
      { detail: "Your session has expired. Please sign in again.", expired: true },
      { status: 401 },
    );
    expired.cookies.delete(SESSION_COOKIE);
    expired.cookies.delete(PROFILE_COOKIE);
    return expired;
  }

  const responseHeaders = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP.has(key.toLowerCase()) && key.toLowerCase() !== "content-encoding") {
      responseHeaders.set(key, value);
    }
  });

  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

type Context = { params: Promise<{ path: string[] }> };

export async function GET(request: Request, context: Context) {
  return forward(request, (await context.params).path);
}
export async function POST(request: Request, context: Context) {
  return forward(request, (await context.params).path);
}
export async function PATCH(request: Request, context: Context) {
  return forward(request, (await context.params).path);
}
export async function PUT(request: Request, context: Context) {
  return forward(request, (await context.params).path);
}
export async function DELETE(request: Request, context: Context) {
  return forward(request, (await context.params).path);
}
