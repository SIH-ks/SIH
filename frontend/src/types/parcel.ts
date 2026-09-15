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

export type ReviewStatus = "pending" | "in_review" | "approved" | "rejected" | "escalated";

export type Priority = "critical" | "high" | "normal" | "low";

/** Every paged list endpoint answers in this shape. `total` is the count across
 * the whole filtered set, not the page — a table footer that says "50 records"
 * over a database of fifty thousand is lying to the officer reading it. */
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface DocumentSummary {
  id: string;
  file_name: string;
  media_type: string;
  byte_size: number;
  page_count: number;
  declared_record_format: string;
  uploaded_by: string | null;
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
   * `formatArea()` (lib/format.ts), which coerces either shape correctly, rather
   * than calling `.toFixed()` on it directly. */
  total_area_sq_metre: number | string | null;
  mismatch_score: number | null;
  confidence_score: number | null;
  recommended_action: RecommendedAction | null;
  requires_human_review: boolean;
  validation_issue_count: number;
  validation_highest_severity: Severity | null;

  // -- adjudication workflow --------------------------------------------------
  review_status: ReviewStatus;
  priority: Priority;
  priority_score: number;
  assigned_to: string | null;
  sla_due_at: string | null;
  decided_by: string | null;
  decided_at: string | null;
  correction_count: number;
  has_human_corrections: boolean;

  created_at: string | null;
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
  parcel_key?: string | null;
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
  decision_note: string | null;
  /** Why the triage service placed this record where it did in the queue.
   * Computed per request rather than stored, so it always reflects the current
   * scores. */
  triage_reasons: string[];
  document?: DocumentSummary | null;
}

export interface ReviewEvent {
  id: string;
  parcel_id: string;
  field_path: string;
  previous_value?: { value: unknown } | null;
  new_value?: { value: unknown } | null;
  action: string;
  reviewer: string;
  reviewer_role: string | null;
  note: string | null;
  created_at: string;
}

export interface AuditEntry extends ReviewEvent {
  parcel_key: string | null;
  village: string | null;
  district: string | null;
}

export interface CorrectionResponse {
  event: ReviewEvent;
  applied: boolean;
  revalidated: boolean;
  revalidation_note: string | null;
  issues_before: number;
  issues_after: number;
  highest_severity_after: Severity | null;
  parcel: ParcelDetail;
}

export interface UploadResponse {
  document: DocumentSummary;
  parcels: ParcelSummary[];
  warnings: string[];
  duplicate_of: string | null;
  processing_ms: number | null;
}

export interface BatchUploadResponse {
  results: UploadResponse[];
  failures: { file_name: string; reason: string; error_type?: string }[];
  succeeded: number;
  failed: number;
}

export interface AnalyticsSummary {
  total_parcels: number;
  total_documents: number;
  total_pages: number;
  auto_validated: number;
  needs_review: number;
  flagged: number;
  by_status: Record<string, number>;
  by_priority: Record<string, number>;
  avg_confidence: number | null;
  avg_mismatch: number | null;
  median_confidence: number | null;
  total_area_hectares: number;
  districts_covered: number;
  villages_covered: number;
  overdue_count: number;
  unassigned_count: number;
  corrections_applied: number;
  straight_through_rate: number;
  staff_hours_saved: number;
  minutes_saved_per_record_assumption: number;
  generated_at: string;
}

export interface DistrictRow {
  state: string | null;
  district: string | null;
  total: number;
  flagged: number;
  approved: number;
  pending: number;
  overdue: number;
  avg_confidence: number | null;
  avg_mismatch: number | null;
  total_area_hectares: number;
  completion_rate: number;
}

export interface TimeseriesPoint {
  date: string;
  ingested: number;
  decided: number;
  corrections: number;
}

export interface RuleFrequency {
  rule_code: string;
  count: number;
  severities: Record<string, number>;
  worst_severity: Severity;
}

export interface ThroughputRow {
  reviewer: string;
  role: string | null;
  events: number;
  corrections: number;
  decisions: number;
  last_active: string | null;
}

export interface QueueHealth {
  buckets: { priority: Priority; open: number; overdue: number }[];
  total_open: number;
  total_overdue: number;
  oldest_open_at: string | null;
}

export interface RuleCatalogueEntry {
  code: string;
  group: string;
  description: string;
  enabled: boolean;
  severity_override: Severity | null;
  registered: boolean;
}

export interface SystemStatus {
  status: "ok" | "degraded";
  environment: string;
  auth_enforced: boolean;
  signed_in_as: { username: string; role: string };
  database: {
    dialect: string;
    reachable: boolean;
    fallback_active: boolean;
    configured_url_scheme: string;
  };
  limits: { max_upload_size_mb: number; max_batch_upload_files: number };
  sla_hours_by_priority: Record<string, number>;
}

export interface Facets {
  tree: Record<string, Record<string, Record<string, number>>>;
  states: string[];
  districts: string[];
  review_statuses: { value: ReviewStatus; label: string }[];
  priorities: Priority[];
}

export interface ParcelListFilters {
  q?: string;
  state?: string;
  district?: string;
  village?: string;
  review_status?: ReviewStatus;
  priority?: Priority;
  severity?: Severity;
  recommended_action?: RecommendedAction;
  assigned_to?: string;
  unassigned?: boolean;
  overdue?: boolean;
  open_only?: boolean;
  requires_review?: boolean;
  min_mismatch?: number;
  max_confidence?: number;
  sort?: "priority" | "updated_at" | "created_at" | "mismatch" | "confidence" | "village" | "area";
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

/** A GeoJSON FeatureCollection whose feature properties carry the parcel fields
 * the map colours and labels by, so the map never needs a second fetch per pin. */
export interface ParcelFeatureProperties {
  parcel_id: string;
  parcel_key: string;
  village: string | null;
  district: string | null;
  state: string | null;
  khata_number: string | null;
  survey_number: string | null;
  mismatch_score: number | null;
  confidence_score: number | null;
  review_status: ReviewStatus;
  priority: Priority;
  severity: Severity | null;
  issue_count: number;
  area_sq_metre: number | null;
}

export interface ParcelGeoJson {
  type: "FeatureCollection";
  features: {
    type: "Feature";
    id: string;
    geometry: GeoJSON.Geometry;
    properties: ParcelFeatureProperties;
  }[];
  properties: { returned: number; total_matching_filter: number; without_geometry: number };
}
