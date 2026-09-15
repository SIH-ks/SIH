import { ChevronLeft } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { SuccessionCaseWorkspace } from "@/components/succession/SuccessionCaseWorkspace";
import { ErrorPanel, PageHeader } from "@/components/ui/Primitives";
import { NOT_FOUND, getSuccessionCase } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  const { id } = await params;
  const item = await getSuccessionCase(id);
  if (!item.data) return { title: "Succession case" };
  return { title: `${item.data.case_reference} — Succession` };
}

export default async function SuccessionCaseDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const item = await getSuccessionCase(id);

  if (item.error) {
    if (item.error.status === NOT_FOUND) notFound();
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Succession case" />
        <ErrorPanel message={item.error.message} unreachable={item.error.unreachable} />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <Link
        href="/succession"
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-muted transition-colors hover:text-series-1"
      >
        <ChevronLeft className="h-3.5 w-3.5" aria-hidden /> Back to succession cases
      </Link>
      <SuccessionCaseWorkspace case={item.data} />
    </div>
  );
}
