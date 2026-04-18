"""tests/test_agent8_responsibility.py"""
from __future__ import annotations
import json
import sys
import types
from unittest.mock import MagicMock
import pytest

if "langgraph.prebuilt" not in sys.modules:
    _m = types.ModuleType("langgraph.prebuilt")
    _m.create_react_agent = MagicMock(return_value=MagicMock())
    sys.modules["langgraph.prebuilt"] = _m

from agent8_responsibility_parser.tools import (
    _strip_none, _parse_float, _detect_subtype_heuristic,
    _extract_date_info, _extract_objects_info, _extract_payments_section,
    detect_responsibility_type, extract_responsibility_base,
    extract_responsibility_objects, extract_responsibility_fid,
    validate_responsibility_result, fix_responsibility_field,
)
from shared.schemas import ResponsibilityParseResult


@pytest.mark.parametrize("text, expected", [
    ("Договор 432 о финансовом риске", "432"),
    ("ФИД данные кредит", "432"),
    ("Имущественная ответственность 433", "433"),
    ("Гражданская ответственность третьи лица", "431"),
    ("Обычный договор", "431"),
])
def test_detect_subtype_heuristic(text, expected):
    assert _detect_subtype_heuristic(text) == expected


def test_extract_date_info():
    text = "дата 01.01.2024 и 15/06/2024"
    result = _extract_date_info(text)
    assert "01.01.2024" in result


def test_extract_date_info_empty():
    assert _extract_date_info("без дат") == ""


def test_extract_objects_info():
    text = "Объект страхования: Склад на Ленина 5\nОбъект: Офис"
    objects = _extract_objects_info(text)
    assert len(objects) >= 1


def test_extract_payments_section():
    text = "Дата заключения 01.01.2024\nплатеж 10000\nПрочие данные\nдалее"
    result = _extract_payments_section(text)
    assert "10000" in result


def test_strip_none():
    assert _strip_none({"a": None, "b": [], "c": "ok"}) == {"c": "ok"}


def test_detect_type_431():
    raw = detect_responsibility_type.invoke({"document_text": "третьи лица ответственность"})
    d = json.loads(raw)
    assert d["subtype"] in ("431", "432", "433")
    assert "instruction" in d


def test_detect_type_432():
    raw = detect_responsibility_type.invoke({"document_text": "финансовый риск ФИД 432"})
    d = json.loads(raw)
    assert d["subtype"] == "432"


def test_detect_type_433():
    raw = detect_responsibility_type.invoke({"document_text": "имущественная ответственность 433"})
    d = json.loads(raw)
    assert d["subtype"] == "433"


def test_detect_type_confidence():
    raw = detect_responsibility_type.invoke({"document_text": "третьи лица"})
    d = json.loads(raw)
    assert d["confidence"] in ("high", "medium")


@pytest.mark.parametrize("subtype", ["431", "432", "433"])
def test_extract_base_schema(subtype):
    raw = extract_responsibility_base.invoke({"document_text": "doc", "subtype": subtype})
    d = json.loads(raw)
    assert "extracted" in d
    assert d["subtype"] == subtype
    for k in ("contract_number", "date_start", "insurance_sum", "risks"):
        assert k in d["extracted"]


def test_extract_base_432_has_payment_schedule():
    raw = extract_responsibility_base.invoke({"document_text": "doc", "subtype": "432"})
    d = json.loads(raw)
    assert "payment_schedule" in d["extracted"]


def test_extract_base_uses_date_hint():
    text = "Дата 01.03.2024 начало"
    raw = extract_responsibility_base.invoke({"document_text": text, "subtype": "431"})
    d = json.loads(raw)
    assert "01.03.2024" in d.get("date_info_hint", "")


def test_extract_objects_schema():
    raw = extract_responsibility_objects.invoke({"document_text": "объект: Склад"})
    d = json.loads(raw)
    assert "objects" in d["extracted"]
    assert isinstance(d["extracted"]["objects"], list)


def test_extract_objects_hint_auto():
    text = "Объект страхования: Гараж на Пушкина"
    raw = extract_responsibility_objects.invoke({"document_text": text})
    d = json.loads(raw)
    assert "Гараж" in d.get("objects_hint", "")


def test_extract_objects_passed_hint():
    raw = extract_responsibility_objects.invoke({"document_text": "doc", "objects_hint": "Склад; Офис"})
    d = json.loads(raw)
    assert "Склад" in d["objects_hint"]


def test_extract_fid_schema():
    raw = extract_responsibility_fid.invoke({"document_text": "doc"})
    d = json.loads(raw)
    assert "extracted" in d
    for k in ("fid_id", "fid_status", "fid_amount"):
        assert k in d["extracted"]


def test_extract_fid_source_main():
    raw = extract_responsibility_fid.invoke({"document_text": "doc"})
    d = json.loads(raw)
    assert d["fid_source"] == "main_document"


