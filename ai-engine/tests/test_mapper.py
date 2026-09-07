"""LLM wire-format -> domain-model mapping, including graceful degradation."""

from __future__ import annotations

from decimal import Decimal

from adhikar.llm.mapper import index_field_confidences, map_extraction
from adhikar.schemas.llm_contract import LlmExtraction

_BASE_AREA = {
    "raw_text": None,
    "hectare": None,
    "are": None,
    "sq_metre": None,
    "acre": None,
    "guntha": None,
    "kanal": None,
    "marla": None,
    "bigha": None,
    "biswa": None,
    "biswansi": None,
}


def _area(raw_text: str, hectare: str, are: str, sq_metre: str) -> dict:
    return {**_BASE_AREA, "raw_text": raw_text, "hectare": hectare, "are": are, "sq_metre": sq_metre}


def _person(name: str) -> dict:
    return {"raw_name": name, "transliterated": None, "relation_raw": None, "relation_name": None}


def _make_extraction(
    *,
    owners: list[dict] | None = None,
    mutations: list[dict] | None = None,
    field_confidences: list[dict] | None = None,
) -> LlmExtraction:
    data = {
        "detected_record_format": "satbara_7_12",
        "detected_scripts": ["Devanagari"],
        "parcels": [
            {
                "jurisdiction": {
                    "state": "Maharashtra",
                    "district": "Pune",
                    "tehsil": "Haveli",
                    "village": "Kondhwa",
                    "hadbast_number": None,
                    "revenue_year_raw": None,
                    "fasli_year_raw": None,
                },
                "khata_number": "45",
                "khatauni_number": None,
                "khasra_numbers": [],
                "survey_number": "142",
                "sub_survey_number": None,
                "total_area": _area("0-80-05", "0", "80", "05"),
                "classified_areas": [],
                "sub_divisions": [],
                "owners": owners or [],
                "mutations": mutations or [],
                "encumbrances": [],
                "crops": [],
                "assessment_amount": None,
                "water_rate": None,
                "other_rights_remarks": None,
                "source_page_indices": [0],
            }
        ],
        "field_confidences": field_confidences or [],
        "unreadable_regions": [],
        "overall_confidence": 0.9,
        "notes": None,
    }
    return LlmExtraction.model_validate(data)


def test_basic_area_mapping() -> None:
    extraction = _make_extraction()
    result = map_extraction(extraction)
    assert len(result.parcels) == 1
    assert result.parcels[0].total_area.sq_metre == Decimal("8005.0000")
    assert result.parcels[0].survey_number == "142"


def test_owner_with_empty_name_is_dropped_not_fatal() -> None:
    extraction = _make_extraction(
        owners=[
            {
                "serial_number": "1",
                "name": _person("Ram Singh"),
                "tenure_raw": "मालिक",
                "share": None,
                "khata_number": None,
                "remarks": None,
            },
            {
                "serial_number": None,
                "name": _person(""),
                "tenure_raw": None,
                "share": None,
                "khata_number": None,
                "remarks": None,
            },
        ]
    )
    result = map_extraction(extraction)
    assert len(result.parcels[0].owners) == 1
    assert result.parcels[0].owners[0].display_name == "Ram Singh"
    assert any("skipped" in w for w in result.warnings)


def test_invalid_mutation_dropped_others_kept() -> None:
    extraction = _make_extraction(
        mutations=[
            {
                "mutation_number": "1",
                "type_raw": "खरेदी",
                "status_raw": "मंजूर",
                "entry_date_raw": "01/01/2019",
                "order_date_raw": "01/01/2018",  # before entry_date -> invalid, dropped
                "from_parties": [],
                "to_parties": [],
                "area_transacted": None,
                "consideration_amount": None,
                "document_reference": None,
                "raw_text": "bad",
            },
            {
                "mutation_number": "2",
                "type_raw": "खरेदी",
                "status_raw": "मंजूर",
                "entry_date_raw": "01/01/2019",
                "order_date_raw": "01/06/2019",
                "from_parties": [],
                "to_parties": [],
                "area_transacted": None,
                "consideration_amount": None,
                "document_reference": None,
                "raw_text": "good",
            },
        ]
    )
    result = map_extraction(extraction)
    assert len(result.parcels[0].mutations) == 1
    assert result.parcels[0].mutations[0].raw_text == "good"
    assert any("dropped" in w for w in result.warnings)


def test_field_confidence_indexing_threads_through() -> None:
    extraction = _make_extraction(
        field_confidences=[{"field_path": "$.parcels[0].total_area", "confidence": 0.42, "reason": "faint"}]
    )
    conf = index_field_confidences(extraction)
    result = map_extraction(extraction, llm_confidence_by_path=conf)
    prov = result.provenance["$.parcels[0].total_area"]
    assert prov.confidence == 0.42
    assert prov.reason == "faint"


def test_unresolvable_share_is_none_not_an_exception() -> None:
    extraction = _make_extraction(
        owners=[
            {
                "serial_number": "1",
                "name": _person("A"),
                "tenure_raw": None,
                "share": {"raw_text": "abc/def", "numerator": None, "denominator": None},
                "khata_number": None,
                "remarks": None,
            }
        ]
    )
    result = map_extraction(extraction)
    assert len(result.parcels) == 1
    assert result.parcels[0].owners[0].share is None
    assert any("could not parse" in w for w in result.warnings)
