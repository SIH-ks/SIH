/**
 * Server-side data access for React Server Components.
 *
 * Reads the session cookie directly (`next/headers`) and calls the FastAPI
 * backend, so a page renders with its data already in the HTML — no loading
 * spinner, no client-side waterfall, and the token never crosses into the
 * browser bundle. Client components use `lib/client-api.ts` instead, which goes
 * through the same-origin proxy.
 *
 * **Failures are values, not exceptions.** Every reader returns a
 * `Result<T>` — `{ data }` or `{ error }` — rather than throwing. A dashboard
 * assembled from six independent panels should degrade one panel when one query
 * fails, not blank the page; making that the default shape is what stops each
 * call site from having to remember a try/catch.
 */

import "server-only";

import { cookies } from "next/headers";

import { API_BASE } from "@/lib/api-config";
import { SESSION_COOKIE, type SessionProfile } from "@/lib/session";
import type {
  AnalyticsSummary,
  AuditEntry,
  DistrictRow,
  DocumentSummary,
  Facets,
  Page,
  ParcelDetail,
  ParcelGeoJson,
  ParcelListFilters,
  ParcelSummary,
  QueueHealth,
  ReviewEvent,
  RuleCatalogueEntry,
  RuleFrequency,
  SystemStatus,
  ThroughputRow,
  TimeseriesPoint,
} from "@/types/parcel";
import type {
  OwnershipEvent,
  SuccessionCaseDetail,
  SuccessionCaseFilters,
  SuccessionCaseSummary,
  SuccessionSummary,
} from "@/types/succession";

export type ApiFailure = {
  status: number;
  message: string;
  /** True when the backend could not be reached at all, as opposed to answering
   * with an error. The console words these very differently: one is "start the
   * server", the other is "this request was refused". */
  unreachable: boolean;
};

export type Result<T> = { data: T; error?: undefined } | { data?: undefined; error: ApiFailure };

export const NOT_FOUND = 404;

function query(filters: Record<string, unknown> = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "") continue;
    if (typeof value === "boolean" && !value) continue; // omit false flags entirely
    params.set(key, String(value));
  }
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

async function get<T>(path: string): Promise<Result<T>> {
  let token: string | undefined;
  try {
    token = (await cookies()).get(SESSION_COOKIE)?.value;
  } catch {
    token = undefined;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      cache: "no-store",
    });
  } catch {
    return {
      error: {
        status: 0,
        unreachable: true,
        message: "Could not reach the Adhikar API. Is the backend running on :8000?",
      },
    };
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    return {
      error: {
        status: response.status,
        unreachable: false,
        message:
          typeof detail === "string"
            ? detail
            : typeof detail?.message === "string"
              ? detail.message
              : `Request to ${path} failed (${response.status}).`,
      },
    };
  }

  return { data: (await response.json()) as T };
}

// -- identity ----------------------------------------------------------------

export async function getSessionProfile(): Promise<SessionProfile | null> {
  const result = await get<SessionProfile>("/auth/me");
  return result.data ?? null;
}

// -- parcels -----------------------------------------------------------------

export function listParcels(filters: ParcelListFilters = {}): Promise<Result<Page<ParcelSummary>>> {
  return get<Page<ParcelSummary>>(`/parcels${query(filters as Record<string, unknown>)}`);
}

export function getReviewQueue(
  scope: "mine" | "unassigned" | "district" | "all" = "all",
  options: { limit?: number; offset?: number } = {},
): Promise<Result<Page<ParcelSummary>>> {
  return get<Page<ParcelSummary>>(`/parcels/queue${query({ scope, ...options })}`);
}

export function getParcel(id: string): Promise<Result<ParcelDetail>> {
  return get<ParcelDetail>(`/parcels/${id}`);
}

export function getParcelEvents(id: string): Promise<Result<ReviewEvent[]>> {
  return get<ReviewEvent[]>(`/parcels/${id}/events`);
}

export function getFacets(): Promise<Result<Facets>> {
  return get<Facets>("/parcels/facets");
}

