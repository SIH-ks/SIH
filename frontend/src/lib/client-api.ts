"use client";

/**
 * Browser-side API calls, routed through the same-origin proxy.
 *
 * Client components never see the bearer token (it lives in an httpOnly cookie),
 * so every request here goes to `/api/proxy/...` and the proxy attaches it. The
 * one behaviour worth knowing about: a 401 means the session expired, and this
 * module reloads the page rather than letting each caller invent its own
 * handling — the middleware then redirects to the login screen with the current
 * URL preserved, so the officer resumes exactly where they were.
 */

import { PROXY_BASE } from "@/lib/api-config";
import type {
  BatchUploadResponse,
  CorrectionResponse,
  ParcelDetail,
  UploadResponse,
} from "@/types/parcel";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public body?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${PROXY_BASE}${path}`, { ...init, cache: "no-store" });

  if (response.status === 401) {
    // Reloading hands control to the middleware, which redirects to /login with
    // `?next=` set. Doing it here rather than in every caller means an expired
    // session can never present as a generic "something went wrong".
    if (typeof window !== "undefined") window.location.reload();
    throw new ApiError("Your session has expired. Please sign in again.", 401);
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : typeof detail?.message === "string"
          ? detail.message
          : `Request failed (${response.status}).`;
    throw new ApiError(message, response.status, body);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

// -- review workflow ---------------------------------------------------------

export function submitCorrection(
  parcelId: string,
  body: { field_path: string; new_value: unknown; note?: string; apply?: boolean },
): Promise<CorrectionResponse> {
  return request<CorrectionResponse>(`/parcels/${parcelId}/review`, json("POST", body));
}

export function changeStatus(
  parcelId: string,
  status: string,
  note?: string,
): Promise<ParcelDetail> {
  return request<ParcelDetail>(`/parcels/${parcelId}/status`, json("POST", { status, note }));
}

export function assignParcel(
  parcelId: string,
  assignee: string | null,
  note?: string,
): Promise<ParcelDetail> {
  return request<ParcelDetail>(`/parcels/${parcelId}/assign`, json("POST", { assignee, note }));
}

export function revalidateParcel(parcelId: string): Promise<ParcelDetail> {
  return request<ParcelDetail>(`/parcels/${parcelId}/revalidate`, { method: "POST" });
}

export function bulkStatus(
  parcelIds: string[],
  status: string,
  note?: string,
): Promise<{ updated: string[]; skipped: { parcel_id: string; reason: string }[]; total_requested: number }> {
  return request(`/parcels/bulk/status`, json("POST", { parcel_ids: parcelIds, status, note }));
}

// -- ingestion ---------------------------------------------------------------

export function uploadDocument(file: File, declaredFormat: string): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("declared_format", declaredFormat);
  return request<UploadResponse>("/documents/upload", { method: "POST", body: form });
}

export function batchUpload(files: File[], declaredFormat: string): Promise<BatchUploadResponse> {
  const form = new FormData();
  for (const file of files) form.append("files", file);
  form.append("declared_format", declaredFormat);
  return request<BatchUploadResponse>("/documents/batch-upload", { method: "POST", body: form });
}

// -- exports -----------------------------------------------------------------

/** Build a proxy URL for a download. Returned as a string rather than fetched:
 * letting the browser navigate to it keeps the API's own `Content-Disposition`
 * filename, which a blob download would replace with a generated one. */
export function exportUrl(path: string, params: Record<string, unknown> = {}): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "" && value !== false) {
      search.set(key, String(value));
    }
  }
  const encoded = search.toString();
  return `${PROXY_BASE}${path}${encoded ? `?${encoded}` : ""}`;
}

// -- session -----------------------------------------------------------------

export async function signOut(): Promise<void> {
  await fetch("/api/session", { method: "DELETE" });
  window.location.href = "/login";
}
