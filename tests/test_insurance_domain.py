"""Tests for the insurance domain knowledge module.

Covers:
  - Insurance type classification from real tender documents
  - OKPD2 code lookups
  - Regulatory reference lookups
  - Insurance tender detection
  - Keyword detection and coverage for all 8 insurance types
"""

import os
import pathlib

import pytest

# Import after conftest env-var setup
from shared.insurance_domain import (
    CANONICAL_INSURANCE_TYPES,
    INSURANCE_DETECTION_KEYWORDS,
    INSURANCE_TYPES,
    OKPD2_CODES,
    REGULATORY_REFERENCES,
    classify_insurance_type,
    classify_tender,
    get_insurance_type_info,
    get_okpd2_description,
    get_regulatory_reference,
    is_insurance_tender,
)
from tests.fixtures.expected_results import (
    EXPECTED_RESULTS,
    TENDER_TYPE_MAP,
    TESTED_INSURANCE_TYPES,
)

# ── Paths ──────────────────────────────────────────────────────────────

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures" / "tenders"


def _read_tender(filename: str) -> str:
    """Read a tender document from fixtures."""
    path = FIXTURES_DIR / filename
    assert path.exists(), f"Tender fixture not found: {path}"
    return path.read_text(encoding="utf-8")


# ── Parametrized classification tests ──────────────────────────────────

_TENDER_FILES = sorted(EXPECTED_RESULTS.keys())


@pytest.mark.parametrize("filename", _TENDER_FILES, ids=_TENDER_FILES)
def test_insurance_type_classification(filename: str):
    """Verify that each tender is classified to the correct insurance type."""
    text = _read_tender(filename)
    expected_type = TENDER_TYPE_MAP[filename]

    insurance_type, confidence = classify_insurance_type(text)

    assert insurance_type == expected_type, (
        f"{filename}: expected type '{expected_type}', got '{insurance_type}' "
        f"(confidence={confidence:.2f})"
    )
    assert confidence > 0.0, f"{filename}: confidence should be > 0"


@pytest.mark.parametrize("filename", _TENDER_FILES, ids=_TENDER_FILES)
def test_is_insurance_tender(filename: str):
    """All tender fixtures should be detected as insurance tenders."""
    text = _read_tender(filename)
    assert is_insurance_tender(text), f"{filename}: should be detected as insurance tender"


@pytest.mark.parametrize("filename", _TENDER_FILES, ids=_TENDER_FILES)
def test_classify_tender_returns_full_result(filename: str):
    """classify_tender() should return a complete result dict."""
    text = _read_tender(filename)
    result = classify_tender(text)

    assert isinstance(result, dict)
    assert "insurance_type" in result
    assert "confidence" in result
    assert "is_insurance" in result
    assert "detected_keywords" in result
    assert result["insurance_type"] != "unknown", f"{filename}: type should not be unknown"
    assert result["is_insurance"] is True


# ── Coverage: all 8 insurance types are testable ──────────────────────

def test_all_canonical_types_covered():
    """Verify we have test tenders covering all 8 canonical insurance types."""
    # ОСАГО, КАСКО, ДМС, Имущество, Ответственность, НС, Грузы, СМР
    expected_canonical = {"ОСАГО", "КАСКО", "ДМС", "Имущество", "Ответственность", "НС", "Грузы", "СМР"}
    actual = set(TESTED_INSURANCE_TYPES)
    missing = expected_canonical - actual
    assert not missing, f"Missing test coverage for insurance types: {missing}"


def test_17_tender_fixtures_exist():
    """Verify all 17 tender fixture files exist."""
    assert len(_TENDER_FILES) == 17, f"Expected 17 tenders, got {len(_TENDER_FILES)}"
    for fname in _TENDER_FILES:
        path = FIXTURES_DIR / fname
        assert path.exists(), f"Missing fixture: {fname}"
        content = path.read_text(encoding="utf-8")
        assert len(content) > 100, f"Fixture {fname} seems too short ({len(content)} chars)"


# ── Insurance type metadata tests ─────────────────────────────────────

def test_insurance_types_have_required_fields():
    """Every InsuranceTypeInfo should have keywords and OKPD2 codes."""
    for type_id, info in INSURANCE_TYPES.items():
        assert info.type_id == type_id
        assert len(info.full_name_ru) > 0, f"{type_id}: missing full_name_ru"
        assert len(info.keywords) > 0, f"{type_id}: missing keywords"
        assert len(info.okpd2_codes) > 0, f"{type_id}: missing OKPD2 codes"


def test_canonical_types_in_insurance_types():
    """All canonical types should have entries in INSURANCE_TYPES."""
    for t in CANONICAL_INSURANCE_TYPES:
        assert t in INSURANCE_TYPES, f"Missing INSURANCE_TYPES entry for '{t}'"


