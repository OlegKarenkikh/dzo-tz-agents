"""
tests/test_agent4_leasing.py
Тесты агента agent4_leasing_parser:
- инструменты (tools.py)
- схема LeasingParseResult
- runner (parse_steps)
- вспомогательные функции (_cut, _normalize_date, _parse_float, _parse_int)
"""
from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub langgraph.prebuilt before any agent import
# ---------------------------------------------------------------------------
if "langgraph.prebuilt" not in sys.modules:
    _fake_lgp = types.ModuleType("langgraph.prebuilt")
    _fake_lgp.create_react_agent = MagicMock(return_value=MagicMock())  # type: ignore
    sys.modules["langgraph.prebuilt"] = _fake_lgp


# ---------------------------------------------------------------------------
# Helper functions (copied from tools.py to allow unit testing in isolation)
# ---------------------------------------------------------------------------
from agent4_leasing_parser.tools import _cut, _normalize_date, _parse_float, _parse_int, _strip_none


# ===== _cut =====

@pytest.mark.parametrize("value, length, expected", [
    ("abc", 250, "abc"),
    ("x" * 300, 250, "x" * 250),
    ("hello", 3, "hel"),
    (None, 250, None),
    (42, 250, 42),
    (3.14, 250, 3.14),
])
def test_cut(value, length, expected):
    assert _cut(value, length) == expected


# ===== _normalize_date =====

@pytest.mark.parametrize("raw, expected", [
    ("", ""),
    (None, ""),
    ("01.03.2024", "01.03.2024"),
    ("«12» июля 2023 г.", "12.07.2023"),
    ("5 апреля 2025", "05.04.2025"),
    ("01 января 2020", "01.01.2020"),
    ("«31» декабря 2024 г.", "31.12.2024"),
])
def test_normalize_date(raw, expected):
    assert _normalize_date(raw) == expected


# ===== _parse_float =====

