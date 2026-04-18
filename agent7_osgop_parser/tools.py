"""
agent7_osgop_parser/tools.py
"""
from __future__ import annotations
import json
import re
from typing import Any
from langchain.tools import tool
from pydantic import BaseModel, ConfigDict, Field
from shared.logger import setup_logger
from shared.schemas import OsgopParseResult

logger = setup_logger("agent_osgop")

class DocTextInput(BaseModel):
    model_config = ConfigDict(strict=True)
    document_text: str = Field(description="Полный текст полиса ОСГОП")

class AdditionalInput(BaseModel):
    model_config = ConfigDict(strict=True)
    document_text: str = Field(description="Полный текст полиса")
    tariffs_info: str = Field(default="", description="Извлечённая секция тарифов")
    payments_info: str = Field(default="", description="Извлечённая секция платежей")

class ValidateInput(BaseModel):
    model_config = ConfigDict(strict=True)
    result_json: str = Field(description="JSON-строка результата OsgopParseResult")

class FixFieldInput(BaseModel):
    model_config = ConfigDict(strict=True)
    result_json: str = Field(description="Текущий JSON результата")
    field_path: str = Field(description="Путь к полю (точечная нотация)")
    corrected_value: Any = Field(description="Исправленное значение")


def _strip_none(d: dict) -> dict:
    result = {}
    for k, v in d.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        if isinstance(v, dict):
            sub = _strip_none(v)
            if sub:
                result[k] = sub
        elif isinstance(v, list):
            clean = [_strip_none(i) if isinstance(i, dict) else i for i in v if i not in (None, "")]
            clean = [i for i in clean if i not in ({}, None, "")]
            if clean:
                result[k] = clean
        else:
            result[k] = v
    return result


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(" ", "").replace(",", ".").replace("%", ""))
        except (ValueError, TypeError):
            return None
    return None


def _extract_tariff_short(text: str) -> str:
    """Извлекает краткую секцию тарифов (DA PreProcessing.extract_tariff_short)."""
    pattern = r"(?i)" + r"тариф[^\n]*\n(?:[^\n]*\n){0,5}"
    match = re.search(pattern, text)
    return match.group(0).strip() if match else ""


def _extract_table_section(text: str, start: str, end: str) -> str:
    """Извлекает секцию таблицы между маркерами."""
    try:
        start_idx = text.upper().find(start.upper())
        if start_idx == -1:
            return ""
        end_idx = text.upper().find(end.upper(), start_idx)
        return text[start_idx:end_idx].strip() if end_idx != -1 else text[start_idx:].strip()
    except Exception:
        return ""


