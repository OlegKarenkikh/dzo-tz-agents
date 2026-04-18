"""
tests/test_agent6_transportation.py
Тесты агента agent6_transportation_parser:
- вспомогательные функции (_parse_float, _validate_weight, _format_route, _resolve_type, _strip_none)
- инструменты (extract_transport_base, extract_transport_route, extract_transport_additional,
               resolve_transport_type, validate_transport_result, fix_transport_field)
- схема TransportParseResult
- runner parse_steps / build_chat_input
"""
from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock

import pytest

# Stub langgraph.prebuilt
if "langgraph.prebuilt" not in sys.modules:
    _fake = types.ModuleType("langgraph.prebuilt")
    _fake.create_react_agent = MagicMock(return_value=MagicMock())
    sys.modules["langgraph.prebuilt"] = _fake

from agent6_transportation_parser.tools import (
    _parse_float,
    _validate_weight,
    _format_route,
    _resolve_type,
    _strip_none,
    TRANSPORT_TYPES,
    extract_transport_base,
    extract_transport_route,
    extract_transport_additional,
    resolve_transport_type,
    validate_transport_result,
    fix_transport_field,
)
from shared.schemas import TransportParseResult


# ===========================================================================
# _parse_float
# ===========================================================================

@pytest.mark.parametrize("value, expected", [
    (None, None),
    (0, 0.0),
    (3.14, 3.14),
    ("100", 100.0),
    ("1 500,50", 1500.5),
    ("10%", 10.0),
    ("", None),
    ("abc", None),
    ({}, None),
])
def test_parse_float(value, expected):
    assert _parse_float(value) == expected


# ===========================================================================
# _validate_weight
# ===========================================================================

@pytest.mark.parametrize("raw, expected", [
    (None, None),
    (500.0, 500.0),
    (10, 10.0),
    ("500 кг", 500.0),
    ("10 тонн", 10000.0),
    ("5т", 5000.0),
    ("2.5 тонны", 2500.0),
    ("", None),
    ("abc", None),
])
def test_validate_weight(raw, expected):
    assert _validate_weight(raw) == expected


# ===========================================================================
# _format_route
# ===========================================================================

@pytest.mark.parametrize("departure, destination, via, expected", [
    ("Москва", "Питер", None, "Москва → Питер"),
    ("Москва", "Питер", [], "Москва → Питер"),
    ("Москва", "Владивосток", ["Новосибирск"], "Москва → Новосибирск → Владивосток"),
    ("А", "Б", ["В", "Г"], "А → В → Г → Б"),
    ("", "Б", None, "Б"),
])
def test_format_route(departure, destination, via, expected):
    assert _format_route(departure, destination, via) == expected


# ===========================================================================
# _resolve_type
# ===========================================================================

@pytest.mark.parametrize("raw, expected", [
    ("Автомобильный транспорт", "Автомобильный транспорт"),
    ("автомобильный транспорт", "Автомобильный транспорт"),
    ("АВИАЦИОННЫЙ ТРАНСПОРТ", "Авиационный транспорт"),
    ("Морской транспорт", "Морской транспорт"),
    ("Неизвестный вид", None),
    ("", None),
])
def test_resolve_type(raw, expected):
    assert _resolve_type(raw, TRANSPORT_TYPES) == expected


# ===========================================================================
# _strip_none
# ===========================================================================

def test_strip_none_removes_empty():
    result = _strip_none({"a": None, "b": "", "c": [], "d": {}, "e": "ok"})
    assert result == {"e": "ok"}


def test_strip_none_nested():
    result = _strip_none({"outer": {"inner": None, "val": 1}})
    assert result == {"outer": {"val": 1}}


def test_strip_none_list_cleans_nulls():
    result = _strip_none({"items": [None, "", {"a": None}, {"b": 1}]})
    assert result == {"items": [{"b": 1}]}


# ===========================================================================
# extract_transport_base
# ===========================================================================

def test_extract_transport_base_returns_json():
    raw = extract_transport_base.invoke({"document_text": "Тестовый документ"})
    data = json.loads(raw)
    assert "instruction" in data
    assert "extracted" in data


def test_extract_transport_base_has_required_keys():
    raw = extract_transport_base.invoke({"document_text": "doc"})
    data = json.loads(raw)
    for key in ("policy_number", "insurer", "cargo_name", "insurance_sum", "premium",
                "currency", "date_start", "date_end"):
        assert key in data["extracted"]


def test_extract_transport_base_all_null_initially():
    raw = extract_transport_base.invoke({"document_text": "doc"})
    data = json.loads(raw)
    for v in data["extracted"].values():
        assert v is None


# ===========================================================================
# extract_transport_route
# ===========================================================================

