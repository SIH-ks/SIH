/**
 * Demo fixtures for running the console without the backend + PostGIS stack.
 *
 * These exist so `npm run dev` alone produces a populated, representative console
 * — they are NOT sample output from the real pipeline. Anything rendered from this
 * file is flagged in the UI with a "Demo data" marker, so fixture values can never
 * be mistaken for genuine extraction results.
 *
 * The records deliberately span the full outcome range the discrepancy engine can
 * produce: exact match, area-sum contradiction, severe geometric disagreement,
 * unmatched geometry (confidence-capped), and an unreadable scan.
 *
 * Shape note: `geometry` and `page_image_urls` are top-level `ParcelDetail` fields
 * (matching the real backend exactly); `owners` / `khasra_numbers` / `mutations` /
 * `total_area` / `provenance` / `validation_issues` live inside `artifact_json`,
 * also matching the real backend's `LandParcelRecord` dump. The one thing that
 * stays demo-only is `provenance` itself being absent here -- there's no real OCR
 * behind a fixture to attribute a bounding box from (see `adhikar.llm.bbox_attribution`
 * on the real path), so the Document Viewer correctly falls back to its simulated
 * highlight positions for demo records. `geometry` on a *real* upload is `null`
 * until a cadastral GeoJSON source is configured (see `ingestion.py`); demo records
 * populate it directly to exercise the map without that dependency.
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
  /** Real-shaped fields (see module docstring) -- these mirror what
   * `LandParcelRecord.model_dump()` actually produces on the backend. */
  owner_name: string | null;
  khasra_numbers: string[];
  mutation_date: string | null;
  /** Demo-only visual aid for the map's overlap detection story -- a neighbouring
   * parcel's polygon, only populated where the record's own findings already
   * narrate an overlap (see the GEOMETRY_OVERLAP issue below), so the map and the
   * text agree with each other. */
  neighbour_geometries?: GeoJSON.Geometry[];
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
    owner_name: "Ramrao Patil",
    khasra_numbers: ["142"],
    mutation_date: "2019-04-03",
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
    owner_name: "Sunita Deshmukh",
    khasra_numbers: ["88/2"],
    mutation_date: "2021-11-12",
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
    // Overlaps the subject parcel by design -- matches the GEOMETRY_OVERLAP
    // finding below exactly, so the map and the text tell the same story.
    // `plot()` centres are ~34m apart against two 64m half-sides, so the two
    // squares genuinely overlap rather than merely touching.
    neighbour_geometries: [plot(28.69283, 76.92175, 64)],
    owner_name: "Suresh Kumar",
    khasra_numbers: ["311"],
    mutation_date: "2018-06-30",
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
    owner_name: "Mohanlal Sharma",
    khasra_numbers: ["1094"],
    mutation_date: "2020-02-14",
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
    owner_name: null,
    khasra_numbers: ["56"],
    mutation_date: null,
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
    owner_name: "Anita Jadhav",
    khasra_numbers: ["204"],
    mutation_date: "2022-08-05",
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
  {
    id: "d1a4f0c2-0000-4000-8000-000000000007",
    document_id: "doc-0007",
    parcel_key: "Belagavi/12/88",
    state: "Karnataka",
    district: "Belagavi",
    village: "Angol",
    khata_number: "12",
    survey_number: "88",
    total_area_sq_metre: 9420,
    mismatch_score: 4.1,
    confidence_score: 0.91,
    recommended_action: "auto_approve",
    requires_human_review: false,
    validation_issue_count: 1,
    validation_highest_severity: "info",
    updated_at: "2026-09-08T07:15:22Z",
    record_format: "jamabandi",
    geometry: plot(15.8497, 74.4977, 48),
    owner_name: "Basavaraj Hiremath",
    khasra_numbers: ["88"],
    mutation_date: "2023-01-19",
    issues: [
      {
        rule_code: "ASSESSMENT_DISPROPORTIONATE",
        severity: "info",
        message: "Land revenue per hectare on this sub-division is 2.3x the parcel's other sub-divisions.",
        json_path: "$.sub_divisions[0].assessment_amount",
        remediation: "Consistent with a mixed irrigated/unirrigated split -- not necessarily an error, worth a glance.",
        confidence: 0.7,
      },
    ],
  },
  {
    id: "d1a4f0c2-0000-4000-8000-000000000008",
    document_id: "doc-0008",
    parcel_key: "Madurai/205/77-1",
    state: "Tamil Nadu",
    district: "Madurai",
    village: "Thiruparankundram",
    khata_number: "205",
    survey_number: "77/1",
    total_area_sq_metre: 3640,
    mismatch_score: 22.0,
    confidence_score: 0.68,
    recommended_action: "review_queue",
    requires_human_review: true,
    validation_issue_count: 2,
    validation_highest_severity: "error",
    updated_at: "2026-09-08T06:52:10Z",
    record_format: "ror_generic",
    geometry: plot(9.8615, 78.0722, 35),
    owner_name: "Muthu Selvam",
    khasra_numbers: ["77/1", "77/1"],
    mutation_date: "2020-07-22",
    issues: [
      {
        rule_code: "DUPLICATE_KHASRA_NUMBER",
        severity: "error",
        message: "Khasra number 77/1 appears twice on this document, against two different sub-divisions.",
        json_path: "$.khasra_numbers",
        remediation: "Check whether one entry is a re-survey number that should replace, not duplicate, the other.",
        confidence: 0.86,
      },
      {
        rule_code: "SHARE_MISSING",
        severity: "warning",
        message: "Two co-owners are recorded with no share stated for either -- apportionment is undefined.",
        json_path: "$.owners",
        remediation: "Confirm whether the record intends an equal split or ask the reviewer to key it in.",
        confidence: 1,
      },
    ],
  },
  {
    id: "d1a4f0c2-0000-4000-8000-000000000009",
    document_id: "doc-0009",
    parcel_key: "Lucknow/501/1200",
    state: "Uttar Pradesh",
    district: "Lucknow",
    village: "Gosainganj",
    khata_number: "501",
    survey_number: "1200",
    total_area_sq_metre: 15230,
    mismatch_score: 8.0,
    confidence_score: 0.77,
    recommended_action: "review_queue",
    requires_human_review: true,
    validation_issue_count: 2,
    validation_highest_severity: "error",
    updated_at: "2026-09-08T06:20:47Z",
    record_format: "jamabandi",
    geometry: plot(26.8467, 80.9462, 55),
    owner_name: "Rajesh Yadav",
    khasra_numbers: ["1200"],
    mutation_date: "2027-01-15",
    issues: [
      {
        rule_code: "MUTATION_DATE_IN_FUTURE",
        severity: "error",
        message: "The most recent mutation is dated 15 Jan 2027, which is after today's date.",
        json_path: "$.mutations[-1].entry_date",
        observed: "2027-01-15",
        remediation: "Almost always a two-digit-year transcription slip (e.g. '27' meant as '17' or '21') -- verify against the scan.",
        confidence: 0.95,
      },
      {
        rule_code: "MUTATION_OUT_OF_SEQUENCE",
        severity: "warning",
        message: "Mutation entries are not in chronological order in the register.",
        json_path: "$.mutations",
        remediation: "Re-check the entry dates were read from the correct column for each row.",
        confidence: 0.8,
      },
    ],
  },
  {
    id: "d1a4f0c2-0000-4000-8000-000000000010",
    document_id: "doc-0010",
    parcel_key: "Howrah/33/9-2",
    state: "West Bengal",
    district: "Howrah",
    village: "Domjur",
    khata_number: "33",
    survey_number: "9/2",
    total_area_sq_metre: 2180,
    mismatch_score: null,
    confidence_score: 0.28,
    recommended_action: "reject_re_scan",
    requires_human_review: true,
    validation_issue_count: 1,
    validation_highest_severity: "critical",
    updated_at: "2026-09-08T05:58:33Z",
    record_format: "khasra_girdawari",
    geometry: null,
    owner_name: null,
    khasra_numbers: ["9/2"],
    mutation_date: null,
    issues: [
      {
        rule_code: "NO_OWNERS_RECORDED",
        severity: "critical",
        message: "No owner rows could be extracted from this parcel at all.",
        json_path: "$.owners",
        remediation: "The ownership column is likely obscured or the table grid mis-detected -- re-scan and re-run before trusting any other field on this record.",
        confidence: 0.9,
      },
    ],
  },
  {
    id: "d1a4f0c2-0000-4000-8000-000000000011",
    document_id: "doc-0011",
    parcel_key: "Rajkot/88/456",
    state: "Gujarat",
    district: "Rajkot",
    village: "Kotharia",
    khata_number: "88",
    survey_number: "456",
    total_area_sq_metre: 7300,
    mismatch_score: 6.2,
    confidence_score: 0.73,
    recommended_action: "review_queue",
    requires_human_review: true,
    validation_issue_count: 1,
    validation_highest_severity: "error",
    updated_at: "2026-09-08T05:30:02Z",
    record_format: "jamabandi",
    geometry: plot(22.3039, 70.8022, 42),
    owner_name: "Kiritbhai Chauhan",
    khasra_numbers: ["456"],
    mutation_date: "2024-03-11",
    issues: [
      {
        rule_code: "CORRECTION_CHANGED_AREA",
        severity: "error",
        message: "A mutation typed as a clerical correction changed the recorded area by 145 sq m -- corrections should not alter area.",
        json_path: "$.mutations[2]",
        observed: "7300",
        expected: "7155",
        remediation: "Re-classify this mutation (it likely belongs under partition or a survey re-measurement) or verify the area figures on both sides of the entry.",
        confidence: 0.83,
      },
    ],
  },
  {
    id: "d1a4f0c2-0000-4000-8000-000000000012",
    document_id: "doc-0012",
    parcel_key: "Ludhiana/19/210",
    state: "Punjab",
    district: "Ludhiana",
    village: "Sidhwan Bet",
    khata_number: "19",
    survey_number: "210",
    total_area_sq_metre: 10120,
    mismatch_score: 11.5,
    confidence_score: 0.7,
    recommended_action: "review_queue",
    requires_human_review: true,
    validation_issue_count: 2,
    validation_highest_severity: "error",
    updated_at: "2026-09-08T05:02:41Z",
    record_format: "jamabandi",
    geometry: plot(30.901, 75.8573, 46),
    owner_name: "Gurpreet Singh",
    khasra_numbers: ["210"],
    mutation_date: "2021-09-09",
    issues: [
      {
        rule_code: "DUPLICATE_OWNER_SERIAL",
        severity: "error",
        message: "Owner serial number 2 is assigned to two different people on this record.",
        json_path: "$.owners",
        remediation: "One row's serial number was likely misread -- compare both entries against the scan.",
        confidence: 0.81,
      },
      {
        rule_code: "OWNER_WITHOUT_MUTATION_TRAIL",
        severity: "warning",
        message: "The current owner does not appear in any sanctioned mutation's transferee list.",
        json_path: "$.owners[1]",
        remediation: "Either an older mutation wasn't digitized, or this owner's entry predates the mutation register on file.",
        confidence: 0.72,
      },
    ],
  },
  {
    id: "d1a4f0c2-0000-4000-8000-000000000013",
    document_id: "doc-0013",
    parcel_key: "Patna/77/3009",
    state: "Bihar",
    district: "Patna",
    village: "Phulwari Sharif",
    khata_number: "77",
    survey_number: "3009",
    total_area_sq_metre: 4850,
    mismatch_score: 18.4,
    confidence_score: 0.66,
    recommended_action: "review_queue",
    requires_human_review: true,
    validation_issue_count: 2,
    validation_highest_severity: "warning",
    updated_at: "2026-09-08T04:41:19Z",
    record_format: "jamabandi",
    geometry: plot(25.5941, 85.1376, 38),
    owner_name: "Om Prakash Singh",
    khasra_numbers: ["3009"],
    mutation_date: "2019-12-02",
    issues: [
      {
        rule_code: "GEOMETRY_SLIVER",
        severity: "warning",
        message: "A 1.2m-wide gap exists between this parcel's polygon and its eastern neighbour, which should share a boundary.",
        json_path: "$.geometry",
        remediation: "Likely a digitisation seam in the source cadastral map rather than a real gap on the ground.",
        confidence: 0.6,
      },
      {
        rule_code: "IDENTIFIER_MISSING",
        severity: "warning",
        message: "No Khatauni number could be read for this parcel, only the Khasra number.",
        json_path: "$.khatauni_number",
        remediation: "Check the cultivation-holding column on the source scan.",
        confidence: 1,
      },
    ],
  },
  {
    id: "d1a4f0c2-0000-4000-8000-000000000014",
    document_id: "doc-0014",
    parcel_key: "Indore/145/67",
    state: "Madhya Pradesh",
    district: "Indore",
    village: "Rau",
    khata_number: "145",
    survey_number: "67",
    total_area_sq_metre: 6800,
    mismatch_score: 2.9,
    confidence_score: 0.93,
    recommended_action: "auto_approve",
    requires_human_review: false,
    validation_issue_count: 1,
    validation_highest_severity: "info",
    updated_at: "2026-09-08T04:10:55Z",
    record_format: "jamabandi",
    geometry: plot(22.7196, 75.8577, 41),
    owner_name: "Sunil Malviya",
    khasra_numbers: ["67"],
    mutation_date: "2022-05-30",
    issues: [
      {
        rule_code: "UNRESOLVED_VOCABULARY",
        severity: "info",
        message: "The classification term on sub-division 2 did not match any known vernacular alias and was left unclassified.",
        json_path: "$.sub_divisions[1].classification",
        observed: "\"Banjar Sailab\"",
        remediation: "A regional variant not yet in the vocabulary table -- worth adding if this term recurs.",
        confidence: 1,
      },
    ],
  },
  {
    id: "d1a4f0c2-0000-4000-8000-000000000015",
    document_id: "doc-0015",
    parcel_key: "Warangal/300/88-3",
    state: "Telangana",
    district: "Warangal",
    village: "Hanamkonda",
    khata_number: "300",
    survey_number: "88/3",
    total_area_sq_metre: 13400,
    mismatch_score: 100,
    confidence_score: 0.39,
    recommended_action: "field_verification",
    requires_human_review: true,
    validation_issue_count: 1,
    validation_highest_severity: "critical",
    updated_at: "2026-09-08T03:47:08Z",
    record_format: "ror_generic",
    geometry: plot(17.9689, 79.5941, 58),
    owner_name: "Lakshmi Narayana",
    khasra_numbers: ["88/3"],
    mutation_date: "2017-10-04",
    issues: [
      {
        rule_code: "AREA_SUM_EXCEEDS_TOTAL",
        severity: "critical",
        message: "Sub-divisions alone total 15,120 sq m, already exceeding the parcel's printed total of 13,400 sq m before any other area is counted.",
        json_path: "$.sub_divisions",
        observed: "15120",
        expected: "13400",
        remediation: "Not a rounding difference -- re-examine whether a sub-division belongs to a different parent survey number.",
        confidence: 0.94,
      },
    ],
  },
  {
    id: "d1a4f0c2-0000-4000-8000-000000000016",
    document_id: "doc-0016",
    parcel_key: "Bhubaneswar/60/512",
    state: "Odisha",
    district: "Khordha",
    village: "Patrapada",
    khata_number: "60",
    survey_number: "512",
    total_area_sq_metre: 5590,
    mismatch_score: 31.0,
    confidence_score: 0.6,
    recommended_action: "review_queue",
    requires_human_review: true,
    validation_issue_count: 2,
    validation_highest_severity: "error",
    updated_at: "2026-09-08T03:15:36Z",
    record_format: "jamabandi",
    geometry: plot(20.2961, 85.8245, 37),
    owner_name: "Priyanka Mohanty",
    khasra_numbers: ["512"],
    mutation_date: "2023-08-17",
    issues: [
      {
        rule_code: "CLASSIFICATION_SPLIT_MISMATCH",
        severity: "error",
        message: "Cultivable + non-cultivable classified areas total 5,910 sq m against a printed parcel total of 5,590 sq m.",
        json_path: "$.classified_areas",
        observed: "5910",
        expected: "5590",
        remediation: "One classified-area row's figure likely has a transcription error -- check each against the scan.",
        confidence: 0.87,
      },
      {
        rule_code: "LOW_FIELD_CONFIDENCE",
        severity: "warning",
        message: "The Vision LLM flagged its own reading of the owner's relation name as uncertain (confidence 0.52).",
        json_path: "$.owners[0].name.relation_name",
        remediation: "Cross-check the father's/husband's name against the scan before relying on it.",
        confidence: 0.52,
      },
    ],
  },
];

