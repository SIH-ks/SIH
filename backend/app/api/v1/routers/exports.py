"""Export endpoints: CSV extracts, the raw artifact, and a printable verification report.

Export is not a nice-to-have in a government workflow, it is how the work leaves the
system: a taluk office reconciles against its own register in a spreadsheet, an audit
cell wants the trail as a file, and a Tehsildar's decision has to become a signed
sheet of paper before it means anything. Each format here exists because a specific
person downstream needs that shape.

Filtering is shared with the parcels router (``_apply_filters``) so an export always
covers exactly the set of records the console was showing when it was launched.
"""

from __future__ import annotations

import csv
import html
import io
import json
import uuid
from datetime import UTC, datetime
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....db.base import get_db
from ....models.enums import Priority, ReviewStatus
from ....models.record import ParcelRecord, ReviewEvent
from ...deps import CurrentUser, current_user
from .parcels import _apply_filters

router = APIRouter(prefix="/exports", tags=["exports"])

_PARCEL_COLUMNS = [
    "parcel_id",
    "parcel_key",
    "state",
    "district",
    "village",
    "khata_number",
    "survey_number",
    "total_area_sq_metre",
    "total_area_hectare",
    "record_format",
    "confidence_score",
    "mismatch_score",
    "recommended_action",
    "review_status",
    "priority",
    "priority_score",
    "assigned_to",
    "decided_by",
    "decided_at",
    "sla_due_at",
    "validation_issue_count",
    "validation_highest_severity",
    "correction_count",
    "created_at",
    "updated_at",
]


def _stream_csv(header: list[str], rows: Iterator[list]) -> StreamingResponse:
    """Yield CSV a row at a time rather than building the whole file in memory.

    A district export is hundreds of thousands of rows; materialising that as one
    string would hold tens of megabytes per concurrent download for no benefit, and
    the client sees the first bytes immediately either way.

    ``utf-8-sig`` because these files are opened in Excel, which reads a plain UTF-8
    CSV as the local ANSI codepage and mangles every Devanagari or Kannada village
    name in the file. The BOM is what makes the names survive the trip.
    """

    def generate() -> Iterator[bytes]:
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(header)
        yield buffer.getvalue().encode("utf-8-sig")
        buffer.seek(0)
        buffer.truncate(0)

        for row in rows:
            writer.writerow(row)
            yield buffer.getvalue().encode("utf-8")
            buffer.seek(0)
            buffer.truncate(0)

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="adhikar-export-{stamp}.csv"'},
    )


@router.get("/parcels.csv")
def export_parcels_csv(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(current_user),
    q: str | None = None,
    state: str | None = None,
    district: str | None = None,
    village: str | None = None,
    review_status: ReviewStatus | None = None,
    priority: Priority | None = None,
    severity: str | None = None,
    open_only: bool = False,
    overdue: bool = False,
    limit: int = Query(50_000, ge=1, le=500_000),
) -> StreamingResponse:
    """The filtered record set as a spreadsheet.

    Area is emitted in both square metres and hectares. Not redundancy: revenue
    records are quoted in hectares and the canonical stored value is square metres,
    and letting each downstream office do that division itself is how two versions of
    the same figure end up in circulation.
    """
    stmt = _apply_filters(select(ParcelRecord), filters=locals()).order_by(
        ParcelRecord.district, ParcelRecord.village, ParcelRecord.parcel_key
    )

    def rows() -> Iterator[list]:
        # yield_per streams from the server-side cursor instead of loading the whole
        # result set, which is the half of "streaming export" that actually bounds
        # memory -- chunked HTTP writes over a fully-materialised list would not.
        for p in db.scalars(stmt.limit(limit).execution_options(yield_per=500)):
            area = float(p.total_area_sq_metre) if p.total_area_sq_metre is not None else None
            yield [
                str(p.id),
                p.parcel_key,
                p.state,
                p.district,
                p.village,
                p.khata_number,
                p.survey_number,
                area,
                round(area / 10_000, 4) if area is not None else None,
                p.record_format,
                p.confidence_score,
                p.mismatch_score,
                p.recommended_action,
                p.review_status,
                p.priority,
                p.priority_score,
                p.assigned_to,
                p.decided_by,
                p.decided_at.isoformat() if p.decided_at else None,
                p.sla_due_at.isoformat() if p.sla_due_at else None,
                p.validation_issue_count,
                p.validation_highest_severity,
                p.correction_count,
                p.created_at.isoformat() if p.created_at else None,
                p.updated_at.isoformat() if p.updated_at else None,
            ]

    return _stream_csv(_PARCEL_COLUMNS, rows())


