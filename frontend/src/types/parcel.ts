/**
 * Mirrors backend/app/schemas/record.py. Kept as a hand-written mirror rather than
 * a codegen artifact for this reference scaffold -- in a production build, generate
 * this from the FastAPI OpenAPI schema (e.g. via `openapi-typescript`) so the two
 * never drift silently.
 */

export type RecommendedAction =
  | "auto_approve"
  | "review_queue"
  | "field_verification"
  | "reject_re_scan";

export type MismatchBand =
  | "exact"
  | "within_survey_tolerance"
  | "minor"
  | "material"
  | "severe"
  | "undetermined";

export type Severity = "info" | "warning" | "error" | "critical";

export interface DocumentSummary {
  id: string;
  file_name: string;
  media_type: string;
  page_count: number;
  declared_record_format: string;
  ingested_at: string;
}

export interface ParcelSummary {
  id: string;
  document_id: string;
  parcel_key: string;
  state: string | null;
  district: string | null;
  village: string | null;
  khata_number: string | null;
  survey_number: string | null;
  total_area_sq_metre: number | null;
  mismatch_score: number | null;
  confidence_score: number | null;
  recommended_action: RecommendedAction | null;
  requires_human_review: boolean;
  validation_issue_count: number;
  validation_highest_severity: Severity | null;
  updated_at: string;
}

export interface ValidationIssue {
  rule_code: string;
  severity: Severity;
  message: string;
  json_path: string;
  observed?: string | null;
  expected?: string | null;
  remediation?: string | null;
  confidence: number;
}

export interface ParcelDetail extends ParcelSummary {
  artifact_json: Record<string, unknown>;
}

export interface UploadResponse {
  document: DocumentSummary;
  parcels: ParcelSummary[];
  warnings: string[];
}

export interface ParcelListFilters {
  state?: string;
  district?: string;
  village?: string;
  requires_review?: boolean;
  min_mismatch?: number;
  limit?: number;
  offset?: number;
}
