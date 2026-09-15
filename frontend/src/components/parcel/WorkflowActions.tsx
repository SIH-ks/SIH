"use client";

import { CheckCircle2, Loader2, RefreshCw, ShieldAlert, UserPlus, XCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/Primitives";
import { useToast } from "@/components/ui/Toast";
import { assignParcel, changeStatus, revalidateParcel } from "@/lib/client-api";
import { cn } from "@/lib/format";
import { can, type SessionProfile } from "@/lib/session";
import type { ParcelDetail } from "@/types/parcel";

/**
 * The decision bar: claim, approve, reject, escalate, reassign, re-validate.
 *
 * **Approve and reject require a reviewer role.** An operator can key
 * corrections all day but cannot put a record into the register — that
 * separation of duties is the point of the whole workflow, and it is enforced by
 * the API regardless of what this component draws. Buttons the current role
 * cannot use are hidden rather than shown-and-refused, with one line saying why.
 *
 * Rejecting and escalating both demand a note. A rejection with no stated reason
 * leaves the operator who has to re-scan the document with nothing to act on,
 * and leaves the audit trail unable to answer the only question anyone will ask
 * of it later.
 */

type Pending = "approve" | "reject" | "escalate" | "claim" | "release" | "revalidate" | null;

export function WorkflowActions({
  parcel,
  profile,
}: {
  parcel: ParcelDetail;
  profile: SessionProfile | null;
}) {
  const router = useRouter();
  const toast = useToast();
  const [pending, setPending] = useState<Pending>(null);
  const [noteFor, setNoteFor] = useState<"reject" | "escalate" | null>(null);
  const [note, setNote] = useState("");

  const isReviewer = can.approve(profile?.role);
  const isOperator = can.write(profile?.role);
  const mine = parcel.assigned_to === profile?.username;
  const decided = parcel.review_status === "approved" || parcel.review_status === "rejected";

  const run = async (action: Pending, work: () => Promise<unknown>, success: string) => {
    setPending(action);
    try {
      await work();
      toast.success(success);
      setNoteFor(null);
      setNote("");
      router.refresh();
    } catch (error) {
      toast.error("Action refused", error instanceof Error ? error.message : undefined);
    } finally {
      setPending(null);
    }
  };

  const transition = (status: string, success: string, action: Pending, withNote?: string) =>
    run(action, () => changeStatus(parcel.id, status, withNote), success);

  return (
    <div className="rounded-xl border border-line bg-surface-card shadow-card">
      <div className="border-b border-line px-4 py-2.5">
        <h2 className="text-sm font-semibold text-ink-primary">Adjudication</h2>
        <p className="text-xs text-ink-muted">
          {decided
            ? `Decided by @${parcel.decided_by} — re-open into review to change it.`
            : parcel.assigned_to
              ? `Claimed by @${parcel.assigned_to}${mine ? " (you)" : ""}`
              : "Unclaimed — in the shared pool"}
        </p>
      </div>

      <div className="flex flex-col gap-3 px-4 py-3.5">
        {!isReviewer && (
          <p className="rounded-lg bg-surface-sunken px-3 py-2 text-xs leading-relaxed text-ink-secondary">
            {isOperator
              ? "You can key corrections on this record, but entering it into the register is a Revenue Inspector's decision. That separation is deliberate."
              : "Your role has read-only oversight access. Nothing on this page can be changed by you."}
          </p>
        )}

        {isReviewer && (
          <>
            {/* -- Primary decisions ------------------------------------------- */}
            {!decided && (
              <div className="grid grid-cols-2 gap-2">
                <Button
                  variant="primary"
                  icon={pending === "approve" ? Loader2 : CheckCircle2}
                  disabled={pending !== null}
                  onClick={() => transition("approved", "Record approved into the register", "approve")}
                  className={cn("bg-status-good hover:bg-status-good/90", pending === "approve" && "[&_svg]:animate-spin")}
                >
                  Approve
                </Button>
                <Button
                  variant="danger"
                  icon={XCircle}
                  disabled={pending !== null}
                  onClick={() => setNoteFor(noteFor === "reject" ? null : "reject")}
                >
                  Reject
                </Button>
              </div>
            )}

            {decided && (
              <Button
                variant="secondary"
                icon={RefreshCw}
                disabled={pending !== null}
                onClick={() => transition("in_review", "Re-opened for review", "claim")}
              >
                Re-open for review
              </Button>
            )}

            {/* -- Secondary actions -------------------------------------------- */}
            <div className="grid grid-cols-2 gap-2">
              {parcel.review_status === "pending" && (
                <Button
                  variant="secondary"
                  icon={UserPlus}
                  disabled={pending !== null}
                  onClick={() => transition("in_review", "Claimed — this record is now yours", "claim")}
                >
                  Claim
                </Button>
              )}
              {parcel.review_status !== "escalated" && !decided && (
                <Button
                  variant="secondary"
                  icon={ShieldAlert}
                  disabled={pending !== null}
                  onClick={() => setNoteFor(noteFor === "escalate" ? null : "escalate")}
                >
                  Escalate
                </Button>
              )}
              {parcel.assigned_to && (
                <Button
                  variant="ghost"
                  disabled={pending !== null}
                  onClick={() =>
                    run(
                      "release",
                      () => assignParcel(parcel.id, null, "Released to the shared pool"),
                      "Released back to the unclaimed pool",
                    )
                  }
                >
                  Release
                </Button>
              )}
            </div>

            {/* -- Note-taking, required for reject and escalate ---------------- */}
            {noteFor && (
              <div className="animate-fade-up rounded-lg border border-line bg-surface-sunken p-3">
                <label htmlFor="decision-note" className="block text-xs font-semibold text-ink-secondary">
                  {noteFor === "reject"
                    ? "Why is this record being rejected?"
                    : "Why does this need a senior officer?"}
                </label>
                <p className="mt-0.5 text-[11px] text-ink-muted">
                  {noteFor === "reject"
                    ? "The operator who has to re-scan needs something to act on, and the audit trail needs a reason."
                    : "Boundary dispute, suspected fraud, or a contradiction the document itself cannot resolve."}
                </p>
                <textarea
                  id="decision-note"
                  rows={3}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder={
                    noteFor === "reject"
                      ? "e.g. Ownership column illegible below row 3 — re-scan at 400 dpi."
                      : "e.g. Sub-division areas contradict the printed total by 1,720 m²; needs a field visit."
                  }
                  className="mt-2 w-full rounded-lg border border-line-strong bg-surface-card px-3 py-2 text-sm text-ink-primary outline-none focus:border-series-1"
                />
                <div className="mt-2 flex gap-2">
                  <Button
                    size="sm"
                    variant={noteFor === "reject" ? "danger" : "primary"}
                    disabled={note.trim().length < 8 || pending !== null}
                    onClick={() =>
                      noteFor === "reject"
                        ? transition("rejected", "Record rejected — re-scan requested", "reject", note)
                        : transition("escalated", "Escalated to a senior officer", "escalate", note)
                    }
                  >
                    {pending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
                    Confirm {noteFor === "reject" ? "rejection" : "escalation"}
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setNoteFor(null)}>
                    Cancel
                  </Button>
                </div>
                {note.trim().length > 0 && note.trim().length < 8 && (
                  <p className="mt-1.5 text-[11px] text-status-warning-ink">
                    A little more detail — this note is what the next person reads.
                  </p>
                )}
              </div>
            )}
          </>
        )}

        {isOperator && (
          <Button
            variant="subtle"
            icon={pending === "revalidate" ? Loader2 : RefreshCw}
            disabled={pending !== null}
            className={pending === "revalidate" ? "[&_svg]:animate-spin" : undefined}
            onClick={() =>
              run("revalidate", () => revalidateParcel(parcel.id), "Rule engine re-run against this record")
            }
            title="Re-judge this record under the current validation policy without re-running OCR"
          >
            Re-run validation
          </Button>
        )}
      </div>

      {parcel.decision_note && (
        <div className="border-t border-line px-4 py-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">Decision note</p>
          <p className="mt-1 break-anywhere text-sm italic text-ink-secondary">“{parcel.decision_note}”</p>
        </div>
      )}
    </div>
  );
}
