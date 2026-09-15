import {
  FileSignature,
  Gavel,
  Landmark,
  Scale,
  Scroll,
  Skull,
  Split,
  Users,
  type LucideIcon,
} from "lucide-react";

import { cn, formatDate } from "@/lib/format";
import type { EventParty, OwnershipEvent, OwnershipEventType } from "@/types/succession";

/**
 * The ownership event chain, drawn as a vertical timeline.
 *
 * This is the picture the specification asks for — previous owner, death,
 * potential heirs, mutation, new owner — rendered from the same `timeline` array
 * the engine returns, so it can never show a chain the documents did not produce.
 * Each node already carries its own `evidence`, which is what makes every branch
 * on the diagram traceable back to a document and a field rather than a drawn
 * assertion.
 *
 * Two things the drawing itself commits to:
 *
 * **A death fans out to potential heirs, which is separate from who the record
 * actually shows.** The `succession_claim` node lists everyone the paperwork
 * names; the `mutation` / `record_snapshot` nodes after it show who the register
 * vested the parcel in. Drawing those as two different node shapes is what makes
 * "these people were named" and "this is who ended up holding it" visually
 * distinct — conflating them would draw a claim as a fact.
 *
 * **An inferred date is drawn differently from a recorded one.** `date_stated` on
 * each event says which; the console renders an inferred position with a dashed
 * connector and a tilde, never as if it were printed on the page.
 */

const EVENT_ICON: Record<OwnershipEventType, LucideIcon> = {
  record_snapshot: Landmark,
  death: Skull,
  succession_claim: Users,
  mutation: Scroll,
  will: FileSignature,
  relinquishment: FileSignature,
  partition: Split,
  family_settlement: Users,
  court_order: Gavel,
  other: Scale,
};

const EVENT_TONE: Record<OwnershipEventType, string> = {
  record_snapshot: "bg-series-1/15 text-series-1 ring-series-1/30",
  death: "bg-status-critical-wash text-status-critical-ink ring-status-critical/30",
  succession_claim: "bg-status-warning-wash text-status-warning-ink ring-status-warning/30",
  mutation: "bg-status-serious-wash text-status-serious-ink ring-status-serious/30",
  will: "bg-series-3/15 text-series-3 ring-series-3/30",
  relinquishment: "bg-series-3/15 text-series-3 ring-series-3/30",
  partition: "bg-series-3/15 text-series-3 ring-series-3/30",
  family_settlement: "bg-series-3/15 text-series-3 ring-series-3/30",
  court_order: "bg-series-4/15 text-series-4 ring-series-4/30",
  other: "bg-surface-sunken text-ink-secondary ring-line-strong/50",
};

const EVENT_LABEL: Record<OwnershipEventType, string> = {
  record_snapshot: "Record of Rights",
  death: "Death recorded",
  succession_claim: "Potential heirs identified",
  mutation: "Mutation",
  will: "Will",
  relinquishment: "Relinquishment deed",
  partition: "Partition deed",
  family_settlement: "Family settlement",
  court_order: "Court order",
  other: "Other document",
};

function PartyList({ parties, label }: { parties: EventParty[]; label: string }) {
  if (parties.length === 0) return null;
  return (
    <div className="mt-1.5 flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5 text-xs">
      <span className="text-ink-muted">{label}</span>
      {parties.map((party, index) => (
        <span key={`${party.name}-${index}`} className="font-medium text-ink-primary">
          {party.name}
          {party.share && <span className="text-ink-muted"> ({party.share})</span>}
          {index < parties.length - 1 && <span className="text-ink-muted">,</span>}
        </span>
      ))}
    </div>
  );
}

export function OwnershipTimeline({ events }: { events: OwnershipEvent[] }) {
  if (events.length === 0) {
    return (
      <p className="px-4 py-8 text-center text-sm text-ink-muted">
        No ownership events could be assembled from the submitted documents.
      </p>
    );
  }

  return (
    <ol className="relative px-4 py-4">
      {events.map((event, index) => {
        const Icon = EVENT_ICON[event.event_type];
        const isLast = index === events.length - 1;
        return (
          <li key={`${event.event_type}-${event.sequence}`} className="relative flex gap-4 pb-6 last:pb-0">
            {!isLast && (
              <span
                className={cn(
                  "absolute left-[15px] top-8 h-[calc(100%-1rem)] w-px",
                  event.date_stated ? "bg-line" : "bg-line/50",
                )}
                style={!event.date_stated ? { backgroundImage: "linear-gradient(to bottom, var(--line) 50%, transparent 50%)", backgroundSize: "1px 6px" } : undefined}
                aria-hidden
              />
            )}
            <span
              className={cn(
                "z-10 mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ring-1 ring-inset",
                EVENT_TONE[event.event_type],
              )}
              title={EVENT_LABEL[event.event_type]}
            >
              <Icon className="h-4 w-4" strokeWidth={2} aria-hidden />
            </span>

            <div className="min-w-0 flex-1 pt-0.5">
              <p className="flex flex-wrap items-baseline gap-x-2 text-[13px]">
                <span className="font-semibold text-ink-primary">{EVENT_LABEL[event.event_type]}</span>
                <span className="text-xs text-ink-muted">
                  {event.event_date ? (
                    <>
                      {!event.date_stated && "~"}
                      {formatDate(event.event_date)}
                      {!event.date_stated && " (inferred from revenue year)"}
                    </>
                  ) : (
                    "date not stated"
                  )}
                </span>
              </p>
              <p className="mt-1 text-[13px] leading-snug text-ink-secondary">{event.description}</p>
              <PartyList parties={event.from_owners} label="From:" />
              <PartyList parties={event.to_owners} label="To:" />
              {event.evidence.length > 0 && (
                <p className="mt-1.5 flex flex-wrap gap-x-1.5 gap-y-0.5 text-[11px] text-ink-muted">
                  {event.evidence
                    .filter((e) => e.document_label)
                    .map((e, i) => (
                      <span
                        key={i}
                        className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono"
                        title={e.field_path ?? undefined}
                      >
                        {e.document_label}
                      </span>
                    ))}
                </p>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
