"""
agent8_responsibility_parser/tools.py
Инструменты LangChain для агента разбора договоров ответственности (431/432/433).
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal

from langchain.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from shared.logger import setup_logger
from shared.schemas import ResponsibilityParseResult

logger = setup_logger("agent_responsibility")

SubType = Literal["431", "432", "433"]

# ---------------------------------------------------------------------------
# Pydantic-схемы аргументов
# ---------------------------------------------------------------------------

class DetectTypeInput(BaseModel):
    model_config = ConfigDict(strict=True)
    document_text: str = Field(description="Полный текст договора ответственности")


class BaseExtractInput(BaseModel):
    model_config = ConfigDict(strict=True)
    document_text: str = Field(description="Полный текст договора")
    subtype: str = Field(description="Тип договора: 431, 432 или 433")


class ObjectsInput(BaseModel):
    model_config = ConfigDict(strict=True)
    document_text: str = Field(description="Полный текст договора")
    objects_hint: str = Field(default="", description="Подсказка об объектах из preprocessing")


class FidInput(BaseModel):
    model_config = ConfigDict(strict=True)
    document_text: str = Field(description="Текст основного договора")
    fid_text: str = Field(default="", description="Текст ФИД-документа (если есть)")


class ValidateInput(BaseModel):
    model_config = ConfigDict(strict=True)
    result_json: str = Field(description="JSON-строка результата")
    subtype: str = Field(description="Тип: 431, 432 или 433")


class FixFieldInput(BaseModel):
    model_config = ConfigDict(strict=True)
    result_json: str = Field(description="Текущий JSON результата")
    subtype: str = Field(description="Тип: 431, 432 или 433")
    field_path: str = Field(description="Путь к полю (точечная нотация)")
    corrected_value: Any = Field(description="Исправленное значение")


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

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
            clean = [_strip_none(i) if isinstance(i, dict) else i
                     for i in v if i not in (None, "")]
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


def _detect_subtype_heuristic(text: str) -> str:
    """Эвристика определения типа договора (DA preprocessing.extract_date logic)."""
    upper = text.upper()
    if "432" in upper or "ФИД" in upper or "ФИНАНСОВЫЙ РИСК" in upper:
        return "432"
    if "433" in upper or "ИМУЩЕСТВЕН" in upper:
        return "433"
    return "431"


def _extract_date_info(text: str) -> str:
    """Извлекает строки с датами из текста (DA preprocessing.extract_date)."""
    dates = re.findall(r"\d{2}[./]\d{2}[./]\d{4}", text)
    return ", ".join(set(dates)) if dates else ""


def _extract_objects_info(text: str) -> list[str]:
    """Извлекает упоминания объектов страхования (DA preprocessing.extract_objects_info)."""
    pattern = r"(?i)объект[^:]*:\s*([^
]+)"
    matches = re.findall(pattern, text)
    return list(set(m.strip() for m in matches if m.strip()))


def _extract_payments_section(text: str) -> str:
    """Извлекает секцию платежей (DA preprocessing.extract_table_section)."""
    start = text.upper().find("ДАТА ЗАКЛЮЧЕНИЯ")
    end = text.upper().find("ПРОЧИЕ ДАННЫЕ", start) if start != -1 else -1
    if start == -1:
        return ""
    return text[start:end].strip() if end != -1 else text[start:].strip()


# ---------------------------------------------------------------------------
# Инструменты
# ---------------------------------------------------------------------------

@tool(args_schema=DetectTypeInput)
def detect_responsibility_type(document_text: str) -> str:
    """Определяет тип договора страхования ответственности: 431, 432 или 433.
    Анализирует ключевые слова и маркеры в тексте.
    Возвращает {subtype, confidence, reasoning}.
    """
    try:
        subtype = _detect_subtype_heuristic(document_text)
        markers = {
            "431": ["третьи лица", "гражданская ответственность", "объекты страхования"],
            "432": ["финансовый риск", "фид", "432", "кредит"],
            "433": ["имущественная", "433", "склад", "здание"],
        }
        found = [kw for kw in markers.get(subtype, []) if kw.lower() in document_text.lower()]
        result = {
            "subtype": subtype,
            "confidence": "high" if found else "medium",
            "markers_found": found,
            "reasoning": f"Обнаружены маркеры типа {subtype}: {found}" if found
                         else f"По умолчанию тип {subtype}",
            "instruction": f"Используй subtype={subtype} в следующих инструментах.",
        }
        logger.info("detect_responsibility_type: subtype=%s confidence=%s", subtype, result["confidence"])
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(args_schema=BaseExtractInput)
def extract_responsibility_base(document_text: str, subtype: str = "431") -> str:
    """Извлекает базовые данные договора ответственности:
    номер, даты, страховые суммы, премия, стороны, риски.
    Адаптирует извлечение под тип (431/432/433).
    Блок DA: responsibility_431_prompt / responsibility_432_prompt.
    """
    try:
        date_info = _extract_date_info(document_text)
        objects_list = _extract_objects_info(document_text)
        objects_str = ";
".join(objects_list)
        payments_info = _extract_payments_section(document_text) if subtype == "432" else ""

        base_fields: dict[str, Any] = {
            "contract_number": None,
            "date_start": None,
            "date_end": None,
            "date_conclusion": None,
            "insurance_sum": None,
            "premium": None,
            "currency": None,
            "insurer": None,
            "policyholder": None,
            "beneficiary": None,
            "risks": [],
            "roles": {},
        }
        if subtype == "432":
            base_fields["payment_schedule"] = []
            base_fields["credit_limit"] = None

        schema: dict[str, Any] = {
            "subtype": subtype,
            "instruction": (
                f"Извлеки базовые данные договора ответственности типа {subtype}. "
                "Заполни все поля в 'extracted'. "
                "Роли: страховщик/страхователь/выгодоприобретатель. "
                "Риски — список строк."
            ),
            "date_info_hint": date_info,
            "objects_hint": objects_str,
            "payments_hint": payments_info,
            "extracted": base_fields,
        }
        logger.info("extract_responsibility_base: subtype=%s", subtype)
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(args_schema=ObjectsInput)
def extract_responsibility_objects(document_text: str, objects_hint: str = "") -> str:
    """Извлекает список объектов страхования из договора ответственности.
    Каждый объект: наименование, адрес, лимит ответственности, описание.
    Блок DA: objects_prompt (pipeline_431 и pipeline_433).
    """
    try:
        auto_objects = _extract_objects_info(document_text)
        hint = objects_hint or (";
".join(auto_objects) if auto_objects else "")
        schema: dict[str, Any] = {
            "instruction": (
                "Извлеки полный список объектов страхования. "
                "Для каждого объекта укажи: наименование, адрес (если есть), "
                "лимит ответственности (float), описание/назначение."
            ),
            "objects_hint": hint or "(не найдено в тексте)",
            "extracted": {
                "objects": [
                    {
                        "name": None,
                        "address": None,
                        "limit": None,
                        "description": None,
                    }
                ]
            },
            "agent_note": (
                "Верни список объектов в поле 'objects'. "
                "Если объект один — всё равно список с одним элементом."
            ),
        }
        logger.info("extract_responsibility_objects: подсказок=%d", len(auto_objects))
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(args_schema=FidInput)
def extract_responsibility_fid(document_text: str, fid_text: str = "") -> str:
    """Извлекает данные ФИД (финансово-имущественный документ) для типа 432.
    Если fid_text не передан — ищет ФИД-маркеры в основном тексте.
    Блок DA: fid_prompt (pipeline_432).
    """
    try:
        source = fid_text or document_text
        schema: dict[str, Any] = {
            "instruction": (
                "Извлеки данные ФИД: идентификатор ФИД, статус, "
                "дата выдачи, сумма (float), описание, связанные договоры."
            ),
            "fid_source": "fid_document" if fid_text else "main_document",
            "extracted": {
                "fid_id": None,
                "fid_status": None,
                "fid_date": None,
                "fid_amount": None,
                "fid_description": None,
                "related_contracts": [],
            },
            "agent_note": "Если ФИД не найден — верни все поля null.",
        }
        logger.info("extract_responsibility_fid: источник=%s", schema["fid_source"])
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(args_schema=ValidateInput)
def validate_responsibility_result(result_json: str, subtype: str = "431") -> str:
    """Валидирует результат разбора договора ответственности через Pydantic.
    Автоматически нормализует float-поля и даты.
    Возвращает {valid, subtype, data} или {valid: false, errors, data}.
    """
    try:
        raw = json.loads(result_json) if isinstance(result_json, str) else result_json
        raw["subtype"] = subtype
        for field in ("insurance_sum", "premium", "credit_limit"):
            if isinstance(raw.get(field), str):
                raw[field] = _parse_float(raw[field])
        if isinstance(raw.get("objects"), list):
            for obj in raw["objects"]:
                if isinstance(obj, dict) and isinstance(obj.get("limit"), str):
                    obj["limit"] = _parse_float(obj["limit"])
        from pydantic import ValidationError
        try:
            validated = ResponsibilityParseResult.model_validate(raw)
            clean = _strip_none(validated.model_dump(mode="json"))
            logger.info("validate_responsibility_result: OK subtype=%s", subtype)
            return json.dumps(
                {"valid": True, "subtype": subtype, "data": clean},
                ensure_ascii=False, indent=2,
            )
        except ValidationError as ve:
            errors = [
                f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
                for e in ve.errors()
            ]
            logger.warning("validate_responsibility_result: ошибки %s", errors)
            return json.dumps(
                {"valid": False, "subtype": subtype, "errors": errors, "data": _strip_none(raw)},
                ensure_ascii=False, indent=2,
            )
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool(args_schema=FixFieldInput)
def fix_responsibility_field(
    result_json: str, subtype: str, field_path: str, corrected_value: Any
) -> str:
    """Точечно исправляет поле в результате и перезапускает валидацию.
    Поддерживает вложенные пути: 'objects.0.limit', 'base.contract_number'.
    """
    try:
        data = json.loads(result_json) if isinstance(result_json, str) else result_json
        parts = field_path.split(".")
        node: Any = data
        for part in parts[:-1]:
            if isinstance(node, dict):
                node = node.setdefault(part, {})
            elif isinstance(node, list):
                node = node[int(part)]
        if isinstance(node, dict):
            node[parts[-1]] = corrected_value
        elif isinstance(node, list):
            node[int(parts[-1])] = corrected_value
        logger.info("fix_responsibility_field: %s исправлено (subtype=%s)", field_path, subtype)
        return validate_responsibility_result.invoke(
            {"result_json": json.dumps(data, ensure_ascii=False), "subtype": subtype}
        )
    except Exception as e:
        return json.dumps({"error": str(e)})
