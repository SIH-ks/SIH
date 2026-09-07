/**
 * Thin fetch wrapper over the FastAPI backend. No client library dependency --
 * the surface is small enough that a generated client would be more ceremony than
 * value at this stage of the project.
 *
 * **Demo fallback.** When the backend is unreachable and `NEXT_PUBLIC_ALLOW_DEMO_DATA`
 * is not explicitly "false", read paths fall back to bundled fixtures so the console
 * is demoable without the full Postgres/PostGIS stack. `usingDemoData()` reports when
 * that happened, and the UI surfaces it — fixtures are never silently presented as
 * real extraction output. Write paths never fall back; a correction that could not be
 * persisted must fail loudly.
 */

import { demoDetail, demoSummaries } from "@/lib/demoData";
import type { ParcelDetail, ParcelListFilters, ParcelSummary, UploadResponse } from "@/types/parcel";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
const DEMO_ALLOWED = process.env.NEXT_PUBLIC_ALLOW_DEMO_DATA !== "false";

class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public body: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** True when the last read served fixtures because the backend was unreachable. */
let servedDemoData = false;
export function usingDemoData(): boolean {
  return servedDemoData;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new ApiError(`Request to ${path} failed with ${response.status}`, response.status, body);
  }
  return (await response.json()) as T;
}

/**
 * Whether a failure means "the Adhikar API isn't there" (fixtures are appropriate)
 * rather than "the API answered and said no" (it isn't).
 *
 * Connection refusal is the obvious case. A 404 counts too: our `/parcels` route
 * always answers 200 with a list when the backend is up, so a 404 means something
 * other than this API is answering on that port -- which is exactly what happens
 * when another service already occupies :8000. 5xx likewise means the backend is
 * present but not serving. Everything else (401, 422, ...) is a real answer and is
 * allowed to surface.
 */
function backendUnavailable(err: unknown): boolean {
  if (!(err instanceof ApiError)) return true;
  return err.status === 404 || err.status >= 500;
}

export async function listParcels(filters: ParcelListFilters = {}): Promise<ParcelSummary[]> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  const query = params.toString();
  try {
    const result = await request<ParcelSummary[]>(`/parcels${query ? `?${query}` : ""}`);
    servedDemoData = false;
    return result;
  } catch (err) {
    if (DEMO_ALLOWED && backendUnavailable(err)) {
      servedDemoData = true;
      return demoSummaries();
    }
    throw err;
  }
}

export async function getParcel(id: string): Promise<ParcelDetail> {
  try {
    const result = await request<ParcelDetail>(`/parcels/${id}`);
    servedDemoData = false;
    return result;
  } catch (err) {
    if (DEMO_ALLOWED && backendUnavailable(err)) {
      const fixture = demoDetail(id);
      if (fixture) {
        servedDemoData = true;
        return fixture;
      }
      throw new ApiError(`Parcel ${id} not found in demo data`, 404, null);
    }
    throw err;
  }
}

export function submitCorrection(
  parcelId: string,
  reviewer: string,
  body: { field_path: string; new_value: unknown; note?: string },
) {
  // No demo fallback: a correction that cannot be persisted must fail visibly.
  return request(`/parcels/${parcelId}/review?reviewer=${encodeURIComponent(reviewer)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function uploadDocument(file: File, declaredFormat: string): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("declared_format", declaredFormat);
  return request<UploadResponse>("/documents/upload", { method: "POST", body: formData });
}

export { ApiError };
