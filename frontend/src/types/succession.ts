/**
 * Mirrors backend/app/schemas/succession.py, in the same hand-written style as
 * `types/parcel.ts` — in a production build, generate both from the FastAPI
 * OpenAPI schema so they cannot drift silently.
 *
 * Note what is absent from `SuccessionOutcome`: there is no member meaning
 * "fraud". The engine has no basis for that conclusion and deliberately carries
 * no code that reaches it, so neither does the type the console renders. The
 * strongest thing this feature says is `review_required`.
 */

/** Statuses lower-cased to match the API; the console supplies display casing. */
export type SuccessionOutcome = "validated" | "incomplete" | "inconsistent" | "review_required";

export type SuccessionRiskLevel = "low" | "medium" | "high" | "critical";

export type CheckStatus = "pass" | "warning" | "fail" | "review_required" | "not_applicable";

export type SuccessionAction =
  | "accept_record"
  | "obtain_additional_documents"
  | "human_review"
  | "refer_to_revenue_authority";

export type SuccessionEventKind =
  | "owner_death_succession"
  | "ownership_transition"
  | "no_transition_detected"
  | "insufficient_documents";

export type OwnershipEventType =
  | "record_snapshot"
  | "death"
  | "succession_claim"
  | "mutation"
  | "will"
  | "relinquishment"
  | "partition"
  | "family_settlement"
  | "court_order"
  | "other";

/** Where a value a check relied on came from — the unit of explainability.
 * A finding citing two of these renders as "Old Jamabandi → total_area = 5.00 ha"
 * against "Mutation → area = 6.20 ha", which a reviewer can check against the
 * paper; a finding without them is an assertion. */
export interface EvidenceRef {
  document_type: string;
  document_id: string | null;
  document_label: string | null;
  field_path: string | null;
  value: string | null;
  raw_value?: string | null;
}

export interface SuccessionCheck {
  /** Positive-sense name of what was checked, e.g. `OWNER_IDENTITY_MATCH`. */
  rule: string;
  /** The stable catalogue code the finding is filed under; appears in audits. */
  rule_code: string;
  status: CheckStatus;
  explanation: string;
  evidence: EvidenceRef[];
  /** Similarity, where the check matched text rather than comparing exactly.
   * Carried so a fuzzy link is auditable: "matched at 0.91 against a 0.88
   * threshold" is checkable, "names matched" is not. */
  match_score: number | null;
  confidence: number;
  risk_points: number;
  remediation: string | null;
}

/** One line of the risk score's arithmetic. The score is their sum and nothing
 * else — a score a reviewer cannot decompose is one they cannot argue with. */
export interface RiskContribution {
  rule: string;
  rule_code: string;
  status: CheckStatus;
  base_points: number;
  multiplier: number;
  points: number;
  reason: string;
}

export interface EventParty {
  name: string;
  share: string | null;
  relation: string | null;
}

export interface OwnershipEvent {
  sequence: number;
  event_type: OwnershipEventType;
  event_date: string | null;
  /** False when the position was inferred (from a revenue year, say) rather than
   * read off the document. Drawn differently — an inferred position on a
   * timeline must not look like a recorded one. */
  date_stated: boolean;
  parcel_key: string | null;
  person: string | null;
  from_owners: EventParty[];
  to_owners: EventParty[];
  description: string;
  evidence: EvidenceRef[];
}

/** A person the documents name as family of the deceased.
 * *Candidate*, not heir: `stated_share` is populated only from a document that
 * itself states a share, and nothing here asserts entitlement. */
export interface HeirCandidate {
  name: string;
  relation: string;
  stated_share: string | null;
  is_minor: boolean;
  source: EvidenceRef | null;
}

export interface SuccessionOwner {
  name: string;
  share: string | null;
}

export interface SuccessionReport {
  case_id: string;
  parcel_key: string | null;
  policy_name: string;

  outcome: SuccessionOutcome;
  risk_level: SuccessionRiskLevel;
  risk_score: number;
  event_type: SuccessionEventKind;
  recommended_action: SuccessionAction;

  /** Assembled from what the checks found, so it cannot drift from them. */
  summary: string;

  parcel: Record<string, unknown>;
  previous_owners: SuccessionOwner[];
  current_owners: SuccessionOwner[];

  deceased: string[];
  /** True only when a submitted certificate names a person the *previous record*
   * recorded as owner — not merely that a certificate was submitted. */
  death_verified: boolean;
  potential_heirs: HeirCandidate[];

  checks: SuccessionCheck[];
  issues: string[];
  /** The non-clear checks in the engine's ordinary ValidationIssue shape — the
   * same structure `/parcels/{id}` returns, so the existing findings component
   * renders them unchanged. */
  findings: {
    rule_code: string;
    severity: string;
    message: string;
    json_path: string;
    confidence: number;
    remediation?: string | null;
  }[];

  risk_contributions: RiskContribution[];
  timeline: OwnershipEvent[];
  evidence_documents: EvidenceRef[];

  /** Carried in the payload, not only in the UI: the report is exported and
   * printed, and a caveat living on one screen stops travelling with the
   * conclusion the moment anybody does either. */
  disclaimer: string;
  counts_by_status: Record<string, number>;
  duration_ms: number;
  generated_at: string | null;
}

export interface SuccessionCaseSummary {
  id: string;
  case_reference: string;
  parcel_id: string | null;
  parcel_key: string | null;
  state: string | null;
  district: string | null;
  village: string | null;

  outcome: SuccessionOutcome;
  risk_level: SuccessionRiskLevel;
  risk_score: number;
  event_type: SuccessionEventKind;
  recommended_action: SuccessionAction;
  death_verified: boolean;
  heir_count: number;
  check_count: number;
  open_finding_count: number;

  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface SuccessionCaseDetail extends SuccessionCaseSummary {
  report: SuccessionReport;
  /** The bundle exactly as the engine read it. Shown so a reviewer can see what
   * the system *read* from the documents, not only what it concluded — two
   * different questions, and only one of them is a finding. */
  case_json: Record<string, unknown>;
  normalization_warnings: string[];
  document_ids: string[];
  notes: string | null;
  events: OwnershipEvent[];
}

export interface SuccessionSummary {
  total_cases: number;
  open_cases: number;
  by_outcome: Record<string, number>;
  by_risk_level: Record<string, number>;
  deaths_verified: number;
  avg_risk_score: number;
}

export interface SuccessionCaseFilters {
  q?: string;
  state?: string;
  district?: string;
  village?: string;
  outcome?: SuccessionOutcome;
  risk_level?: SuccessionRiskLevel;
  event_type?: SuccessionEventKind;
  open_only?: boolean;
  min_risk?: number;
  parcel_id?: string;
  sort?: "risk" | "created_at" | "updated_at" | "village";
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}
