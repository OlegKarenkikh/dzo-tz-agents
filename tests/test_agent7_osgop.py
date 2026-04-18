"""tests/test_agent7_osgop.py"""
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

from agent7_osgop_parser.tools import (
    _strip_none, _parse_float, _extract_tariff_short, _extract_table_section,
    extract_osgop_base, extract_osgop_insurant, extract_osgop_territory,
    extract_osgop_additional, extract_osgop_transport,
    validate_osgop_result, fix_osgop_field,
)
from shared.schemas import OsgopParseResult


@pytest.mark.parametrize("v, exp", [
    (None, None), (0, 0.0), ("1 500,5", 1500.5), ("abc", None), ({}, None),
])
def test_parse_float(v, exp):
    assert _parse_float(v) == exp


def test_strip_none_basic():
    assert _strip_none({"a": None, "b": "", "c": 1}) == {"c": 1}


def test_strip_none_list():
    assert _strip_none({"x": [None, "", {"k": None}, {"k": 1}]}) == {"x": [{"k": 1}]}


def test_extract_tariff_short_found():
    text = "Прочее\nТАРИФ автобус 5%\nдата: 01.01.2024\nПрочее"
    result = _extract_tariff_short(text)
    assert "ТАРИФ" in result.upper()


def test_extract_tariff_short_not_found():
    assert _extract_tariff_short("без тарифов") == ""


def test_extract_table_section_found():
    text = "AAA\nКОЛИЧЕСТВО ПЛАТЕЖЕЙ\n100\nТАРИФЫ\nBBB"
    result = _extract_table_section(text, "КОЛИЧЕСТВО ПЛАТЕЖЕЙ", "ТАРИФЫ")
    assert "100" in result


def test_extract_table_section_not_found():
    assert _extract_table_section("text", "MISSING", "END") == ""


def test_extract_osgop_base_schema():
    raw = extract_osgop_base.invoke({"document_text": "полис"})
    d = json.loads(raw)
    assert "extracted" in d
    for k in ("policy_number", "date_start", "insurance_sum", "premium", "currency"):
        assert k in d["extracted"]


def test_extract_osgop_base_all_null():
    raw = extract_osgop_base.invoke({"document_text": "полис"})
    d = json.loads(raw)
    for v in d["extracted"].values():
        assert v is None


def test_extract_osgop_insurant_schema():
    raw = extract_osgop_insurant.invoke({"document_text": "doc"})
    d = json.loads(raw)
    for k in ("name", "inn", "kpp", "legal_address"):
        assert k in d["extracted"]


def test_extract_osgop_territory_schema():
    raw = extract_osgop_territory.invoke({"document_text": "doc"})
    d = json.loads(raw)
    assert "regions" in d["extracted"]
    assert isinstance(d["extracted"]["regions"], list)
    assert d["extracted"]["international"] is False


def test_extract_osgop_additional_auto_extract():
    text = "ТАРИФ автобус 5%\nКОЛИЧЕСТВО ПЛАТЕЖЕЙ\n3 платежа\nТАРИФЫ\nдалее"
    raw = extract_osgop_additional.invoke({"document_text": text})
    d = json.loads(raw)
    assert "tariffs_section" in d
    assert "extracted" in d


def test_extract_osgop_additional_passed_info():
    raw = extract_osgop_additional.invoke({
        "document_text": "doc", "tariffs_info": "автобус: 5%", "payments_info": "01.01.2024: 10000"
    })
    d = json.loads(raw)
    assert "автобус" in d["tariffs_section"]


def test_extract_osgop_transport_schema():
    raw = extract_osgop_transport.invoke({"document_text": "5 автобусов"})
    d = json.loads(raw)
    for k in ("vehicle_count", "transportation_types", "vehicle_models"):
        assert k in d["extracted"]


def test_extract_osgop_transport_removes_table():
    text = "Полис\nСведения о транспортных средствах\nМарка: ПАЗ\nДАТА"
    raw = extract_osgop_transport.invoke({"document_text": text})
    d = json.loads(raw)
    assert "ПАЗ" not in d.get("text_without_table", "")


