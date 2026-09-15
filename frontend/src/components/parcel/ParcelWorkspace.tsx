"use client";

import { useState } from "react";

import { DocumentViewer } from "@/components/parcel/DocumentViewer";
import {
  ExtractedRecordForm,
  boxesByPath,
  type EditableField,
} from "@/components/parcel/ExtractedRecordForm";
import { API_ORIGIN } from "@/lib/api-config";
import type { SessionProfile } from "@/lib/session";
import type { ParcelDetail } from "@/types/parcel";

/**
 * The split-screen workspace: source scan on the left, extracted fields on the
 * right, and one piece of shared state between them — which field is focused.
 *
 * That state has to live here rather than in either panel: the highlight is
 * *rendered* by the viewer but *triggered* by the form, a sibling relationship
 * only their common parent can coordinate.
 */
export function ParcelWorkspace({
  parcel,
  profile,
}: {
  parcel: ParcelDetail;
  profile: SessionProfile | null;
}) {
  const [active, setActive] = useState<EditableField | null>(null);

  const boxes = boxesByPath(parcel);
  // Provenance is keyed by the LLM wire schema's field names, which differ from
  // the artifact's own paths — hence `provenanceKey` on each field rather than
  // reusing `path`. A field the mapper does not instrument simply has no box,
  // and the viewer then draws nothing at all rather than guessing a position.
  const activeBox = active?.provenanceKey ? (boxes[active.provenanceKey] ?? null) : null;

  const pageUrls = parcel.page_image_urls.map((url) =>
    url.startsWith("http") ? url : `${API_ORIGIN}${url}`,
  );
  const fileName =
    parcel.document?.file_name ??
    `${parcel.village ?? "record"}-${parcel.survey_number ?? parcel.khata_number ?? parcel.id.slice(0, 8)}`;

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[1.25fr_1fr]">
      <DocumentViewer
        pageUrls={pageUrls}
        fileName={fileName}
        activeBox={activeBox}
        activeLabel={active?.label}
      />
      <ExtractedRecordForm parcel={parcel} profile={profile} onFocusField={setActive} />
    </div>
  );
}