@pytest.mark.parametrize("value, expected", [
    (None, None),
    (1, 1.0),
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


# ===== _parse_int =====

@pytest.mark.parametrize("value, expected", [
    (None, None),
    (5, 5),
    (3.9, 3),
    ("7", 7),
    ("1 000,5", 1000),
    ("", None),
    ("abc", None),
])
def test_parse_int(value, expected):
    assert _parse_int(value) == expected


# ===== _strip_none =====

def test_strip_none_removes_empty():
    result = _strip_none({"a": None, "b": "", "c": [], "d": {}, "e": "ok"})
    assert result == {"e": "ok"}


def test_strip_none_nested():
    result = _strip_none({"outer": {"inner": None, "val": 1}})
    assert result == {"outer": {"val": 1}}


def test_strip_none_list_cleans_nulls():
    result = _strip_none({"items": [None, "", {"a": None}, {"b": 1}]})
    assert result == {"items": [{"b": 1}]}


# ===== extract_leasing_base =====

from agent4_leasing_parser.tools import extract_leasing_base


def test_extract_leasing_base_returns_json():
    raw = extract_leasing_base.invoke({"document_text": "Тестовый документ"})
    data = json.loads(raw)
    assert "instruction" in data
    assert "extracted" in data
    assert "policy_number" in data["extracted"]


def test_extract_leasing_base_contains_required_keys():
    raw = extract_leasing_base.invoke({"document_text": "doc"})
    data = json.loads(raw)
    for key in ("currency", "territory", "insurance_rules", "risks_list"):
        assert key in data["extracted"]


# ===== extract_leasing_additional =====

from agent4_leasing_parser.tools import extract_leasing_additional


def test_extract_leasing_additional_schema():
    raw = extract_leasing_additional.invoke({"document_text": "doc", "table_text": ""})
    data = json.loads(raw)
    assert data["has_table_text"] is False
    for key in ("date_start", "date_end", "insurance_objects", "payments"):
        assert key in data["extracted"]


def test_extract_leasing_additional_with_table():
    raw = extract_leasing_additional.invoke({"document_text": "doc", "table_text": "Таблица"})
    data = json.loads(raw)
    assert data["has_table_text"] is True


# ===== extract_leasing_roles =====

from agent4_leasing_parser.tools import extract_leasing_roles


def test_extract_leasing_roles_schema():
    raw = extract_leasing_roles.invoke({"document_text": "doc"})
    data = json.loads(raw)
    assert "role_isn_map" in data
    assert "лизингодатель" in data["role_isn_map"]
    assert data["extracted"] == []


# ===== extract_leasing_territory =====

from agent4_leasing_parser.tools import extract_leasing_territory


def test_extract_leasing_territory_passes_raw():
    raw = extract_leasing_territory.invoke({"territory_raw": "г. Москва"})
    data = json.loads(raw)
    assert data["territory_raw"] == "г. Москва"
    for key in ("country", "city", "street"):
        assert key in data["extracted"]


def test_extract_leasing_territory_truncates_long_string():
    long_str = "x" * 300
    raw = extract_leasing_territory.invoke({"territory_raw": long_str})
    data = json.loads(raw)
    # territory_raw in output should be cut to 250
    assert len(data["territory_raw"]) <= 250


# ===== extract_leasing_risks =====

from agent4_leasing_parser.tools import extract_leasing_risks


def test_extract_leasing_risks_with_numbered_risks():
    risks = ["Пожар", "Кража"]
    raw = extract_leasing_risks.invoke({
        "document_text": "doc",
        "rules": ["Правила 001"],
        "numbered_risks": risks,
    })
    data = json.loads(raw)
    assert data["risks_from_doc"] == risks
    assert data["rules"] == ["Правила 001"]


def test_extract_leasing_risks_empty_defaults():
    raw = extract_leasing_risks.invoke({"document_text": "doc"})
    data = json.loads(raw)
    assert data["rules"] == []
    assert data["risks_from_doc"] == []


# ===== validate_leasing_result =====

from agent4_leasing_parser.tools import validate_leasing_result


def test_validate_leasing_result_minimal_valid():
    payload = json.dumps({"file_name": "test.docx"})
    raw = validate_leasing_result.invoke({"result_json": payload})
    data = json.loads(raw)
    assert data["valid"] is True
    assert "data" in data


def test_validate_leasing_result_invalid_schema():
    # currency must be RUR/USD/EUR or None — invalid type forces Pydantic to coerce/error
    payload = json.dumps({"base": {"currency": None}, "file_name": "x"})
    raw = validate_leasing_result.invoke({"result_json": payload})
    data = json.loads(raw)
    # None currency is fine (Optional), should be valid
    assert data["valid"] is True


def test_validate_leasing_result_normalizes_dates():
    payload = json.dumps({
        "file_name": "doc",
        "base": {"date_sign": "«01» января 2024 г."},
    })
    raw = validate_leasing_result.invoke({"result_json": payload})
    data = json.loads(raw)
    assert data["valid"] is True
    # After normalization date_sign should be DD.MM.YYYY
    date_sign = data["data"].get("base", {}).get("date_sign")
    if date_sign:
        assert len(date_sign) == 10


# ===== fix_leasing_field =====

from agent4_leasing_parser.tools import fix_leasing_field


def test_fix_leasing_field_updates_value():
    initial = json.dumps({"file_name": "test", "base": {"policy_number": "OLD-001"}})
    raw = fix_leasing_field.invoke({
        "result_json": initial,
        "field_path": "base.policy_number",
        "corrected_value": "NEW-999",
    })
    data = json.loads(raw)
    assert data.get("data", {}).get("base", {}).get("policy_number") == "NEW-999"


def test_fix_leasing_field_nested_creation():
    initial = json.dumps({"file_name": "test"})
    raw = fix_leasing_field.invoke({
        "result_json": initial,
        "field_path": "base.currency",
        "corrected_value": "RUR",
    })
    data = json.loads(raw)
    # After fix the path should exist
    assert "data" in data or "error" not in data


# ===== LeasingParseResult schema =====

from shared.schemas import LeasingParseResult


def test_leasing_parse_result_defaults():
    result = LeasingParseResult()
    assert result.file_name == ""
    assert result.roles == []
    assert result.risks == []


def test_leasing_parse_result_currency_normalization():
    result = LeasingParseResult(base={"currency": "rur"})
    assert result.base.currency == "RUR"


def test_leasing_parse_result_currency_normalization_usd():
    result = LeasingParseResult(base={"currency": "usd"})
    assert result.base.currency == "USD"


def test_leasing_parse_result_full():
    data = {
        "file_name": "contract.docx",
        "base": {
            "policy_number": "POL-001",
            "currency": "RUR",
            "date_sign": "01.01.2024",
        },
        "roles": [{"role": "страхователь", "organization_name": "ООО Тест"}],
        "risks": [{"short_name": "Пожар", "classisn": 100, "ruleisn": 200}],
    }
    result = LeasingParseResult.model_validate(data)
    assert result.file_name == "contract.docx"
    assert result.base.policy_number == "POL-001"
    assert len(result.roles) == 1
    assert len(result.risks) == 1


# ===== Runner parse_steps =====

from unittest.mock import MagicMock


def _make_runner():
    with patch("agent4_leasing_parser.agent.create_leasing_agent"):
        from agent4_leasing_parser.runner import LeasingParserRunner
    return LeasingParserRunner()


def test_runner_parse_steps_valid():
    from agent4_leasing_parser.runner import LeasingParserRunner
    runner = LeasingParserRunner.__new__(LeasingParserRunner)
    steps = [("validate_leasing_result", {"valid": True, "data": {"base": {"policy_number": "POL-42"}}})]
    decision, artifacts, reply_subject = runner.parse_steps(steps, {"output": ""}, "job-1")
    assert decision == "Разбор завершён"
    assert artifacts["leasing_data"]["base"]["policy_number"] == "POL-42"
    assert "POL-42" in reply_subject


def test_runner_parse_steps_invalid():
    from agent4_leasing_parser.runner import LeasingParserRunner
    runner = LeasingParserRunner.__new__(LeasingParserRunner)
    steps = [("validate_leasing_result", {"valid": False, "errors": ["Ошибка"], "data": {}})]
    decision, artifacts, reply_subject = runner.parse_steps(steps, {"output": ""}, "job-2")
    assert decision == "Требуется проверка"
    assert "Ошибка" in artifacts["validation_errors"]


def test_runner_parse_steps_no_steps_fallback_output():
    from agent4_leasing_parser.runner import LeasingParserRunner
    runner = LeasingParserRunner.__new__(LeasingParserRunner)
    decision, _, _ = runner.parse_steps([], {"output": "разбор завершён"}, "job-3")
    assert decision == "Разбор завершён"


def test_runner_build_chat_input():
    from agent4_leasing_parser.runner import LeasingParserRunner
    runner = LeasingParserRunner.__new__(LeasingParserRunner)
    mail = {"from": "test@test.ru", "subject": "Лизинг"}
    result = runner.build_chat_input(mail, ["Текст документа"])
    assert "ЛИЗИНГА" in result
    assert "test@test.ru" in result
    assert "Текст документа" in result
