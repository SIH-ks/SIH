/**
 * Demo fixtures for running the console without the backend + PostGIS stack.
 *
 * These exist so `npm run dev` alone produces a populated, representative console
 * — they are NOT sample output from the real pipeline. Anything rendered from this
 * file is flagged in the UI with a DEMO DATA marker (see `HeaderBar`), so fixture
 * values can never be mistaken for genuine extraction results.
 *
 * The records deliberately span the full outcome range the discrepancy engine can
 * produce: exact match, area-sum contradiction, severe geometric disagreement,
 * unmatched geometry (confidence-capped), and an unreadable scan.
 */

import type { ParcelDetail, ParcelSummary, ValidationIssue } from "@/types/parcel";

/** A small square polygon around a point, sized in metres. */
function plot(lat: number, lon: number, halfSideM: number): GeoJSON.Geometry {
  const dLat = halfSideM / 111_320;
  const dLon = halfSideM / (111_320 * Math.cos((lat * Math.PI) / 180));
  return {
    type: "Polygon",
    coordinates: [
      [
        [lon - dLon, lat - dLat],
        [lon + dLon, lat - dLat],
        [lon + dLon, lat + dLat],
        [lon - dLon, lat + dLat],
        [lon - dLon, lat - dLat],
      ],
    ],
  };
}

interface DemoRecord extends ParcelSummary {
  geometry: GeoJSON.Geometry | null;
  record_format: string;
  issues: ValidationIssue[];
}