def test_extract_transport_route_returns_json():
    raw = extract_transport_route.invoke({"document_text": "doc"})
    data = json.loads(raw)
    assert "extracted" in data
    assert "instruction" in data


def test_extract_transport_route_has_route_fields():
    raw = extract_transport_route.invoke({"document_text": "doc"})
    data = json.loads(raw)
    for key in ("route_specified", "departure", "destination", "via", "route_string"):
        assert key in data["extracted"]


def test_extract_transport_route_default_not_specified():
    raw = extract_transport_route.invoke({"document_text": "doc"})
    data = json.loads(raw)
    assert data["extracted"]["route_specified"] is False


# ===========================================================================
# extract_transport_additional
# ===========================================================================

def test_extract_transport_additional_returns_json():
    raw = extract_transport_additional.invoke({"document_text": "doc"})
    data = json.loads(raw)
    assert "extracted" in data


def test_extract_transport_additional_has_required_keys():
    raw = extract_transport_additional.invoke({"document_text": "doc"})
    data = json.loads(raw)
    for key in ("transport_types_raw", "cargo_weight_raw", "packaging"):
        assert key in data["extracted"]


def test_extract_transport_additional_transport_types_is_list():
    raw = extract_transport_additional.invoke({"document_text": "doc"})
    data = json.loads(raw)
    assert isinstance(data["extracted"]["transport_types_raw"], list)


# ===========================================================================
# resolve_transport_type
# ===========================================================================

def test_resolve_transport_type_exact_match():
    raw = resolve_transport_type.invoke({"transport_types_raw": ["Автомобильный транспорт"]})
    data = json.loads(raw)
    assert "Автомобильный транспорт" in data["resolved"]
    assert data["unresolved"] == []


def test_resolve_transport_type_case_insensitive():
    raw = resolve_transport_type.invoke({"transport_types_raw": ["морской транспорт"]})
    data = json.loads(raw)
    assert "Морской транспорт" in data["resolved"]


def test_resolve_transport_type_unknown():
    raw = resolve_transport_type.invoke({"transport_types_raw": ["Телепортация"]})
    data = json.loads(raw)
    assert "Телепортация" in data["unresolved"]


def test_resolve_transport_type_mixed():
    raw = resolve_transport_type.invoke({
        "transport_types_raw": ["Авиационный транспорт", "Неизвестный"]
    })
    data = json.loads(raw)
    assert "Авиационный транспорт" in data["resolved"]
    assert "Неизвестный" in data["unresolved"]


def test_resolve_transport_type_empty():
    raw = resolve_transport_type.invoke({"transport_types_raw": []})
    data = json.loads(raw)
    assert data["resolved"] == []
    assert data["unresolved"] == []


# ===========================================================================
# validate_transport_result
# ===========================================================================

def test_validate_transport_result_minimal_valid():
    payload = json.dumps({"file_name": "test.pdf"})
    raw = validate_transport_result.invoke({"result_json": payload})
    data = json.loads(raw)
    assert data["valid"] is True


def test_validate_transport_result_full_valid():
    payload = json.dumps({
        "file_name": "cargo.pdf",
        "cargo_name": "Оборудование",
        "cargo_weight": 5000.0,
        "insurance_sum": 1000000.0,
        "premium": 5000.0,
        "currency": "RUR",
        "departure_point": "Москва",
        "destination_point": "Санкт-Петербург",
        "transport_type": "Автомобильный транспорт",
        "date_start": "01.01.2024",
        "date_end": "31.01.2024",
    })
    raw = validate_transport_result.invoke({"result_json": payload})
    data = json.loads(raw)
    assert data["valid"] is True
    assert data["data"]["cargo_name"] == "Оборудование"


def test_validate_transport_result_strips_nulls():
    payload = json.dumps({"file_name": "x", "cargo_name": None, "cargo_weight": ""})
    raw = validate_transport_result.invoke({"result_json": payload})
    data = json.loads(raw)
    assert "cargo_name" not in data.get("data", {})


def test_validate_transport_result_auto_converts_weight():
    payload = json.dumps({"file_name": "x", "cargo_weight_raw": "5 тонн"})
    raw = validate_transport_result.invoke({"result_json": payload})
    data = json.loads(raw)
    assert data["valid"] is True
    assert data["data"].get("cargo_weight") == 5000.0


def test_validate_transport_result_auto_converts_float_string():
    payload = json.dumps({"file_name": "x", "insurance_sum": "1 500 000,50"})
    raw = validate_transport_result.invoke({"result_json": payload})
    data = json.loads(raw)
    assert data["valid"] is True
    assert data["data"].get("insurance_sum") == 1500000.5


# ===========================================================================
# fix_transport_field
# ===========================================================================

