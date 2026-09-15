"use client";

import { Check, Loader2, RotateCcw, Undo2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Primitives";
import { useToast } from "@/components/ui/Toast";
import { submitCorrection } from "@/lib/client-api";
import { cn } from "@/lib/format";
import { can, type SessionProfile } from "@/lib/session";
import type { ParcelDetail, RealBoundingBox, RealFieldProvenance } from "@/types/parcel";

/**
 * The editable projection of the extracted record.
 *
 * The fields are **derived from the artifact**, not hard-coded: a record with
 * three owners shows three owner rows, and one with none shows none. That
 * matters because the previous fixed four-field form could only ever correct the
 * first owner of any record, which is not what a Jamabandi page contains.
 *
 * Each field carries the exact JSON path the backend writes to. Saving one field
 * POSTs that path, and the API applies it to `artifact_json` **and re-runs the
 * whole rule engine** — so the response says how many findings the correction
 * resolved or created, and this component reports that back rather than a
 * generic "saved". A reviewer who fixes a mis-read sub-division area and watches
 * `AREA_SUM_MISMATCH` clear has been shown their correction was right.
 */

export interface EditableField {
  path: string;
  label: string;
  value: string;
  group: string;
  /** The provenance key for this field, when the mapper records one. Distinct
   * strings from `path` on purpose — provenance is keyed by the LLM wire
   * schema's names (`owners[0].name.raw_name`), the artifact by the domain
   * model's (`owners[0].name.raw`). Conflating the two is an easy silent bug. */
  provenanceKey?: string;
  hint?: string;
  type?: "text" | "number" | "date";
}

/** Read a dotted/bracket path out of the artifact. Mirrors the backend's
 * `services.corrections.read_path`, deliberately tolerant of a missing branch. */
function read(source: unknown, path: string): unknown {
  const segments = path.replace(/\[(\d+)\]/g, ".$1").split(".").filter(Boolean);
  let current: unknown = source;
  for (const segment of segments) {
    if (current === null || current === undefined) return undefined;
    if (Array.isArray(current)) {
      const index = Number(segment);
      if (Number.isNaN(index)) return undefined;
      current = current[index];
    } else if (typeof current === "object") {
      current = (current as Record<string, unknown>)[segment];
    } else {
      return undefined;
    }
  }
  return current;
}

function asText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return "";
  return String(value);
}

