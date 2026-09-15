import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { UploadWorkbench } from "@/components/upload/UploadWorkbench";
import { PageHeader } from "@/components/ui/Primitives";
import { getSessionProfile, getSystemStatus } from "@/lib/api";
import { can } from "@/lib/session";

export const metadata: Metadata = { title: "Upload scans" };
export const dynamic = "force-dynamic";

/**
 * Ingestion. Gated at the operator role — the same boundary the API enforces on
 * `POST /documents/upload`, checked here as well so an auditor is redirected
 * rather than shown a form every submission would be refused from.
 *
 * The batch and size limits come from the server's own settings rather than
 * being duplicated as constants: a deployment that raises
 * `ADHIKAR_API_MAX_UPLOAD_SIZE_MB` should not have to remember to edit the
 * frontend too.
 */
export default async function UploadPage() {
  const [profile, status] = await Promise.all([getSessionProfile(), getSystemStatus()]);

  if (!can.write(profile?.role)) redirect("/");

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Upload scans"
        description="Every page runs the full extraction, validation and discrepancy pipeline before it reaches the review queue. Nothing is entered into the register without a Revenue Inspector's decision."
      />

      <UploadWorkbench
        maxFiles={status.data?.limits.max_batch_upload_files ?? 25}
        maxSizeMb={status.data?.limits.max_upload_size_mb ?? 25}
      />
    </div>
  );
}