# ── OKPD2 tests ───────────────────────────────────────────────────────

def test_okpd2_osago():
    assert get_okpd2_description("65.12.21.000") == "ОСАГО"


def test_okpd2_kasko():
    assert get_okpd2_description("65.12.29.000") == "КАСКО"


def test_okpd2_medical():
    assert get_okpd2_description("65.12.12.000") is not None


def test_okpd2_cargo():
    assert get_okpd2_description("65.12.36.000") is not None


def test_okpd2_life():
    assert get_okpd2_description("65.11") is not None


def test_okpd2_reinsurance():
    assert get_okpd2_description("65.20") is not None


def test_okpd2_unknown_returns_none():
    assert get_okpd2_description("99.99.99") is None


# ── Regulatory reference tests ────────────────────────────────────────

@pytest.mark.parametrize("law_id", ["44-ФЗ", "223-ФЗ", "40-ФЗ", "225-ФЗ", "4015-1"])
def test_regulatory_reference_lookup(law_id: str):
    ref = get_regulatory_reference(law_id)
    assert ref is not None, f"Missing regulatory reference for {law_id}"
    assert len(ref) > 10


def test_regulatory_reference_unknown():
    assert get_regulatory_reference("999-ФЗ") is None


# ── get_insurance_type_info tests ─────────────────────────────────────

def test_get_type_info_osago():
    info = get_insurance_type_info("ОСАГО")
    assert info is not None
    assert info.is_mandatory is True
    assert "65.12.21.000" in info.okpd2_codes


def test_get_type_info_kasko():
    info = get_insurance_type_info("КАСКО")
    assert info is not None
    assert info.is_mandatory is False


def test_get_type_info_unknown():
    assert get_insurance_type_info("UNKNOWN_TYPE") is None


# ── Edge case classification tests ────────────────────────────────────

def test_classify_empty_text():
    t, c = classify_insurance_type("")
    assert t == "unknown"
    assert c == 0.0


def test_classify_non_insurance_text():
    text = "Закупка канцелярских товаров для муниципального учреждения"
    t, c = classify_insurance_type(text)
    # Non-insurance text may still match weakly; the important thing
    # is that is_insurance_tender returns False.
    assert not is_insurance_tender(text)


def test_classify_pure_osago_text():
    text = "ОСАГО страхование автогражданской ответственности 40-ФЗ полис"
    t, c = classify_insurance_type(text)
    assert t == "ОСАГО"
    assert c > 0.5


def test_classify_pure_dms_text():
    text = "ДМС добровольное медицинское страхование сотрудников амбулаторно-поликлиническое"
    t, c = classify_insurance_type(text)
    assert t == "ДМС"
    assert c > 0.5


def test_classify_pure_smr_text():
    text = "Страхование строительно-монтажных рисков СМР капитальный ремонт МКД"
    t, c = classify_insurance_type(text)
    assert t == "СМР"
    assert c > 0.3


def test_classify_pure_cargo_text():
    text = "Страхование грузов при перевозке генеральный договор мультимодальные перевозки"
    t, c = classify_insurance_type(text)
    assert t == "Грузы"
    assert c > 0.3


def test_classify_pure_liability_text():
    text = "Обязательное страхование ответственности владельца опасного производственного объекта ОПО 225-ФЗ"
    t, c = classify_insurance_type(text)
    assert t == "Ответственность"
    assert c > 0.3


def test_classify_pure_property_text():
    text = "Страхование имущества юридических лиц от пожара all risks восстановительная стоимость"
    t, c = classify_insurance_type(text)
    assert t == "Имущество"
    assert c > 0.3


def test_classify_pure_ns_text():
    text = "Страхование от несчастных случаев и болезней работников НС временная нетрудоспособность"
    t, c = classify_insurance_type(text)
    assert t == "НС"
    assert c > 0.3


# ── Insurance detection keyword set ───────────────────────────────────

def test_detection_keywords_not_empty():
    assert len(INSURANCE_DETECTION_KEYWORDS) > 20


def test_key_abbreviations_in_keywords():
    for abbr in ["осаго", "каско", "дмс", "омс", "страхование"]:
        assert abbr in INSURANCE_DETECTION_KEYWORDS, f"Missing keyword: {abbr}"


# ── is_insurance_tender edge cases ────────────────────────────────────

def test_not_insurance_without_procurement():
    """Insurance keywords alone (without procurement context) → False."""
    text = "Добровольное медицинское страхование ДМС полис"
    assert not is_insurance_tender(text)


def test_insurance_with_procurement():
    """Insurance + procurement keywords → True."""
    text = "Добровольное медицинское страхование ДМС тендер 223-ФЗ НМЦК"
    assert is_insurance_tender(text)