/** Build the field list from whatever this particular record actually contains. */
export function deriveFields(parcel: ParcelDetail): EditableField[] {
  const artifact = parcel.artifact_json;
  const fields: EditableField[] = [];

  const push = (field: EditableField) => {
    if (read(artifact, field.path) !== undefined) fields.push(field);
  };

  // -- jurisdiction ---------------------------------------------------------
  for (const [key, label] of [
    ["state", "State"],
    ["district", "District"],
    ["tehsil", "Tehsil / Taluk"],
    ["village", "Village"],
  ] as const) {
    push({
      path: `jurisdiction.${key}`,
      label,
      value: asText(read(artifact, `jurisdiction.${key}`)),
      group: "Jurisdiction",
    });
  }

  // -- identifiers ----------------------------------------------------------
  for (const [key, label, hint] of [
    ["khata_number", "Khata / Khewat", "The ownership-holding identifier"],
    ["khatauni_number", "Khatauni", "Cultivation-holding identifier"],
    ["survey_number", "Survey / Gat no.", undefined],
    ["sub_survey_number", "Hissa no.", undefined],
  ] as const) {
    push({
      path: key,
      label,
      value: asText(read(artifact, key)),
      group: "Identifiers",
      hint,
    });
  }

  const khasra = read(artifact, "khasra_numbers");
  if (Array.isArray(khasra)) {
    khasra.forEach((_, index) =>
      fields.push({
        path: `khasra_numbers[${index}]`,
        label: `Khasra no. ${index + 1}`,
        value: asText(khasra[index]),
        group: "Identifiers",
      }),
    );
  }

  // -- area -----------------------------------------------------------------
  push({
    path: "total_area.sq_metre",
    label: "Total area (m²)",
    value: asText(read(artifact, "total_area.sq_metre")),
    group: "Area",
    provenanceKey: "total_area",
    type: "number",
    hint: "The printed parcel total. Every arithmetic rule compares derived sums against this figure.",
  });

  const subDivisions = read(artifact, "sub_divisions");
  if (Array.isArray(subDivisions)) {
    subDivisions.forEach((_, index) => {
      fields.push({
        path: `sub_divisions[${index}].sub_division_number`,
        label: `Sub-division ${index + 1} — number`,
        value: asText(read(artifact, `sub_divisions[${index}].sub_division_number`)),
        group: "Area",
      });
      fields.push({
        path: `sub_divisions[${index}].area.sq_metre`,
        label: `Sub-division ${index + 1} — area (m²)`,
        value: asText(read(artifact, `sub_divisions[${index}].area.sq_metre`)),
        group: "Area",
        type: "number",
      });
    });
  }

  // -- owners ---------------------------------------------------------------
  const owners = read(artifact, "owners");
  if (Array.isArray(owners)) {
    owners.forEach((_, index) => {
      fields.push({
        path: `owners[${index}].name.raw`,
        label: `Owner ${index + 1} — name`,
        value: asText(read(artifact, `owners[${index}].name.raw`)),
        group: "Ownership",
        provenanceKey: `owners[${index}].name.raw_name`,
      });
      fields.push({
        path: `owners[${index}].name.relation_name`,
        label: `Owner ${index + 1} — father / husband`,
        value: asText(read(artifact, `owners[${index}].name.relation_name`)),
        group: "Ownership",
      });
      fields.push({
        path: `owners[${index}].serial_number`,
        label: `Owner ${index + 1} — serial`,
        value: asText(read(artifact, `owners[${index}].serial_number`)),
        group: "Ownership",
      });
      if (read(artifact, `owners[${index}].share`) !== null) {
        fields.push({
          path: `owners[${index}].share.numerator`,
          label: `Owner ${index + 1} — share numerator`,
          value: asText(read(artifact, `owners[${index}].share.numerator`)),
          group: "Ownership",
          type: "number",
        });
        fields.push({
          path: `owners[${index}].share.denominator`,
          label: `Owner ${index + 1} — share denominator`,
          value: asText(read(artifact, `owners[${index}].share.denominator`)),
          group: "Ownership",
          type: "number",
        });
      }
    });
  }

  // -- mutations ------------------------------------------------------------
  const mutations = read(artifact, "mutations");
  if (Array.isArray(mutations)) {
    mutations.forEach((_, index) => {
      fields.push({
        path: `mutations[${index}].entry_date`,
        label: `Mutation ${index + 1} — entry date`,
        value: asText(read(artifact, `mutations[${index}].entry_date`)),
        group: "Mutation chain",
        type: "date",
      });
      fields.push({
        path: `mutations[${index}].status`,
        label: `Mutation ${index + 1} — status`,
        value: asText(read(artifact, `mutations[${index}].status`)),
        group: "Mutation chain",
      });
    });
  }

  return fields;
}

export function boxesByPath(parcel: ParcelDetail): Record<string, RealBoundingBox> {
  const provenance = (parcel.artifact_json.provenance ?? {}) as Record<string, RealFieldProvenance>;
  const out: Record<string, RealBoundingBox> = {};
  for (const [key, entry] of Object.entries(provenance)) {
    if (entry?.bbox) out[key] = entry.bbox;
  }
  return out;
}

// ---------------------------------------------------------------------------

