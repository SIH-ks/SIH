"use client";

import { useState } from "react";

import { API_ORIGIN, submitCorrection } from "@/lib/api";
import { formatArea } from "@/lib/utils";
import type { ParcelDetail, RealBoundingBox, RealFieldProvenance } from "@/types/parcel";

import { DocumentViewer } from "./DocumentViewer";
import { EXTRACTED_FIELD_ORDER, ExtractedDataForm, type ExtractedFieldKey } from "./ExtractedDataForm";

const REVIEWER_IDENTITY = "console-reviewer";

/** Real backend JSON paths each field corrects, matching the ai-engine's
 * `LandParcelRecord` shape exactly -- see the artifact this parcel's `artifact_json`
 * actually is. Used only when a correction is saved; display values are read more
 * loosely (see `deriveFields`) since a demo record may be missing pieces a real one
 * wouldn't be. */
const FIELD_PATHS: Record<ExtractedFieldKey, string> = {
  ownerName: "owners[0].name.raw",
  khasraNumber: "khasra_numbers[0]",
  totalArea: "total_area.sq_metre",
  date: "mutations[0].entry_date",
};

/**
 * The *provenance* path for each field -- deliberately different strings from
 * `FIELD_PATHS` above. `FIELD_PATHS` addresses the domain-shaped `LandParcelRecord`
 * dump (`owners[0].name.raw`); provenance is keyed by the wire schema's own field
 * names instead (`owners[0].name.raw_name`), because that's the literal string
 * `adhikar.llm.mapper` writes -- see its `_record_provenance` call sites. Getting
 * these two conflated is an easy, silent mistake (both single strings, both
 * "the owner name field"), so they're named and commented separately on purpose.
 *
 * `khasraNumber` and `date` have no entry: the mapper doesn't record provenance for
 * them today (only owner name and total area are instrumented), so those two
 * fields always fall back to the Document Viewer's simulated highlight -- an
 * honest gap, not a bug to work around here.
 */
const PROVENANCE_PATHS: Partial<Record<ExtractedFieldKey, string>> = {
  ownerName: "owners[0].name.raw_name",
  totalArea: "total_area",
};

function deriveRealBoxes(parcel: ParcelDetail): Partial<Record<ExtractedFieldKey, RealBoundingBox>> {
  const artifact = parcel.artifact_json as Record<string, unknown>;
  const provenance = (artifact.provenance as Record<string, RealFieldProvenance> | undefined) ?? {};
  const boxes: Partial<Record<ExtractedFieldKey, RealBoundingBox>> = {};
  for (const [field, path] of Object.entries(PROVENANCE_PATHS) as [ExtractedFieldKey, string][]) {
    const bbox = provenance[path]?.bbox;
    if (bbox) boxes[field] = bbox;
  }
  return boxes;
}

function deriveFields(parcel: ParcelDetail): Record<ExtractedFieldKey, string> {
  const artifact = parcel.artifact_json as Record<string, unknown>;
  const owners = Array.isArray(artifact.owners) ? (artifact.owners as Array<Record<string, unknown>>) : [];
  const khasra = Array.isArray(artifact.khasra_numbers) ? (artifact.khasra_numbers as string[]) : [];
  const mutations = Array.isArray(artifact.mutations) ? (artifact.mutations as Array<Record<string, unknown>>) : [];

  const ownerName =
    (owners[0]?.name as Record<string, unknown> | undefined)?.raw ??
    (owners[0]?.name as Record<string, unknown> | undefined)?.transliterated;

  const mutationDate = mutations[0]?.entry_date;

  return {
    ownerName: typeof ownerName === "string" ? ownerName : "",
    khasraNumber: khasra[0] ?? parcel.survey_number ?? "",
    totalArea: formatArea(parcel.total_area_sq_metre),
    date:
      typeof mutationDate === "string"
        ? mutationDate
        : new Date(parcel.updated_at).toISOString().slice(0, 10),
  };
}

/**
 * Composes the Document Viewer and Extracted Data Form into the split-screen
 * workspace and owns the one piece of state that connects them: which field is
 * currently focused. This has to live above both panels (not inside either one)
 * since the highlight it drives is rendered by the viewer but triggered by the
 * form -- a sibling relationship that only their shared parent can coordinate.
 */
export function ValidationWorkspace({ parcel, fileName }: { parcel: ParcelDetail; fileName: string }) {
  const [values, setValues] = useState<Record<ExtractedFieldKey, string>>(() => deriveFields(parcel));
  const [activeField, setActiveField] = useState<ExtractedFieldKey | null>(null);

  const fieldMeta = EXTRACTED_FIELD_ORDER.map((f) => ({ ...f, confidence: parcel.confidence_score }));
  const realImageUrl = parcel.page_image_urls.length > 0 ? `${API_ORIGIN}${parcel.page_image_urls[0]}` : null;
  const realBoxes = deriveRealBoxes(parcel);

  const handleSave = async () => {
    const original = deriveFields(parcel);
    const changed = (Object.keys(values) as ExtractedFieldKey[]).filter((key) => values[key] !== original[key]);
    await Promise.all(
      changed.map((key) =>
        submitCorrection(parcel.id, REVIEWER_IDENTITY, {
          field_path: FIELD_PATHS[key],
          new_value: values[key],
        }).catch(() => null),
      ),
    );
  };

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.3fr_1fr]">
      <DocumentViewer
        fileName={fileName}
        fields={values}
        activeField={activeField}
        realImageUrl={realImageUrl}
        realBoxes={realBoxes}
      />
      <ExtractedDataForm
        values={values}
        fieldMeta={fieldMeta}
        onChange={(key, value) => setValues((v) => ({ ...v, [key]: value }))}
        onFieldFocus={setActiveField}
        onSave={handleSave}
      />
    </div>
  );
}