def test_fix_transport_field_updates_value():
    initial = json.dumps({"file_name": "test", "cargo_name": "СТАРЫЙ"})
    raw = fix_transport_field.invoke({
        "result_json": initial,
        "field_path": "cargo_name",
        "corrected_value": "Оборудование",
    })
    data = json.loads(raw)
    assert data.get("data", {}).get("cargo_name") == "Оборудование"


def test_fix_transport_field_creates_new_key():
    initial = json.dumps({"file_name": "x"})
    raw = fix_transport_field.invoke({
        "result_json": initial,
        "field_path": "transport_type",
        "corrected_value": "Автомобильный транспорт",
    })
    data = json.loads(raw)
    assert "error" not in data


def test_fix_transport_field_numeric_value():
    initial = json.dumps({"file_name": "x", "cargo_weight": None})
    raw = fix_transport_field.invoke({
        "result_json": initial,
        "field_path": "cargo_weight",
        "corrected_value": 10000.0,
    })
    data = json.loads(raw)
    assert data.get("data", {}).get("cargo_weight") == 10000.0


# ===========================================================================
# TransportParseResult schema
# ===========================================================================

def test_transport_schema_defaults():
    r = TransportParseResult()
    assert r.file_name == ""
    assert r.cargo_name is None
    assert r.cargo_weight is None
    assert r.parse_errors == []


@pytest.mark.parametrize("weight", [0.0, 500.0, 10000.0])
def test_transport_schema_cargo_weight(weight):
    r = TransportParseResult(cargo_weight=weight)
    assert r.cargo_weight == weight


def test_transport_schema_full_round_trip():
    data = {
        "file_name": "transport.pdf",
        "cargo_name": "Станки",
        "cargo_weight": 3000.0,
        "cargo_value": 5000000.0,
        "currency": "RUR",
        "departure_point": "Москва",
        "destination_point": "Новосибирск",
        "transport_type": "Железнодорожный транспорт",
        "date_start": "01.03.2024",
        "date_end": "15.03.2024",
        "insurer": "ООО Страховая",
        "insurer_inn": "7700112233",
        "insurance_sum": 5000000.0,
        "premium": 25000.0,
    }
    r = TransportParseResult.model_validate(data)
    dumped = r.model_dump(mode="json")
    assert dumped["file_name"] == "transport.pdf"
    assert dumped["cargo_weight"] == 3000.0
    assert dumped["transport_type"] == "Железнодорожный транспорт"


# ===========================================================================
# Runner parse_steps / build_chat_input
# ===========================================================================

def test_runner_parse_steps_valid():
    from agent6_transportation_parser.runner import TransportationParserRunner
    runner = TransportationParserRunner.__new__(TransportationParserRunner)
    steps = [("validate_transport_result", {
        "valid": True,
        "data": {"departure_point": "Москва", "destination_point": "Питер", "cargo_name": "Груз"},
    })]
    decision, artifacts, reply_subject = runner.parse_steps(steps, {"output": ""}, "job-1")
    assert decision == "Разбор завершён"
    assert "Москва" in reply_subject
    assert "Питер" in reply_subject


def test_runner_parse_steps_invalid():
    from agent6_transportation_parser.runner import TransportationParserRunner
    runner = TransportationParserRunner.__new__(TransportationParserRunner)
    steps = [("validate_transport_result", {
        "valid": False,
        "errors": ["cargo_weight: value is not a valid float"],
        "data": {},
    })]
    decision, artifacts, _ = runner.parse_steps(steps, {"output": ""}, "job-2")
    assert decision == "Требуется проверка"
    assert "cargo_weight: value is not a valid float" in artifacts["validation_errors"]


def test_runner_parse_steps_error():
    from agent6_transportation_parser.runner import TransportationParserRunner
    runner = TransportationParserRunner.__new__(TransportationParserRunner)
    steps = [("validate_transport_result", {"error": "connection timeout"})]
    decision, artifacts, _ = runner.parse_steps(steps, {"output": ""}, "job-3")
    assert decision == "Ошибка разбора"
    assert artifacts["error"] == "connection timeout"


def test_runner_build_chat_input():
    from agent6_transportation_parser.runner import TransportationParserRunner
    runner = TransportationParserRunner.__new__(TransportationParserRunner)
    mail = {"from": "user@corp.ru", "subject": "Перевозка груза", "body": ""}
    result = runner.build_chat_input(mail, ["Текст документа"])
    assert "ПЕРЕВОЗКИ" in result
    assert "user@corp.ru" in result
    assert "Текст документа" in result


def test_runner_parse_steps_fallback_to_output():
    from agent6_transportation_parser.runner import TransportationParserRunner
    runner = TransportationParserRunner.__new__(TransportationParserRunner)
    decision, _, _ = runner.parse_steps([], {"output": "разбор завершён"}, "job-4")
    assert decision == "Разбор завершён"
