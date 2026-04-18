"""
tests/test_da_schemas.py
Тесты схем Pydantic для DA-агентов (агенты 4-6):
- LeasingParseResult
- OsagoParseResult
- TransportParseResult
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.schemas import (
    LeasingAddressSchema,
    LeasingBaseSchema,
    LeasingParseResult,
    OsagoParseResult,
    TransportParseResult,
)


# ---------------------------------------------------------------------------
# LeasingAddressSchema
# ---------------------------------------------------------------------------

def test_leasing_address_max_length_enforced():
    # Pydantic v2 raises ValidationError on construction when max_length exceeded
    with pytest.raises(ValidationError):
        LeasingAddressSchema(city="x" * 300, street="y" * 300, house="h" * 50)
    with pytest.raises(ValidationError):
        LeasingAddressSchema.model_validate({"house": "x" * 25})


def test_leasing_address_defaults_none():
    addr = LeasingAddressSchema()
    assert addr.country is None
    assert addr.city is None
    assert addr.house is None


# ---------------------------------------------------------------------------
# LeasingBaseSchema
# ---------------------------------------------------------------------------

def test_leasing_base_currency_upper():
    base = LeasingBaseSchema(currency="eur")
    assert base.currency == "EUR"


def test_leasing_base_currency_none():
    base = LeasingBaseSchema(currency=None)
    assert base.currency is None


@pytest.mark.parametrize("currency", ["RUR", "USD", "EUR", None])
def test_leasing_base_valid_currencies(currency):
    base = LeasingBaseSchema(currency=currency)
    assert base.currency == (currency.upper() if currency else None)


def test_leasing_base_policy_number_max_length():
    with pytest.raises(ValidationError):
        LeasingBaseSchema.model_validate({"policy_number": "x" * 260})


# ---------------------------------------------------------------------------
# LeasingParseResult
# ---------------------------------------------------------------------------

def test_leasing_parse_result_empty_lists():
    r = LeasingParseResult()
    assert r.roles == []
    assert r.insurance_objects == []
    assert r.payments == []
    assert r.risks == []
    assert r.agents == []
    assert r.parse_errors == []


def test_leasing_parse_result_validation_status_default():
    r = LeasingParseResult()
    assert r.validation_status == "pending"


def test_leasing_parse_result_full_round_trip():
    data = {
        "file_name": "leasing.docx",
        "base": {"policy_number": "POL-999", "currency": "rur"},
        "roles": [{"role": "лизингодатель", "organization_name": "ООО А"}],
        "risks": [{"short_name": "Пожар", "classisn": 1, "ruleisn": 2}],
    }
    r = LeasingParseResult.model_validate(data)
    dumped = r.model_dump(mode="json")
    assert dumped["file_name"] == "leasing.docx"
    assert dumped["base"]["currency"] == "RUR"
    assert dumped["roles"][0]["role"] == "лизингодатель"


# ---------------------------------------------------------------------------
# OsagoParseResult
# ---------------------------------------------------------------------------

def test_osago_parse_result_defaults():
    r = OsagoParseResult()
    assert r.file_name == ""
    assert r.vehicle_brand is None
    assert r.year is None
    assert r.parse_errors == []


@pytest.mark.parametrize("year", [1990, 2000, 2024])
def test_osago_parse_result_year_valid(year):
    r = OsagoParseResult(year=year)
    assert r.year == year


def test_osago_parse_result_full():
    data = {
        "file_name": "osago.pdf",
        "vehicle_brand": "ТОЙОТА",
        "vehicle_number": "А123БВ199",
        "vin": "XTA123456789",
        "power_hp": 150.0,
        "max_mass": None,
        "year": 2022,
    }
    r = OsagoParseResult.model_validate(data)
    assert r.vehicle_brand == "ТОЙОТА"
    assert r.power_hp == 150.0
    assert r.max_mass is None


# ---------------------------------------------------------------------------
# TransportParseResult
# ---------------------------------------------------------------------------

def test_transport_parse_result_defaults():
    r = TransportParseResult()
    assert r.file_name == ""
    assert r.cargo_name is None
    assert r.parse_errors == []


def test_transport_parse_result_full():
    data = {
        "file_name": "transport.pdf",
        "cargo_name": "Оборудование",
        "cargo_weight": 10.5,
        "cargo_value": 5000000.0,
        "currency": "RUR",
        "departure_point": "Москва",
        "destination_point": "Санкт-Петербург",
        "insurance_sum": 5000000.0,
        "premium": 25000.0,
    }
    r = TransportParseResult.model_validate(data)
    assert r.cargo_name == "Оборудование"
    assert r.cargo_weight == 10.5
    assert r.premium == 25000.0
