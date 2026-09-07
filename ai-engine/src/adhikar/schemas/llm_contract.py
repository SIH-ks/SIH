"""The wire schema the Vision LLM fills in.

This is deliberately **not** the domain model, for three reasons.

**Numbers cross the wire as strings.** ``"0-80-05"``, ``"1,25,000"`` and ``"२-४०-००"``
are all real cell contents. Typing these as ``float`` forces the model to interpret
before it has transcribed, and silently loses precision on money. Strings let the
model do the one thing it is reliably excellent at -- reading glyphs -- and leave
interpretation to :mod:`adhikar.normalize`, which is deterministic and testable.

**Classification is not the model's job.** Vernacular terms arrive as ``raw`` text
and are resolved against :data:`~adhikar.schemas.enums.VERNACULAR_ALIASES` in code.
A model asked to choose from a closed enum on an ambiguous term will choose
confidently and wrongly; a lookup that misses produces ``UNKNOWN`` plus an
``UNRESOLVED_VOCABULARY`` finding, which is the honest outcome. The one exception is
:attr:`LlmExtraction.detected_record_format`, which is a genuine whole-document
judgement the model is well suited to make.

**Every field is required and nullable.** Strict JSON-schema output
(``additionalProperties: false`` with a complete ``required`` list) needs it, and it
converts silent omission into an explicit ``null`` -- which is information.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "LlmArea",
    "LlmClassifiedArea",
    "LlmCrop",
    "LlmEncumbrance",
    "LlmExtraction",
    "LlmJurisdiction",
    "LlmMutation",
    "LlmOwner",
    "LlmParcel",
    "LlmPerson",
    "LlmShare",
    "LlmSubDivision",
    "UnreadableRegion",
]

_STRICT = ConfigDict(extra="forbid")


class LlmArea(BaseModel):
    """An area cell, transcribed component-by-component.

    Populate only the components the document actually prints. A 7/12 extract that
    reads ``0-80-05`` sets hectare/are/sq_metre; a Jamabandi reading ``2K-8M`` sets
    kanal/marla. ``raw_text`` is always set, and is the fallback the parser uses when
    the components are ambiguous.
    """

    model_config = _STRICT

    raw_text: str | None = Field(description="The cell content exactly as printed, including separators.")
    hectare: str | None = Field(description="Hectare component, as printed.")
    are: str | None = Field(description="Are component (the 'R' in H-R-Sq.M).")
    sq_metre: str | None = Field(description="Square-metre component, or the whole area if given in sq m.")
    acre: str | None = Field(description="Acre component.")
    guntha: str | None = Field(description="Guntha component (1/40 acre).")
    kanal: str | None = Field(description="Kanal component (1/8 acre).")
    marla: str | None = Field(description="Marla component (1/20 kanal).")
    bigha: str | None = Field(description="Bigha component. Region-dependent; do not convert.")
    biswa: str | None = Field(description="Biswa component (1/20 bigha).")
    biswansi: str | None = Field(description="Biswansi component (1/20 biswa).")


class LlmPerson(BaseModel):
    model_config = _STRICT

    raw_name: str | None = Field(description="Name in the original script, exactly as printed.")
    transliterated: str | None = Field(description="Latin transliteration, if you are confident of it.")
    relation_raw: str | None = Field(
        description="The relational marker as printed, e.g. 's/o', 'w/o', 'वल्द', 'कोम'."
    )
    relation_name: str | None = Field(description="The related person's name, in the original script.")


class LlmShare(BaseModel):
    model_config = _STRICT

    raw_text: str | None = Field(description="The share exactly as printed, e.g. '1/3', '0.25', 'समान'.")
    numerator: str | None = Field(description="Numerator, when the share is printed as a fraction.")
    denominator: str | None = Field(description="Denominator, when the share is printed as a fraction.")


class LlmOwner(BaseModel):
    model_config = _STRICT

    serial_number: str | None = Field(description="The row's serial/sr. no. as printed.")
    name: LlmPerson
    tenure_raw: str | None = Field(
        description="Tenure/capacity term as printed, e.g. 'भोगवटादार वर्ग-1', 'Malik', 'कूळ'."
    )
    share: LlmShare | None
    khata_number: str | None
    remarks: str | None


class LlmClassifiedArea(BaseModel):
    model_config = _STRICT

    raw_label: str | None = Field(
        description="Classification term as printed, e.g. 'चाही', 'Gair Mumkin', 'पोट खराब'."
    )
    area: LlmArea
    irrigation_raw: str | None = Field(description="Irrigation source as printed, if stated separately.")


class LlmSubDivision(BaseModel):
    model_config = _STRICT

    sub_division_number: str | None = Field(description="Hissa / sub-division number as printed.")
    area: LlmArea
    classification_raw: str | None
    assessment_amount: str | None = Field(description="Land revenue for this sub-division, in rupees.")
    owner_serial_numbers: list[str] = Field(
        description="Owner serial numbers this sub-division is recorded against. Empty list if none."
    )
    remarks: str | None


class LlmMutation(BaseModel):
    model_config = _STRICT

    mutation_number: str | None
    type_raw: str | None = Field(description="Mutation cause as printed, e.g. 'खरेदी', 'Virasat', 'Rehan'.")
    status_raw: str | None = Field(description="Status as printed, e.g. 'मंजूर', 'Pending'.")
    entry_date_raw: str | None = Field(description="Entry date exactly as printed; do not reformat.")
    order_date_raw: str | None = Field(description="Order/sanction date exactly as printed.")
    from_parties: list[LlmPerson] = Field(description="Transferors. Empty list if none stated.")
    to_parties: list[LlmPerson] = Field(description="Transferees. Empty list if none stated.")
    area_transacted: LlmArea | None
    consideration_amount: str | None = Field(description="Sale consideration in rupees, as printed.")
    document_reference: str | None = Field(description="Registered deed no. or court decree citation.")
    raw_text: str | None = Field(
        description="The entire mutation cell verbatim. Always fill this, even when the "
        "structured fields above are complete."
    )


class LlmEncumbrance(BaseModel):
    model_config = _STRICT

    type_raw: str | None = Field(description="Charge type as printed, e.g. 'गहाण', 'Bank charge', 'बोजा'.")
    status_raw: str | None = Field(description="Status as printed, e.g. 'चालू', 'Discharged', 'कमी केला'.")
    holder_name: str | None = Field(description="Bank, society or person holding the charge.")
    amount: str | None = Field(description="Charge amount in rupees, as printed.")
    created_on_raw: str | None
    discharged_on_raw: str | None
    reference: str | None
    raw_text: str | None = Field(description="The entire 'other rights' entry verbatim.")


class LlmCrop(BaseModel):
    model_config = _STRICT

    year: str | None
    season_raw: str | None = Field(description="Season as printed, e.g. 'खरीप', 'Rabi'.")
    crop_name: str | None
    area: LlmArea | None
    irrigation_raw: str | None
    remarks: str | None


class LlmJurisdiction(BaseModel):
    model_config = _STRICT

    state: str | None
    district: str | None
    tehsil: str | None = Field(description="Tehsil / Taluka / Mandal / Block, as printed.")
    village: str | None
    hadbast_number: str | None = Field(description="Village settlement number, Jamabandi headers only.")
    revenue_year_raw: str | None = Field(description="Revenue year as printed, e.g. '2023-24'.")
    fasli_year_raw: str | None = Field(description="Fasli year, if the header gives one.")


class LlmParcel(BaseModel):
    """One parcel's Record of Rights, as read off the page."""

    model_config = _STRICT

    jurisdiction: LlmJurisdiction
    khata_number: str | None = Field(description="Khata / Khewat number.")
    khatauni_number: str | None
    khasra_numbers: list[str] = Field(description="Khasra / field-plot numbers. Empty list if none.")
    survey_number: str | None = Field(description="Survey / Gat number.")
    sub_survey_number: str | None = Field(description="Hissa number of the survey number itself.")

    total_area: LlmArea | None = Field(description="The parcel total exactly as printed. Never compute it.")
    classified_areas: list[LlmClassifiedArea] = Field(
        description="Breakup by classification (irrigated / unirrigated / pot-kharaba / ...)."
    )
    sub_divisions: list[LlmSubDivision] = Field(description="Hissa rows. Empty list if the parcel is undivided.")

    owners: list[LlmOwner]
    mutations: list[LlmMutation]
    encumbrances: list[LlmEncumbrance]
    crops: list[LlmCrop]

    assessment_amount: str | None = Field(description="Total land revenue / akarni, in rupees.")
    water_rate: str | None = Field(description="Water cess / jud, in rupees.")
    other_rights_remarks: str | None = Field(description="The 'other rights' column, verbatim.")
    source_page_indices: list[int] = Field(description="Zero-based page indices this parcel was read from.")