export const DEMO_PARCELS: DemoRecord[] = [
  {
    id: "d1a4f0c2-0000-4000-8000-000000000001",
    document_id: "doc-0001",
    parcel_key: "Kondhwa/45/142",
    state: "Maharashtra",
    district: "Pune",
    village: "Kondhwa",
    khata_number: "45",
    survey_number: "142",
    total_area_sq_metre: 8005,
    mismatch_score: 1.8,
    confidence_score: 0.94,
    recommended_action: "auto_approve",
    requires_human_review: false,
    validation_issue_count: 0,
    validation_highest_severity: null,
    updated_at: "2026-09-07T09:12:44Z",
    record_format: "satbara_7_12",
    geometry: plot(18.4575, 73.8896, 45),
    issues: [],
  },
  {
    id: "d1a4f0c2-0000-4000-8000-000000000002",
    document_id: "doc-0002",
    parcel_key: "Wagholi/112/88/2",
    state: "Maharashtra",
    district: "Pune",
    village: "Wagholi",
    khata_number: "112",
    survey_number: "88/2",
    total_area_sq_metre: 12000,
    mismatch_score: 14.2,
    confidence_score: 0.81,
    recommended_action: "review_queue",
    requires_human_review: true,
    validation_issue_count: 2,
    validation_highest_severity: "error",
    updated_at: "2026-09-07T09:10:02Z",
    record_format: "satbara_7_12",
    geometry: plot(18.5793, 73.9812, 52),
    issues: [
      {
        rule_code: "AREA_SUM_MISMATCH",
        severity: "error",
        message:
          "Sub-divisions total 1-24-00 H-R-Sq.M but the parcel's printed total area is 1-20-00 H-R-Sq.M — a difference of 400.00 sq m.",
        json_path: "$.sub_divisions",
        observed: "12400.0000",
        expected: "12000.0000",
        remediation:
          "Verify each sub-division area against the scan; a single-digit transcription error in one row is the most common cause.",
        confidence: 0.92,
      },
      {
        rule_code: "SHARE_SUM_NOT_UNITY",
        severity: "warning",
        message: "Recorded ownership shares sum to 5/6 (0.8333), short of the whole parcel.",
        json_path: "$.owners",
        observed: "5/6",
        expected: "1",
        remediation: "An owner row may be missing, or one recorded share is understated.",
        confidence: 1,
      },
    ],
  },
  {
    id: "d1a4f0c2-0000-4000-8000-000000000003",
    document_id: "doc-0003",
    parcel_key: "Bahadurgarh/7/311",
    state: "Haryana",
    district: "Jhajjar",
    village: "Bahadurgarh",
    khata_number: "7",
    survey_number: "311",
    total_area_sq_metre: 20234,
    mismatch_score: 100,
    confidence_score: 0.42,
    recommended_action: "field_verification",
    requires_human_review: true,
    validation_issue_count: 3,
    validation_highest_severity: "critical",
    updated_at: "2026-09-07T09:04:31Z",
    record_format: "jamabandi",
    geometry: plot(28.6926, 76.9214, 64),
    issues: [
      {
        rule_code: "GEOMETRY_AREA_MISMATCH",
        severity: "critical",
        message:
          "Recorded area 20,234 sq m disagrees with the cadastral polygon (16,384 sq m) by 23.5% — beyond the severe threshold.",
        json_path: "$.total_area",
        observed: "20234",
        expected: "16384",
        remediation: "Dispatch a surveyor; text and map describe materially different extents.",
        confidence: 0.88,
      },
      {
        rule_code: "GEOMETRY_OVERLAP",
        severity: "error",
        message: "This parcel's polygon overlaps parcel Bahadurgarh/7/312 by 812.40 sq m.",
        json_path: "$.geometry",
        remediation: "Possible encroachment or duplicated allotment — requires field verification.",
        confidence: 0.79,
      },
      {
        rule_code: "ENCUMBRANCE_ACTIVE",
        severity: "info",
        message: "Active bank charge recorded in favour of Punjab National Bank.",
        json_path: "$.encumbrances[0]",
        remediation: "Material to any transaction on this parcel.",
        confidence: 1,
      },
    ],
  },
  {
    id: "d1a4f0c2-0000-4000-8000-000000000004",
    document_id: "doc-0004",
    parcel_key: "Sikar/23/1094",
    state: "Rajasthan",
    district: "Sikar",
    village: "Ranoli",
    khata_number: "23",
    survey_number: "1094",
    total_area_sq_metre: 5058,
    mismatch_score: null,
    confidence_score: 0.55,
    recommended_action: "review_queue",
    requires_human_review: true,
    validation_issue_count: 1,
    validation_highest_severity: "warning",
    updated_at: "2026-09-07T08:58:17Z",
    record_format: "jamabandi",
    geometry: null,
    issues: [
      {
        rule_code: "GEOMETRY_NOT_FOUND",
        severity: "warning",
        message:
          "No cadastral polygon could be matched to this parcel; confidence is capped at 0.55 pending geometry.",
        json_path: "$.geometry",
        remediation: "Check the Bhu-Naksha layer for this hadbast, or queue for DGPS survey.",
        confidence: 1,
      },
    ],
  },
  {
    id: "d1a4f0c2-0000-4000-8000-000000000005",
    document_id: "doc-0005",
    parcel_key: "Karnal/301/56",
    state: "Haryana",
    district: "Karnal",
    village: "Nilokheri",
    khata_number: "301",
    survey_number: "56",
    total_area_sq_metre: null,
    mismatch_score: null,
    confidence_score: 0.31,
    recommended_action: "reject_re_scan",
    requires_human_review: true,
    validation_issue_count: 2,
    validation_highest_severity: "critical",
    updated_at: "2026-09-07T08:41:55Z",
    record_format: "jamabandi",
    geometry: null,
    issues: [
      {
        rule_code: "TOTAL_AREA_MISSING",
        severity: "critical",
        message: "No total area could be read for this parcel; every area-based check below is skipped.",
        json_path: "$.total_area",
        remediation: "Re-examine the area column on the source scan; it may be faint, torn, or unconventionally formatted.",
        confidence: 1,
      },
      {
        rule_code: "LOW_OCR_CONFIDENCE",
        severity: "warning",
        message: "Mean OCR confidence on page 1 is 0.31 — the scan is too degraded to adjudicate.",
        json_path: "$.pages[0]",
        remediation: "Re-scan at 300 dpi or higher.",
        confidence: 1,
      },
    ],
  },
  {
    id: "d1a4f0c2-0000-4000-8000-000000000006",
    document_id: "doc-0006",
    parcel_key: "Baramati/88/204",
    state: "Maharashtra",
    district: "Pune",
    village: "Baramati",
    khata_number: "88",
    survey_number: "204",
    total_area_sq_metre: 6070,
    mismatch_score: 3.4,
    confidence_score: 0.89,
    recommended_action: "auto_approve",
    requires_human_review: false,
    validation_issue_count: 1,
    validation_highest_severity: "info",
    updated_at: "2026-09-07T08:33:09Z",
    record_format: "satbara_7_12",
    geometry: plot(18.1514, 74.5815, 39),
    issues: [
      {
        rule_code: "ENCUMBRANCE_ACTIVE",
        severity: "info",
        message: "Active mortgage recorded in favour of Bank of Maharashtra.",
        json_path: "$.encumbrances[0]",
        remediation: "Material to any transaction on this parcel.",
        confidence: 1,
      },
    ],
  },
];

export function demoSummaries(): ParcelSummary[] {
  return DEMO_PARCELS.map(({ geometry, record_format, issues, ...summary }) => summary);
}

export function demoDetail(id: string): ParcelDetail | null {
  const record = DEMO_PARCELS.find((p) => p.id === id);
  if (!record) return null;
  const { geometry, record_format, issues, ...summary } = record;
  return {
    ...summary,
    artifact_json: {
      geometry,
      record_format,
      validation_issues: issues,
    },
  };
}