@router.get("/audit.csv")
def export_audit_csv(
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(current_user),
    reviewer: str | None = None,
    district: str | None = None,
    limit: int = Query(100_000, ge=1, le=500_000),
) -> StreamingResponse:
    """The audit trail as a file, for an audit cell that works outside this system."""
    stmt = (
        select(ReviewEvent, ParcelRecord.parcel_key, ParcelRecord.district, ParcelRecord.village)
        .join(ParcelRecord, ParcelRecord.id == ReviewEvent.parcel_id)
        .order_by(ReviewEvent.created_at.desc())
    )
    if reviewer:
        stmt = stmt.where(ReviewEvent.reviewer == reviewer)
    if district:
        stmt = stmt.where(ParcelRecord.district == district)

    header = [
        "event_id", "timestamp", "parcel_id", "parcel_key", "district", "village",
        "action", "field_path", "previous_value", "new_value", "reviewer", "reviewer_role",
        "note", "source_ip",
    ]

    def rows() -> Iterator[list]:
        for event, parcel_key, district_name, village in db.execute(stmt.limit(limit)):
            yield [
                str(event.id),
                event.created_at.isoformat() if event.created_at else None,
                str(event.parcel_id),
                parcel_key,
                district_name,
                village,
                event.action,
                event.field_path,
                json.dumps((event.previous_value or {}).get("value"), ensure_ascii=False),
                json.dumps((event.new_value or {}).get("value"), ensure_ascii=False),
                event.reviewer,
                event.reviewer_role,
                event.note,
                event.source_ip,
            ]

    return _stream_csv(header, rows())


@router.get("/parcels/{parcel_id}/artifact.json")
def export_artifact(
    parcel_id: uuid.UUID, db: Session = Depends(get_db), _: CurrentUser = Depends(current_user)
) -> StreamingResponse:
    """The complete extraction artifact for one parcel, verbatim.

    The machine-readable counterpart to the report below: this is what another
    department's system ingests, and it is deliberately the stored JSON rather than a
    re-serialisation, so what leaves is exactly what was audited.
    """
    parcel = db.get(ParcelRecord, parcel_id)
    if parcel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="parcel not found")

    payload = json.dumps(
        {
            "parcel_id": str(parcel.id),
            "parcel_key": parcel.parcel_key,
            "exported_at": datetime.now(UTC).isoformat(),
            "review_status": parcel.review_status,
            "scores": {
                "confidence": parcel.confidence_score,
                "mismatch": parcel.mismatch_score,
                "recommended_action": parcel.recommended_action,
            },
            "geometry": parcel.geometry,
            "artifact": parcel.artifact_json,
        },
        ensure_ascii=False,
        indent=2,
    )
    return StreamingResponse(
        iter([payload.encode("utf-8")]),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{parcel.parcel_key.replace("/", "-")}.json"'},
    )


# ---------------------------------------------------------------------------
# Printable verification report
# ---------------------------------------------------------------------------


def _esc(value: object) -> str:
    return html.escape("—" if value is None or value == "" else str(value))


