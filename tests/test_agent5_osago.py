"""
tests/test_agent5_osago.py
Тесты агента agent5_osago_parser:
- инструменты (tools.py)
- схема OsagoParseResult
- runner (parse_steps)
"""
from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

if "langgraph.prebuilt" not in sys.modules:
    _fake_lgp = types.ModuleType("langgraph.prebuilt")
    _fake_lgp.create_react_agent = MagicMock(return_value=MagicMock())  # type: ignore
    sys.modules["langgraph.prebuilt"] = _fake_lgp


# ===== extract_osago_base =====

from agent5_osago_parser.tools import (
    extract_osago_base,
    extract_osago_additional,
    validate_osago_result,
    fix_osago_field,
)


def test_extract_osago_base_returns_json():
    raw = extract_osago_base.invoke({"document_text": "Тестовый документ"})
    data = json.loads(raw)
    assert "instruction" in data
    assert "extracted" in data


def test_extract_osago_base_contains_vehicle_fields():
    raw = extract_osago_base.invoke({"document_text": "doc"})
    data = json.loads(raw)
    for key in ("insurer", "vehicle_brand", "vehicle_number", "vin", "date_start", "date_end"):
        assert key in data["extracted"]


def test_extract_osago_base_gaz_hint_present():
    raw = extract_osago_base.invoke({"document_text": "doc"})
    data = json.loads(raw)
    assert "Газпром" in data.get("gaz_flag_hint", "")


# ===== extract_osago_additional =====

def test_extract_osago_additional_schema():
    raw = extract_osago_additional.invoke({"document_text": "doc"})
    data = json.loads(raw)
    for key in ("power_hp", "max_mass", "permitted_max_mass", "seats_count"):
        assert key in data["extracted"]


# ===== validate_osago_result =====

def test_validate_osago_result_minimal_valid():
    payload = json.dumps({"file_name": "test.pdf"})
    raw = validate_osago_result.invoke({"result_json": payload})
    data = json.loads(raw)
    assert data["valid"] is True


def test_validate_osago_result_with_data():
    payload = json.dumps({
        "file_name": "osago.pdf",
        "vehicle_brand": "ЛАДА",
        "vehicle_number": "А001АА199",
        "year": 2020,
        "date_start": "01.01.2024",
        "power_hp": 90.0,
    })
    raw = validate_osago_result.invoke({"result_json": payload})
    data = json.loads(raw)
    assert data["valid"] is True
    assert data["data"]["vehicle_brand"] == "ЛАДА"


def test_validate_osago_result_strips_nulls():
    payload = json.dumps({"file_name": "x", "vehicle_brand": None, "vin": ""})
    raw = validate_osago_result.invoke({"result_json": payload})
    data = json.loads(raw)
    assert "vehicle_brand" not in data.get("data", {})
    assert "vin" not in data.get("data", {})


# ===== fix_osago_field =====

def test_fix_osago_field_updates_value():
    initial = json.dumps({"file_name": "test", "vehicle_number": "OLD"})
    raw = fix_osago_field.invoke({
        "result_json": initial,
        "field_path": "vehicle_number",
        "corrected_value": "NEW-123",
    })
    data = json.loads(raw)
    assert data.get("data", {}).get("vehicle_number") == "NEW-123"


def test_fix_osago_field_invalid_path_doesnt_crash():
    initial = json.dumps({"file_name": "x"})
    # Setting a new key via fix should work (creates it)
    raw = fix_osago_field.invoke({
        "result_json": initial,
        "field_path": "vin",
        "corrected_value": "XTA123456",
    })
    assert "error" not in json.loads(raw)


# ===== OsagoParseResult schema =====

from shared.schemas import OsagoParseResult


def test_osago_parse_result_defaults():
    result = OsagoParseResult()
    assert result.file_name == ""
    assert result.parse_errors == []


def test_osago_parse_result_full():
    data = {
        "file_name": "osago.pdf",
        "vehicle_brand": "ЛАДА",
        "vehicle_model": "Гранта",
        "vehicle_number": "А001АА199",
        "year": 2019,
        "power_hp": 87.0,
    }
    result = OsagoParseResult.model_validate(data)
    assert result.vehicle_brand == "ЛАДА"
    assert result.year == 2019
    assert result.power_hp == 87.0


# ===== Runner parse_steps =====

def test_osago_runner_parse_steps_valid():
    from agent5_osago_parser.runner import OsagoParserRunner
    runner = OsagoParserRunner.__new__(OsagoParserRunner)
    steps = [("validate_osago_result", {
        "valid": True,
        "data": {"vehicle_brand": "ЛАДА", "vehicle_number": "А001АА199"},
    })]
    decision, artifacts, reply_subject = runner.parse_steps(steps, {"output": ""}, "job-1")
    assert decision == "Разбор завершён"
    assert "ЛАДА" in reply_subject


def test_osago_runner_parse_steps_invalid():
    from agent5_osago_parser.runner import OsagoParserRunner
    runner = OsagoParserRunner.__new__(OsagoParserRunner)
    steps = [("validate_osago_result", {"valid": False, "errors": ["Ошибка"], "data": {}})]
    decision, artifacts, _ = runner.parse_steps(steps, {"output": ""}, "job-2")
    assert decision == "Требуется проверка"
    assert "Ошибка" in artifacts["validation_errors"]


def test_osago_runner_build_chat_input():
    from agent5_osago_parser.runner import OsagoParserRunner
    runner = OsagoParserRunner.__new__(OsagoParserRunner)
    mail = {"from": "user@corp.ru", "subject": "ОСАГО", "body": ""}
    result = runner.build_chat_input(mail, ["Текст"])
    assert "ОСАГО" in result
    assert "user@corp.ru" in result
