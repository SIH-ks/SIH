/**
 * Where the FastAPI backend lives, and how to address its static files.
 *
 * Separated from `lib/api.ts` because the route handlers under `app/api/` need
 * the base URL without pulling in the fetch helpers (and their `next/headers`
 * dependency) that only make sense inside a request for a page.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? "http://localhost:8000/api/v1";

/**
 * The backend's origin with no path. `page_image_urls` come back as
 * server-relative paths (`/static/uploads/...`), so building an `<img src>`
 * needs this, not `API_BASE` (which carries the `/api/v1` prefix). Derived from
 * `API_BASE` rather than a second environment variable so the two can never
 * point at different hosts by accident.
 */
export const API_ORIGIN = API_BASE.replace(/\/api\/v\d+\/?$/, "");

/** Everything the browser sends goes through this same-origin proxy instead of
 * straight to the API, so the session token can stay in an httpOnly cookie the
 * client bundle cannot read. See `app/api/proxy/[...path]/route.ts`. */
export const PROXY_BASE = "/api/proxy";