@router.get("/parcels/{parcel_id}/report.html", response_class=HTMLResponse)
def verification_report(
    parcel_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(current_user),
) -> HTMLResponse:
    """A self-contained, printable Record Verification Report for one parcel.

    Server-rendered HTML with an embedded print stylesheet rather than a generated
    PDF: it opens in any browser, prints to PDF from there with the department's own
    header and footer, and adds no rendering dependency to the deployment. Everything
    is inline -- no external CSS, fonts or images -- so the saved file stays readable
    years later on a machine that cannot reach this server, which is the actual
    requirement for a document that goes into a case file.

    The report states what the machine found *and* what a human decided, including
    when they disagreed. A verification document that hid the disagreement would be
    worse than none.
    """
    parcel = db.get(ParcelRecord, parcel_id)
    if parcel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="parcel not found")

    artifact = parcel.artifact_json or {}
    issues = artifact.get("validation_issues") or []
    owners = artifact.get("owners") or []
    events = list(
        db.scalars(
            select(ReviewEvent).where(ReviewEvent.parcel_id == parcel_id).order_by(ReviewEvent.created_at.asc())
        ).all()
    )

    area_sqm = float(parcel.total_area_sq_metre) if parcel.total_area_sq_metre is not None else None
    status_label = ReviewStatus(parcel.review_status).label if parcel.review_status else "—"

    owner_rows = "".join(
        f"<tr><td>{_esc(o.get('serial_number'))}</td>"
        f"<td>{_esc((o.get('name') or {}).get('raw'))}</td>"
        f"<td>{_esc((o.get('name') or {}).get('relation_name'))}</td>"
        f"<td>{_esc(o.get('tenure_type'))}</td>"
        f"<td>{_esc(_share(o))}</td></tr>"
        for o in owners
    ) or "<tr><td colspan='5' class='muted'>No owner rows were extracted from this record.</td></tr>"

    issue_rows = "".join(
        f"<tr class='sev-{_esc(i.get('severity'))}'>"
        f"<td><span class='pill pill-{_esc(i.get('severity'))}'>{_esc(i.get('severity'))}</span></td>"
        f"<td class='mono'>{_esc(i.get('rule_code'))}</td>"
        f"<td>{_esc(i.get('message'))}"
        + (f"<div class='muted small'>{_esc(i.get('remediation'))}</div>" if i.get("remediation") else "")
        + "</td></tr>"
        for i in issues
    ) or "<tr><td colspan='3' class='muted'>No validation findings — the record is internally consistent.</td></tr>"

    event_rows = "".join(
        f"<tr><td class='mono small'>{_esc(e.created_at.strftime('%d %b %Y %H:%M') if e.created_at else None)}</td>"
        f"<td>{_esc(e.action)}</td>"
        f"<td class='mono small'>{_esc(e.field_path)}</td>"
        f"<td class='small'>{_esc((e.previous_value or {}).get('value'))} → "
        f"<strong>{_esc((e.new_value or {}).get('value'))}</strong></td>"
        f"<td class='small'>{_esc(e.reviewer)}<div class='muted'>{_esc(e.reviewer_role)}</div></td></tr>"
        for e in events
    ) or "<tr><td colspan='5' class='muted'>No human action has been recorded on this record.</td></tr>"

    generated = datetime.now(UTC).strftime("%d %B %Y, %H:%M UTC")

    return HTMLResponse(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Verification Report — {_esc(parcel.parcel_key)}</title>
<style>
  @page {{ size: A4; margin: 16mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font: 12px/1.5 "Georgia", "Times New Roman", serif; color: #1a1a1a; margin: 0; background: #fff; }}
  .sheet {{ max-width: 820px; margin: 0 auto; padding: 24px; }}
  header {{ border-bottom: 3px double #0f2557; padding-bottom: 12px; margin-bottom: 18px; }}
  h1 {{ font-size: 20px; margin: 0 0 2px; letter-spacing: .3px; }}
  h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 1px; color: #0f2557;
        border-bottom: 1px solid #d4d4d8; padding-bottom: 4px; margin: 22px 0 8px; }}
  .sub {{ color: #52525b; font-size: 11px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 6px; }}
  th, td {{ text-align: left; padding: 5px 8px; border-bottom: 1px solid #e4e4e7; vertical-align: top; }}
  th {{ background: #f4f4f5; font-size: 10px; text-transform: uppercase; letter-spacing: .6px; color: #3f3f46; }}
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px 18px; }}
  .field label {{ display: block; font-size: 9.5px; text-transform: uppercase; letter-spacing: .7px; color: #71717a; }}
  .field div {{ font-size: 13px; font-weight: 600; }}
  .mono {{ font-family: "Consolas", "Courier New", monospace; }}
  .small {{ font-size: 10.5px; }}
  .muted {{ color: #71717a; }}
  .pill {{ display: inline-block; padding: 1px 7px; border-radius: 9px; font-size: 9.5px;
           text-transform: uppercase; letter-spacing: .5px; font-family: sans-serif; font-weight: 700; }}
  .pill-info {{ background: #dbeafe; color: #1e40af; }}
  .pill-warning {{ background: #fef3c7; color: #92400e; }}
  .pill-error {{ background: #fee2e2; color: #991b1b; }}
  .pill-critical {{ background: #991b1b; color: #fff; }}
  .banner {{ border: 1px solid #0f2557; background: #f8fafc; padding: 10px 14px; margin: 14px 0;
             display: flex; justify-content: space-between; align-items: center; }}
  .banner strong {{ font-size: 15px; }}
  .sign {{ margin-top: 40px; display: grid; grid-template-columns: 1fr 1fr; gap: 40px; }}
  .sign div {{ border-top: 1px solid #1a1a1a; padding-top: 5px; font-size: 10.5px; }}
  footer {{ margin-top: 26px; border-top: 1px solid #d4d4d8; padding-top: 8px;
            font-size: 9.5px; color: #71717a; }}
  @media print {{ .noprint {{ display: none; }} .sheet {{ padding: 0; }} }}
</style></head>
<body><div class="sheet">
<header>
  <h1>Record of Rights — Verification Report</h1>
  <div class="sub">Adhikar · Intelligent Land Record Digitization &amp; Validation System</div>
</header>

<div class="banner">
  <div>
    <div class="sub">Adjudication status</div>
    <strong>{_esc(status_label)}</strong>
    {f'<div class="sub">Decided by {_esc(parcel.decided_by)} on {_esc(parcel.decided_at.strftime("%d %b %Y") if parcel.decided_at else None)}</div>' if parcel.decided_by else '<div class="sub">Not yet adjudicated by a revenue officer.</div>'}
  </div>
  <div style="text-align:right">
    <div class="sub">Extraction confidence</div>
    <strong>{f"{parcel.confidence_score * 100:.1f}%" if parcel.confidence_score is not None else "—"}</strong>
    <div class="sub">Cadastral mismatch {f"{parcel.mismatch_score:.1f}" if parcel.mismatch_score is not None else "—"}</div>
  </div>
</div>

<h2>Parcel identity</h2>
<div class="grid">
  <div class="field"><label>State</label><div>{_esc(parcel.state)}</div></div>
  <div class="field"><label>District</label><div>{_esc(parcel.district)}</div></div>
  <div class="field"><label>Village</label><div>{_esc(parcel.village)}</div></div>
  <div class="field"><label>Khata / Khewat</label><div>{_esc(parcel.khata_number)}</div></div>
  <div class="field"><label>Survey / Gat no.</label><div>{_esc(parcel.survey_number)}</div></div>
  <div class="field"><label>Record format</label><div>{_esc(parcel.record_format)}</div></div>
  <div class="field"><label>Total area</label><div>{f"{area_sqm:,.2f} sq m" if area_sqm is not None else "—"}</div></div>
  <div class="field"><label>Total area (ha)</label><div>{f"{area_sqm / 10_000:.4f}" if area_sqm is not None else "—"}</div></div>
  <div class="field"><label>Parcel key</label><div class="mono small">{_esc(parcel.parcel_key)}</div></div>
</div>

<h2>Recorded interests</h2>
<table><thead><tr><th>Sl.</th><th>Name</th><th>Relation</th><th>Tenure</th><th>Share</th></tr></thead>
<tbody>{owner_rows}</tbody></table>

<h2>Validation findings ({len(issues)})</h2>
<table><thead><tr><th style="width:74px">Severity</th><th style="width:190px">Rule</th><th>Finding</th></tr></thead>
<tbody>{issue_rows}</tbody></table>

<h2>Audit trail ({len(events)} entries)</h2>
<table><thead><tr><th>When</th><th>Action</th><th>Field</th><th>Change</th><th>By</th></tr></thead>
<tbody>{event_rows}</tbody></table>

<div class="sign">
  <div>Verified by (Revenue Inspector / Tehsildar)</div>
  <div>Countersigned (Tahsil Office seal)</div>
</div>

<footer>
  Generated {generated} by {_esc(user.full_name)} ({_esc(user.role.label)}) ·
  Machine-assisted extraction. This report records both the automated findings and every human
  action taken on them; it does not itself confer title. Figures are as extracted from the source
  scan and, where corrected, as amended by the named officer above.
</footer>

<p class="noprint muted small" style="margin-top:18px">
  Tip: print to PDF from your browser to file this against the case record.
</p>
</div></body></html>""")


def _share(owner: dict) -> str | None:
    share = owner.get("share")
    if not share:
        return None
    numerator, denominator = share.get("numerator"), share.get("denominator")
    if numerator is None or not denominator:
        return share.get("raw_text")
    return f"{numerator}/{denominator}"