@tool(args_schema=DocTextInput)
def extract_osgop_base(document_text: str) -> str:
    """Извлекает базовые данные полиса ОСГОП:
    номер полиса, страховщик, даты начала/окончания, страховая сумма, премия, валюта.
    Блок DA: base_prompt.
    """
    try:
        schema: dict[str, Any] = {
            "instruction": (
                "Извлеки из полиса ОСГОП: номер полиса, страховщика, "
                "даты начала/окончания (DD.MM.YYYY), страховую сумму (float), "
                "страховую премию (float), валюту (RUR/USD/EUR)."
            ),
            "extracted": {
                "policy_number": None,
                "insurer_company": None,
                "date_start": None,
                "date_end": None,
                "insurance_sum": None,
                "premium": None,
                "currency": None,
            },
        }
        logger.info("extract_osgop_base: шаблон сформирован")
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(args_schema=DocTextInput)
def extract_osgop_insurant(document_text: str) -> str:
    """Извлекает данные страхователя из полиса ОСГОП.
    Блок DA: base_insurant_prompt.
    """
    try:
        schema: dict[str, Any] = {
            "instruction": "Извлеки данные страхователя: наименование, ИНН, КПП, адрес, контакты.",
            "extracted": {
                "name": None,
                "inn": None,
                "kpp": None,
                "legal_address": None,
                "actual_address": None,
                "phone": None,
                "email": None,
            },
        }
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(args_schema=DocTextInput)
def extract_osgop_territory(document_text: str) -> str:
    """Извлекает территорию страхования из полиса ОСГОП.
    Блок DA: base_territory_prompt.
    """
    try:
        schema: dict[str, Any] = {
            "instruction": "Извлеки территорию страхования: регионы, маршруты, ограничения.",
            "extracted": {
                "regions": [],
                "international": False,
                "territory_description": None,
                "restrictions": None,
            },
        }
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(args_schema=AdditionalInput)
def extract_osgop_additional(
    document_text: str,
    tariffs_info: str = "",
    payments_info: str = "",
) -> str:
    """Извлекает доп. условия полиса ОСГОП: тарифы, платежи, франшиза.
    Блок DA: additional_prompt.
    """
    try:
        if not tariffs_info:
            tariffs_info = _extract_tariff_short(document_text)
        if not payments_info:
            payments_info = _extract_table_section(document_text, "КОЛИЧЕСТВО ПЛАТЕЖЕЙ", "ТАРИФЫ")
        schema: dict[str, Any] = {
            "instruction": "Извлеки тарифы по видам перевозок, график платежей, франшизу, особые условия.",
            "tariffs_section": tariffs_info or "(не найдено)",
            "payments_section": payments_info or "(не найдено)",
            "extracted": {
                "tariffs": {},
                "payment_schedule": [],
                "franchise": None,
                "special_conditions": None,
                "risk_exclusions": None,
            },
        }
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(args_schema=DocTextInput)
def extract_osgop_transport(document_text: str) -> str:
    """Извлекает сведения о ТС и типах перевозок из полиса ОСГОП.
    Блок DA: transport_prompt + transport_models_prompt.
    """
    try:
        table_pattern = r"(?i)" + r"сведения о транспортных средствах.{0,3000}"
        clean_text = re.sub(table_pattern, "[ТАБЛИЦА ТС УДАЛЕНА]", document_text, flags=re.DOTALL)
        schema: dict[str, Any] = {
            "instruction": "Извлеки: количество ТС (int), типы перевозок, марки/модели ТС, категории.",
            "text_without_table": clean_text[:500] + "..." if len(clean_text) > 500 else clean_text,
            "extracted": {
                "vehicle_count": None,
                "transportation_types": [],
                "vehicle_models": [],
                "vehicle_categories": [],
                "has_license_cards": None,
            },
        }
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(args_schema=ValidateInput)
def validate_osgop_result(result_json: str) -> str:
    """Валидирует OsgopParseResult через Pydantic.
    Возвращает {valid: true, data: ...} или {valid: false, errors: ..., data: ...}.
    """
    try:
        raw = json.loads(result_json) if isinstance(result_json, str) else result_json
        for field in ("insurance_sum", "premium", "franchise"):
            if isinstance(raw.get(field), str):
                raw[field] = _parse_float(raw[field])
        from pydantic import ValidationError
        try:
            validated = OsgopParseResult.model_validate(raw)
            clean = _strip_none(validated.model_dump(mode="json"))
            logger.info("validate_osgop_result: OK")
            return json.dumps({"valid": True, "data": clean}, ensure_ascii=False, indent=2)
        except ValidationError as ve:
            errors = [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in ve.errors()]
            return json.dumps({"valid": False, "errors": errors, "data": _strip_none(raw)}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(args_schema=FixFieldInput)
def fix_osgop_field(result_json: str, field_path: str, corrected_value: Any) -> str:
    """Точечно исправляет поле в результате ОСГОП и перезапускает валидацию."""
    try:
        data = json.loads(result_json) if isinstance(result_json, str) else result_json
        parts = field_path.split(".")
        node: Any = data
        for part in parts[:-1]:
            node = node.setdefault(part, {}) if isinstance(node, dict) else node[int(part)]
        if isinstance(node, dict):
            node[parts[-1]] = corrected_value
        logger.info("fix_osgop_field: поле %s исправлено", field_path)
        return validate_osgop_result.invoke({"result_json": json.dumps(data, ensure_ascii=False)})
    except Exception as e:
        return json.dumps({"error": str(e)})
