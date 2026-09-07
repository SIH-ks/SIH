"""Controlled vocabularies for Indian Records-of-Rights (RoR).

Every enum here is deliberately *closed*. Land-record vocabulary varies enormously
between states, so the strategy is: keep a small, canonical, machine-reasonable set
of members, and push the state-specific surface forms into :data:`VERNACULAR_ALIASES`,
which the normaliser resolves against.

A term that cannot be resolved never silently becomes a neighbouring member -- it
becomes ``UNKNOWN`` and raises a validation issue, so a human reviewer sees it.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "VERNACULAR_ALIASES",
    "CultivabilityClass",
    "EncumbranceStatus",
    "EncumbranceType",
    "ExtractorKind",
    "IrrigationSource",
    "LandClassification",
    "MutationStatus",
    "MutationType",
    "RecordFormat",
    "RelationType",
    "TenureType",
    "cultivability_of",
]


class RecordFormat(StrEnum):
    """The document template the scan follows.

    The format drives table-geometry expectations and the extraction prompt, so it
    is detected once up front rather than inferred field-by-field.
    """

    JAMABANDI = "jamabandi"
    """Record of Rights, Punjab/Haryana/HP/Rajasthan lineage. Khewat/Khatauni columns."""

    SATBARA = "satbara_7_12"
    """Maharashtra 7/12 extract: Village Form VII (rights) + Form XII (crops)."""

    KHASRA_GIRDAWARI = "khasra_girdawari"
    """Seasonal crop-inspection register keyed by Khasra number."""

    ROR_GENERIC = "ror_generic"
    """Any other Record-of-Rights layout; generic table parsing applies."""

    UNKNOWN = "unknown"


class LandClassification(StrEnum):
    """Revenue classification of a parcel or sub-division."""

    IRRIGATED = "irrigated"
    """Chahi / Nahri / Bagayat -- well, canal or otherwise assured irrigation."""

    UNIRRIGATED = "unirrigated"
    """Barani / Jirayat -- rain-fed."""

    CULTIVABLE_WASTE = "cultivable_waste"
    """Banjar Qadim / Banjar Jadid -- fallow but arable."""

    NON_CULTIVABLE = "non_cultivable"
    """Gair Mumkin / Pot-Kharaba -- rock, path, structure, watercourse."""

    FOREST = "forest"

    RESIDENTIAL = "residential"
    """Abadi / Gaothan -- inhabited site."""

    UNKNOWN = "unknown"


class CultivabilityClass(StrEnum):
    """The coarse cultivable/non-cultivable split the problem statement asks for."""

    CULTIVABLE = "cultivable"
    NON_CULTIVABLE = "non_cultivable"
    UNKNOWN = "unknown"


_CULTIVABILITY_MAP: dict[LandClassification, CultivabilityClass] = {
    LandClassification.IRRIGATED: CultivabilityClass.CULTIVABLE,
    LandClassification.UNIRRIGATED: CultivabilityClass.CULTIVABLE,
    LandClassification.CULTIVABLE_WASTE: CultivabilityClass.CULTIVABLE,
    LandClassification.NON_CULTIVABLE: CultivabilityClass.NON_CULTIVABLE,
    LandClassification.FOREST: CultivabilityClass.NON_CULTIVABLE,
    LandClassification.RESIDENTIAL: CultivabilityClass.NON_CULTIVABLE,
    LandClassification.UNKNOWN: CultivabilityClass.UNKNOWN,
}


def cultivability_of(classification: LandClassification) -> CultivabilityClass:
    """Collapse a revenue classification onto the cultivable/non-cultivable axis.

    ``CULTIVABLE_WASTE`` maps to *cultivable*: Banjar land is arable but currently
    fallow, and revenue law counts it in the culturable area. Only Gair Mumkin /
    Pot-Kharaba is genuinely non-cultivable.
    """
    return _CULTIVABILITY_MAP.get(classification, CultivabilityClass.UNKNOWN)


class TenureType(StrEnum):
    """The capacity in which a person is recorded against the parcel."""

    OWNER = "owner"
    """Malik / Bhumiswami / Bhogvatadar."""

    OCCUPANT_CLASS_I = "occupant_class_i"
    """Maharashtra Bhogvatadar Varg-1: freely transferable occupancy."""

    OCCUPANT_CLASS_II = "occupant_class_ii"
    """Maharashtra Bhogvatadar Varg-2: transfer restricted, Collector sanction needed."""

    TENANT = "tenant"
    """Gair Maurusi / Kabjedar / Kul -- cultivating tenant."""

    GOVERNMENT_LESSEE = "government_lessee"
    MORTGAGEE = "mortgagee"
    TRUST = "trust"

    GOVERNMENT = "government"
    """Sarkar / Gram Panchayat vested land."""

    UNKNOWN = "unknown"


class RelationType(StrEnum):
    """Relational qualifier printed beside an owner name."""

    SON_OF = "son_of"
    DAUGHTER_OF = "daughter_of"
    WIFE_OF = "wife_of"
    WIDOW_OF = "widow_of"
    HEIR_OF = "heir_of"
    GUARDIAN_OF = "guardian_of"
    UNKNOWN = "unknown"


class MutationType(StrEnum):
    """Cause of a change in the record of rights (Intekal / Pheri / Ferfar)."""

    SALE = "sale"
    INHERITANCE = "inheritance"
    GIFT = "gift"
    PARTITION = "partition"
    MORTGAGE = "mortgage"
    MORTGAGE_REDEMPTION = "mortgage_redemption"
    LEASE = "lease"
    EXCHANGE = "exchange"
    COURT_DECREE = "court_decree"

    ACQUISITION = "acquisition"
    """Compulsory acquisition by the State."""

    CORRECTION = "correction"
    """Clerical rectification; must not change total area."""

    WILL = "will"
    OTHER = "other"
    UNKNOWN = "unknown"


class MutationStatus(StrEnum):
    PENDING = "pending"
    SANCTIONED = "sanctioned"
    REJECTED = "rejected"
    DISPUTED = "disputed"
    UNKNOWN = "unknown"


class EncumbranceType(StrEnum):
    MORTGAGE = "mortgage"

    BANK_CHARGE = "bank_charge"
    """Crop / KCC loan charge noted in the 'other rights' column."""

    COURT_INJUNCTION = "court_injunction"
    GOVERNMENT_ACQUISITION = "government_acquisition"
    TENANCY_RIGHT = "tenancy_right"
    LIS_PENDENS = "lis_pendens"
    ATTACHMENT = "attachment"
    OTHER = "other"
    UNKNOWN = "unknown"


class EncumbranceStatus(StrEnum):
    ACTIVE = "active"
    DISCHARGED = "discharged"
    UNKNOWN = "unknown"


class IrrigationSource(StrEnum):
    CANAL = "canal"
    WELL = "well"
    TUBEWELL = "tubewell"
    TANK = "tank"
    RAIN_FED = "rain_fed"
    LIFT = "lift"
    OTHER = "other"
    UNKNOWN = "unknown"


class ExtractorKind(StrEnum):
    """Which stage produced a value. Carried in provenance; drives trust weighting."""

    OCR_EASYOCR = "ocr_easyocr"
    OCR_TESSERACT = "ocr_tesseract"
    OCR_ENSEMBLE = "ocr_ensemble"
    VISION_LLM = "vision_llm"

    RULE_DERIVED = "rule_derived"
    """Computed by the engine (e.g. an area summed from sub-divisions)."""

    HUMAN_REVIEW = "human_review"
    """Corrected in the reviewer console. Always outranks every machine source."""


# ======================================================================================
# Vernacular surface forms
# ======================================================================================
# Keys are lower-cased, whitespace-collapsed strings as they appear on scans -- both
# the Devanagari originals and the romanisations clerks use interchangeably. The
# normaliser (adhikar.normalize.vocab) matches exactly first, then by fuzzy ratio.
#
# Devanagari literals are written as escapes so the file stays ASCII-safe in transit;
# the trailing comment shows the rendered form.

VERNACULAR_ALIASES: dict[str, LandClassification | TenureType | MutationType] = {
    # -- LandClassification: irrigated ---------------------------------------------
    "chahi": LandClassification.IRRIGATED,
    "चाही": LandClassification.IRRIGATED,  # chahi
    "nahri": LandClassification.IRRIGATED,
    "नहरी": LandClassification.IRRIGATED,  # nahri
    "bagayat": LandClassification.IRRIGATED,
    "बागायत": LandClassification.IRRIGATED,  # bagayat
    "irrigated": LandClassification.IRRIGATED,
    # -- LandClassification: unirrigated --------------------------------------------
    "barani": LandClassification.UNIRRIGATED,
    "बरानी": LandClassification.UNIRRIGATED,  # barani
    "jirayat": LandClassification.UNIRRIGATED,
    "जिरायत": LandClassification.UNIRRIGATED,  # jirayat
    "unirrigated": LandClassification.UNIRRIGATED,
    "dry": LandClassification.UNIRRIGATED,
    # -- LandClassification: cultivable waste ----------------------------------------
    "banjar": LandClassification.CULTIVABLE_WASTE,
    "banjar qadim": LandClassification.CULTIVABLE_WASTE,
    "banjar jadid": LandClassification.CULTIVABLE_WASTE,
    "बंजर": LandClassification.CULTIVABLE_WASTE,  # banjar
    "fallow": LandClassification.CULTIVABLE_WASTE,
    # -- LandClassification: non-cultivable -------------------------------------------
    "gair mumkin": LandClassification.NON_CULTIVABLE,
    "gairmumkin": LandClassification.NON_CULTIVABLE,
    "गैर मुमकिन": LandClassification.NON_CULTIVABLE,
    "pot kharaba": LandClassification.NON_CULTIVABLE,
    "potkharab": LandClassification.NON_CULTIVABLE,
    "पोट खराब": LandClassification.NON_CULTIVABLE,  # pot kharab
    "non cultivable": LandClassification.NON_CULTIVABLE,
    # -- LandClassification: other ------------------------------------------------------
    "abadi": LandClassification.RESIDENTIAL,
    "gaothan": LandClassification.RESIDENTIAL,
    "गावठाण": LandClassification.RESIDENTIAL,  # gaothan
    "jungle": LandClassification.FOREST,
    "van": LandClassification.FOREST,
    # -- TenureType -----------------------------------------------------------------------
    "malik": TenureType.OWNER,
    "मालिक": TenureType.OWNER,  # malik
    "bhumiswami": TenureType.OWNER,
    "bhogvatadar varg 1": TenureType.OCCUPANT_CLASS_I,
    "bhogwatdar varg-1": TenureType.OCCUPANT_CLASS_I,
    "भोगवटादार वर्ग-1": TenureType.OCCUPANT_CLASS_I,
    "भोगवटादार वर्ग-१": TenureType.OCCUPANT_CLASS_I,
    "bhogvatadar varg 2": TenureType.OCCUPANT_CLASS_II,
    "bhogwatdar varg-2": TenureType.OCCUPANT_CLASS_II,
    "भोगवटादार वर्ग-2": TenureType.OCCUPANT_CLASS_II,
    "भोगवटादार वर्ग-२": TenureType.OCCUPANT_CLASS_II,
    "भोगवटादार": TenureType.OWNER,
    "gair maurusi": TenureType.TENANT,
    "kabjedar": TenureType.TENANT,
    "kul": TenureType.TENANT,
    "कूळ": TenureType.TENANT,  # kul
    "sarkar": TenureType.GOVERNMENT,
    "सरकार": TenureType.GOVERNMENT,  # sarkar
    # -- MutationType ------------------------------------------------------------------------
    "bai": MutationType.SALE,
    "kharedi": MutationType.SALE,
    "खरेदी": MutationType.SALE,  # kharedi
    "sale deed": MutationType.SALE,
    "varsa": MutationType.INHERITANCE,
    "वारस": MutationType.INHERITANCE,  # varas
    "virasat": MutationType.INHERITANCE,
    "hiba": MutationType.GIFT,
    "bakshish": MutationType.GIFT,
    "taqsim": MutationType.PARTITION,
    "vatap": MutationType.PARTITION,
    "वाटप": MutationType.PARTITION,  # vatap
    "rehan": MutationType.MORTGAGE,
    "gahan": MutationType.MORTGAGE,
    "fak": MutationType.MORTGAGE_REDEMPTION,
    "bhusampadan": MutationType.ACQUISITION,
}