def test_validate_osgop_minimal():
    raw = validate_osgop_result.invoke({"result_json": json.dumps({"file_name": "x.pdf"})})
    d = json.loads(raw)
    assert d["valid"] is True


def test_validate_osgop_full():
    payload = json.dumps({
        "file_name": "osgop.pdf", "policy_number": "OSGOP-001",
        "insurance_sum": 5000000.0, "premium": 25000.0, "currency": "RUR",
        "date_start": "01.01.2024", "date_end": "31.12.2024",
        "vehicle_count": 5,
    })
    d = json.loads(validate_osgop_result.invoke({"result_json": payload}))
    assert d["valid"] is True
    assert d["data"]["policy_number"] == "OSGOP-001"


def test_validate_osgop_auto_float():
    payload = json.dumps({"file_name": "x", "insurance_sum": "1 000 000,00"})
    d = json.loads(validate_osgop_result.invoke({"result_json": payload}))
    assert d["valid"] is True
    assert d["data"].get("insurance_sum") == 1000000.0


def test_validate_osgop_strips_nulls():
    payload = json.dumps({"file_name": "x", "policy_number": None})
    d = json.loads(validate_osgop_result.invoke({"result_json": payload}))
    assert "policy_number" not in d.get("data", {})


def test_fix_osgop_field_updates():
    initial = json.dumps({"file_name": "x", "policy_number": "OLD"})
    d = json.loads(fix_osgop_field.invoke({
        "result_json": initial, "field_path": "policy_number", "corrected_value": "NEW-123"
    }))
    assert d.get("data", {}).get("policy_number") == "NEW-123"


def test_fix_osgop_field_nested():
    initial = json.dumps({"file_name": "x"})
    d = json.loads(fix_osgop_field.invoke({
        "result_json": initial, "field_path": "premium", "corrected_value": 5000.0
    }))
    assert "error" not in d


def test_osgop_schema_defaults():
    r = OsgopParseResult()
    assert r.file_name == ""
    assert r.policy_number is None
    assert r.vehicle_count is None


@pytest.mark.parametrize("sum_val", [0.0, 1000000.0, 99999.99])
def test_osgop_schema_insurance_sum(sum_val):
    r = OsgopParseResult(insurance_sum=sum_val)
    assert r.insurance_sum == sum_val


def test_osgop_schema_round_trip():
    data = {
        "file_name": "osgop.pdf", "policy_number": "OSGOP-999",
        "insurance_sum": 10000000.0, "premium": 50000.0, "currency": "RUR",
        "vehicle_count": 10, "transportation_types": ["Автобус"],
    }
    r = OsgopParseResult.model_validate(data)
    d = r.model_dump(mode="json")
    assert d["policy_number"] == "OSGOP-999"
    assert d["vehicle_count"] == 10


def test_runner_parse_steps_valid():
    from agent7_osgop_parser.runner import OsgopParserRunner
    runner = OsgopParserRunner.__new__(OsgopParserRunner)
    steps = [("validate_osgop_result", {"valid": True, "data": {"policy_number": "P-001"}})]
    decision, artifacts, subject = runner.parse_steps(steps, {}, "j1")
    assert decision == "Разбор завершён"
    assert "P-001" in subject


def test_runner_parse_steps_invalid():
    from agent7_osgop_parser.runner import OsgopParserRunner
    runner = OsgopParserRunner.__new__(OsgopParserRunner)
    steps = [("validate_osgop_result", {"valid": False, "errors": ["premium: bad"], "data": {}})]
    decision, artifacts, _ = runner.parse_steps(steps, {}, "j2")
    assert decision == "Требуется проверка"
    assert "premium: bad" in artifacts["validation_errors"]


def test_runner_build_chat_input():
    from agent7_osgop_parser.runner import OsgopParserRunner
    runner = OsgopParserRunner.__new__(OsgopParserRunner)
    result = runner.build_chat_input({"from": "u@test.ru", "subject": "Полис ОСГОП"}, ["Текст полиса"])
    assert "ОСГОП" in result
    assert "u@test.ru" in result
    assert "Текст полиса" in result