export function ExtractedRecordForm({
  parcel,
  profile,
  onFocusField,
  onCorrectionApplied,
}: {
  parcel: ParcelDetail;
  profile: SessionProfile | null;
  onFocusField: (field: EditableField | null) => void;
  onCorrectionApplied?: () => void;
}) {
  const router = useRouter();
  const toast = useToast();

  const original = useMemo(() => deriveFields(parcel), [parcel]);
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(original.map((field) => [field.path, field.value])),
  );
  const [saving, setSaving] = useState<string | null>(null);
  const [savedPaths, setSavedPaths] = useState<Set<string>>(new Set());

  const editable = can.write(profile?.role);

  const groups = useMemo(() => {
    const map = new Map<string, EditableField[]>();
    for (const field of original) {
      if (!map.has(field.group)) map.set(field.group, []);
      map.get(field.group)!.push(field);
    }
    return [...map.entries()];
  }, [original]);

  const dirty = original.filter((field) => (values[field.path] ?? "") !== field.value);

  const save = async (field: EditableField) => {
    setSaving(field.path);
    try {
      const result = await submitCorrection(parcel.id, {
        field_path: field.path,
        new_value: values[field.path],
        note: `Corrected ${field.label} in the reviewer console`,
      });

      const delta = result.issues_after - result.issues_before;
      const description = !result.revalidated
        ? `Saved, but the rule engine could not re-run: ${result.revalidation_note ?? "record does not satisfy the schema"}`
        : delta < 0
          ? `${Math.abs(delta)} validation finding${Math.abs(delta) === 1 ? "" : "s"} resolved by this correction.`
          : delta > 0
            ? `Careful — this correction created ${delta} new finding${delta === 1 ? "" : "s"}.`
            : `Re-validated: ${result.issues_after} finding${result.issues_after === 1 ? "" : "s"} unchanged.`;

      if (!result.revalidated || delta > 0) {
        toast.push({ tone: "warning", title: `${field.label} updated`, description });
      } else {
        toast.success(`${field.label} updated`, description);
      }

      setSavedPaths((current) => new Set(current).add(field.path));
      onCorrectionApplied?.();
      router.refresh();
    } catch (error) {
      toast.error(
        `Could not save ${field.label}`,
        error instanceof Error ? error.message : "The API refused the correction.",
      );
    } finally {
      setSaving(null);
    }
  };

  const reset = (field: EditableField) => {
    setValues((current) => ({ ...current, [field.path]: field.value }));
  };

  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-line bg-surface-card shadow-card">
      <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-2.5">
        <div>
          <h2 className="text-sm font-semibold text-ink-primary">Extracted record</h2>
          <p className="text-xs text-ink-muted">
            {original.length} field{original.length === 1 ? "" : "s"} read from this scan
            {dirty.length > 0 && (
              <span className="ml-1.5 font-semibold text-brand-saffron">· {dirty.length} unsaved</span>
            )}
          </p>
        </div>
        {!editable && (
          <span className="rounded-full bg-surface-sunken px-2.5 py-1 text-[11px] font-medium text-ink-muted">
            Read-only for your role
          </span>
        )}
      </div>

      <div className="max-h-[560px] overflow-y-auto">
        {groups.map(([group, fields]) => (
          <section key={group}>
            <h3 className="sticky top-0 z-10 border-b border-line bg-surface-sunken px-4 py-1.5 text-[10px] font-bold uppercase tracking-wider text-ink-muted">
              {group}
            </h3>
            <div className="flex flex-col gap-3 px-4 py-3.5">
              {fields.map((field) => {
                const value = values[field.path] ?? "";
                const changed = value !== field.value;
                const busy = saving === field.path;

                return (
                  <div key={field.path}>
                    <div className="mb-1 flex items-baseline justify-between gap-2">
                      <label
                        htmlFor={`field-${field.path}`}
                        className="text-xs font-medium text-ink-secondary"
                      >
                        {field.label}
                      </label>
                      {savedPaths.has(field.path) && !changed && (
                        <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-status-good-ink">
                          <Check className="h-3 w-3" aria-hidden /> Saved
                        </span>
                      )}
                    </div>

                    <div className="flex gap-1.5">
                      <input
                        id={`field-${field.path}`}
                        type={field.type === "date" ? "text" : field.type ?? "text"}
                        inputMode={field.type === "number" ? "decimal" : undefined}
                        value={value}
                        disabled={!editable || busy}
                        onChange={(event) =>
                          setValues((current) => ({ ...current, [field.path]: event.target.value }))
                        }
                        onFocus={() => onFocusField(field)}
                        onBlur={() => onFocusField(null)}
                        className={cn(
                          "h-9 w-full rounded-lg border bg-surface-card px-3 text-sm text-ink-primary outline-none transition-colors disabled:opacity-70",
                          changed
                            ? "border-brand-saffron bg-brand-saffron/[0.06]"
                            : "border-line-strong focus:border-series-1",
                        )}
                      />

                      {changed && editable && (
                        <>
                          <Button
                            size="sm"
                            variant="primary"
                            disabled={busy}
                            onClick={() => save(field)}
                            className="shrink-0"
                            title="Apply this correction and re-run the rule engine"
                          >
                            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : "Save"}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => reset(field)}
                            className="shrink-0 px-2"
                            title="Discard this change"
                          >
                            <Undo2 className="h-3.5 w-3.5" aria-hidden />
                          </Button>
                        </>
                      )}
                    </div>

                    {field.hint && !changed && (
                      <p className="mt-1 text-[11px] leading-snug text-ink-muted">{field.hint}</p>
                    )}
                    {changed && (
                      <p className="mt-1 text-[11px] text-ink-muted">
                        was <span className="font-mono">{field.value || "—"}</span> · saving re-runs all 22
                        validation rules against the corrected record
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          </section>
        ))}

        {original.length === 0 && (
          <p className="px-4 py-10 text-center text-sm text-ink-muted">
            This record's artifact carries no editable fields.
          </p>
        )}
      </div>

      {dirty.length > 1 && editable && (
        <div className="flex items-center justify-between gap-3 border-t border-line bg-surface-sunken px-4 py-2.5">
          <span className="text-xs text-ink-secondary">
            {dirty.length} fields changed. Each saves — and re-validates — independently, so a rejected
            correction never takes the others with it.
          </span>
          <Button
            size="sm"
            variant="ghost"
            icon={RotateCcw}
            onClick={() => setValues(Object.fromEntries(original.map((f) => [f.path, f.value])))}
          >
            Discard all
          </Button>
        </div>
      )}
    </div>
  );
}
