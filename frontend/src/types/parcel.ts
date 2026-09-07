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
  /** A `Decimal` on the backend (`Numeric(18,4)`) -- Pydantic serializes that as a
   * JSON *string* ("8005.0000"), not a number, to avoid float precision loss. The
   * demo fixtures provide a plain number instead. Always route this through
   * `formatArea()` (lib/utils.ts), which coerces either shape correctly, rather
   * than calling `.toFixed()` on it directly. */
  total_area_sq_metre: number | string | null;
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

/** Matches `adhikar.schemas.ocr.BoundingBox` -- normalized [0,1] page coordinates. */
export interface RealBoundingBox {
  page_index: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

/** One `artifact_json.provenance` entry -- real bbox attribution when the OCR
 * ensemble's line text matched the extracted value confidently enough (see
 * `adhikar.llm.bbox_attribution`); `bbox: null` is the honest "no confident match
 * found" state, not a missing feature. */
export interface RealFieldProvenance {
  extractor: string;
  confidence: number;
  raw_text: string | null;
  bbox: RealBoundingBox | null;
  reason?: string | null;
}

export interface ParcelDetail extends ParcelSummary {
  artifact_json: Record<string, unknown>;
  /** Matched cadastral polygon as GeoJSON, or `null` when no geometry source is
   * configured / matched -- the honest default for a real upload today. */
  geometry: GeoJSON.Geometry | null;
  /** Server-relative URLs (join with `API_ORIGIN`, not `API_BASE`) of the source
   * document's rendered pages, in order. Empty for demo-fixture records, which
   * render the mock synthetic document instead. */
  page_image_urls: string[];
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