def test_extract_fid_source_fid_doc():
    raw = extract_responsibility_fid.invoke({"document_text": "doc", "fid_text": "ФИД-001"})
    d = json.loads(raw)
    assert d["fid_source"] == "fid_document"


def test_extract_fid_all_null():
    raw = extract_responsibility_fid.invoke({"document_text": "doc"})
    d = json.loads(raw)
    for v in d["extracted"].values():
        assert v is None or v == []


def test_validate_minimal_431():
    raw = validate_responsibility_result.invoke({
        "result_json": json.dumps({"file_name": "x"}), "subtype": "431"
    })
    d = json.loads(raw)
    assert d["valid"] is True
    assert d["subtype"] == "431"


def test_validate_full_431():
    payload = json.dumps({
        "file_name": "resp.pdf", "contract_number": "431-001",
        "insurance_sum": 1000000.0, "premium": 5000.0,
        "date_start": "01.01.2024", "date_end": "31.12.2024",
        "objects": [{"name": "Склад", "limit": 500000.0}],
    })
    d = json.loads(validate_responsibility_result.invoke({"result_json": payload, "subtype": "431"}))
    assert d["valid"] is True
    assert d["data"]["contract_number"] == "431-001"


def test_validate_auto_float():
    payload = json.dumps({"file_name": "x", "insurance_sum": "2 000 000,00"})
    d = json.loads(validate_responsibility_result.invoke({"result_json": payload, "subtype": "431"}))
    assert d["valid"] is True
    assert d["data"].get("insurance_sum") == 2000000.0


@pytest.mark.parametrize("subtype", ["431", "432", "433"])
def test_validate_all_subtypes(subtype):
    payload = json.dumps({"file_name": f"resp_{subtype}.pdf"})
    d = json.loads(validate_responsibility_result.invoke({"result_json": payload, "subtype": subtype}))
    assert d["valid"] is True
    assert d["subtype"] == subtype


def test_fix_field_updates():
    initial = json.dumps({"file_name": "x", "contract_number": "OLD"})
    d = json.loads(fix_responsibility_field.invoke({
        "result_json": initial, "subtype": "431",
        "field_path": "contract_number", "corrected_value": "431-NEW",
    }))
    assert d.get("data", {}).get("contract_number") == "431-NEW"


def test_fix_field_nested_object():
    initial = json.dumps({"file_name": "x", "objects": [{"name": "Склад", "limit": None}]})
    d = json.loads(fix_responsibility_field.invoke({
        "result_json": initial, "subtype": "433",
        "field_path": "objects.0.limit", "corrected_value": 1000000.0,
    }))
    assert "error" not in d


def test_responsibility_schema_defaults():
    r = ResponsibilityParseResult()
    assert r.file_name == ""
    assert r.subtype == "431"
    assert r.contract_number is None
    assert r.objects == []


@pytest.mark.parametrize("subtype", ["431", "432", "433"])
def test_responsibility_schema_subtype(subtype):
    r = ResponsibilityParseResult(subtype=subtype)
    assert r.subtype == subtype


def test_responsibility_schema_round_trip():
    data = {
        "file_name": "resp.pdf", "subtype": "431", "contract_number": "431-100",
        "insurance_sum": 5000000.0, "premium": 25000.0,
        "date_start": "01.03.2024", "date_end": "28.02.2025",
        "objects": [{"name": "Завод", "limit": 2000000.0}],
    }
    r = ResponsibilityParseResult.model_validate(data)
    d = r.model_dump(mode="json")
    assert d["contract_number"] == "431-100"
    assert d["objects"][0]["name"] == "Завод"


def test_runner_parse_steps_valid():
    from agent8_responsibility_parser.runner import ResponsibilityParserRunner
    runner = ResponsibilityParserRunner.__new__(ResponsibilityParserRunner)
    steps = [("validate", {"valid": True, "subtype": "431", "data": {"contract_number": "C-1"}})]
    decision, artifacts, subject = runner.parse_steps(steps, {}, "j1")
    assert decision == "Разбор завершён"
    assert "C-1" in subject
    assert "431" in subject


def test_runner_parse_steps_invalid():
    from agent8_responsibility_parser.runner import ResponsibilityParserRunner
    runner = ResponsibilityParserRunner.__new__(ResponsibilityParserRunner)
    steps = [("validate", {"valid": False, "subtype": "432", "errors": ["x: bad"], "data": {}})]
    decision, artifacts, _ = runner.parse_steps(steps, {}, "j2")
    assert decision == "Требуется проверка"
    assert "x: bad" in artifacts["validation_errors"]


def test_runner_build_chat_input():
    from agent8_responsibility_parser.runner import ResponsibilityParserRunner
    runner = ResponsibilityParserRunner.__new__(ResponsibilityParserRunner)
    result = runner.build_chat_input({"from": "u@test.ru", "subject": "Договор 431"}, ["Текст договора"])
    assert "ОТВЕТСТВЕННОСТИ" in result
    assert "Текст договора" in result