/** Neighbouring parcel polygons for the map's overlap-detection visual -- see
 * `DemoRecord.neighbour_geometries`'s docstring. Not part of `ParcelDetail` (real
 * neighbour geometry isn't wired on the backend yet), so the page reads this
 * directly rather than through `demoDetail()`. */
export function demoNeighbourGeometries(id: string): GeoJSON.Geometry[] {
  return DEMO_PARCELS.find((p) => p.id === id)?.neighbour_geometries ?? [];
}

export function demoSummaries(): ParcelSummary[] {
  return DEMO_PARCELS.map(
    ({ geometry, record_format, issues, owner_name, khasra_numbers, mutation_date, ...summary }) => summary,
  );
}

export function demoDetail(id: string): ParcelDetail | null {
  const record = DEMO_PARCELS.find((p) => p.id === id);
  if (!record) return null;
  const { geometry, record_format, issues, owner_name, khasra_numbers, mutation_date, ...summary } = record;
  return {
    ...summary,
    // Matches the real ParcelDetail contract exactly: geometry and page_image_urls
    // are top-level fields, not nested in artifact_json (see types/parcel.ts).
    // page_image_urls is always empty here -- there is no real scanned page behind
    // a demo fixture, so the Document Viewer correctly falls back to its mock
    // synthetic document rather than trying to show one that doesn't exist.
    geometry,
    page_image_urls: [],
    artifact_json: {
      // Real fields -- shaped exactly as the backend's LandParcelRecord dump.
      owners: owner_name ? [{ name: { raw: owner_name } }] : [],
      khasra_numbers,
      survey_number: summary.survey_number,
      total_area: summary.total_area_sq_metre !== null ? { sq_metre: summary.total_area_sq_metre } : null,
      mutations: mutation_date ? [{ entry_date: mutation_date }] : [],
      // Demo-only convenience field -- see module docstring. No `provenance` key:
      // demo fixtures have no OCR to attribute bboxes from, so the Document Viewer
      // correctly falls back to its simulated highlight positions for these.
      record_format,
      validation_issues: issues,
    },
  };
}