export function getParcelGeoJson(
  filters: { state?: string; district?: string; review_status?: string; limit?: number } = {},
): Promise<Result<ParcelGeoJson>> {
  return get<ParcelGeoJson>(`/parcels/geojson${query(filters)}`);
}

// -- documents ---------------------------------------------------------------

export function listDocuments(
  options: { limit?: number; offset?: number } = {},
): Promise<Result<Page<DocumentSummary>>> {
  return get<Page<DocumentSummary>>(`/documents${query(options)}`);
}

// -- audit -------------------------------------------------------------------

export function listAuditEvents(
  filters: { reviewer?: string; action?: string; district?: string; limit?: number; offset?: number } = {},
): Promise<Result<Page<AuditEntry>>> {
  return get<Page<AuditEntry>>(`/audit/events${query(filters)}`);
}

// -- analytics ---------------------------------------------------------------

export function getSummary(
  scope: { district?: string; state?: string } = {},
): Promise<Result<AnalyticsSummary>> {
  return get<AnalyticsSummary>(`/analytics/summary${query(scope)}`);
}

export function getDistrictBreakdown(state?: string): Promise<Result<DistrictRow[]>> {
  return get<DistrictRow[]>(`/analytics/districts${query({ state })}`);
}

export function getTimeseries(days = 30, district?: string): Promise<Result<TimeseriesPoint[]>> {
  return get<TimeseriesPoint[]>(`/analytics/timeseries${query({ days, district })}`);
}

export function getRuleFrequency(limit = 12): Promise<Result<RuleFrequency[]>> {
  return get<RuleFrequency[]>(`/analytics/rules${query({ limit })}`);
}

export function getThroughput(days = 30): Promise<Result<ThroughputRow[]>> {
  return get<ThroughputRow[]>(`/analytics/throughput${query({ days })}`);
}

export function getQueueHealth(district?: string): Promise<Result<QueueHealth>> {
  return get<QueueHealth>(`/analytics/queue-health${query({ district })}`);
}

// -- system ------------------------------------------------------------------

export function getRuleCatalogue(): Promise<Result<RuleCatalogueEntry[]>> {
  return get<RuleCatalogueEntry[]>("/system/rules");
}

export function getSystemStatus(): Promise<Result<SystemStatus>> {
  return get<SystemStatus>("/system/status");
}

export function getActivePolicy(): Promise<Result<{ name: string; policy: Record<string, unknown> }>> {
  return get<{ name: string; policy: Record<string, unknown> }>("/system/policy");
}

export function listUsers(): Promise<Result<SessionProfile[]>> {
  return get<SessionProfile[]>("/auth/users");
}

// -- ownership succession ----------------------------------------------------

export function listSuccessionCases(
  filters: SuccessionCaseFilters = {},
): Promise<Result<Page<SuccessionCaseSummary>>> {
  return get<Page<SuccessionCaseSummary>>(
    `/succession/cases${query(filters as Record<string, unknown>)}`,
  );
}

export function getSuccessionCase(id: string): Promise<Result<SuccessionCaseDetail>> {
  return get<SuccessionCaseDetail>(`/succession/cases/${id}`);
}

/** Succession cases raised against one parcel. Drives the panel on the parcel
 * detail page, which is absent — not empty — when a record has no case. */
export function getParcelSuccessionCases(
  parcelId: string,
): Promise<Result<SuccessionCaseSummary[]>> {
  return get<SuccessionCaseSummary[]>(`/succession/parcels/${parcelId}/cases`);
}

/** Every ownership event recorded against one parcel, across every case — the
 * question a revenue office actually asks, which a per-case timeline cannot
 * answer. */
export function getOwnershipHistory(parcelKey: string): Promise<Result<OwnershipEvent[]>> {
  return get<OwnershipEvent[]>(`/succession/history${query({ parcel_key: parcelKey })}`);
}

export function getSuccessionSummary(district?: string): Promise<Result<SuccessionSummary>> {
  return get<SuccessionSummary>(`/succession/summary${query({ district })}`);
}