class FieldConfidence(BaseModel):
    """Per-field certainty, addressed by path into the parcel."""

    model_config = _STRICT

    field_path: str = Field(
        description="Path into this extraction, e.g. 'parcels[0].total_area' or "
        "'parcels[0].owners[1].name.raw_name'."
    )
    confidence: float = Field(ge=0.0, le=1.0, description="0.0-1.0 certainty in the transcribed value.")
    reason: str | None = Field(description="Why confidence is below 1.0, when it is.")


class UnreadableRegion(BaseModel):
    """A region that could not be transcribed. Reporting it beats guessing at it."""

    model_config = _STRICT

    page_index: int
    description: str = Field(description="What is there and why it is unreadable, e.g. 'torn corner'.")
    approximate_field: str | None = Field(description="Which record field it likely holds, if inferable.")


class LlmExtraction(BaseModel):
    """The complete structured output of one Vision LLM extraction call."""

    model_config = _STRICT

    detected_record_format: Literal[
        "jamabandi", "satbara_7_12", "khasra_girdawari", "ror_generic", "unknown"
    ] = Field(description="Which template this document follows.")

    detected_scripts: list[str] = Field(
        description="Unicode script names present, e.g. ['Devanagari', 'Latin']."
    )

    parcels: list[LlmParcel] = Field(
        description="One entry per parcel/khata on the document. Most extracts hold exactly one."
    )

    field_confidences: list[FieldConfidence] = Field(
        description="Confidence for every field you were less than fully certain about. "
        "Omit fields you read cleanly -- they are assumed high-confidence."
    )

    unreadable_regions: list[UnreadableRegion]

    overall_confidence: float = Field(
        ge=0.0, le=1.0, description="Your overall certainty in this extraction, 0.0-1.0."
    )

    notes: str | None = Field(
        description="Anything a human reviewer should know: unusual layout, contradictions "
        "visible on the page, columns you could not map."
    )
