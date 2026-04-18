"""
agent5_osago_parser/tools.py
Инструменты LangChain для агента разбора документов ОСАГО.
"""
from __future__ import annotations

import json
from typing import Any

from langchain.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from shared.logger import setup_logger
from shared.schemas import OsagoParseResult

logger = setup_logger("agent_osago")


class ExtractOsagoBaseInput(BaseModel):
    model_config = ConfigDict(strict=True)
    document_text: str = Field(description="Полный текст заявления/письма ОСАГО")


class ExtractOsagoAdditionalInput(BaseModel):
    model_config = ConfigDict(strict=True)
    document_text: str = Field(description="Полный текст заявления/письма ОСАГО")


class ValidateOsagoInput(BaseModel):
    model_config = ConfigDict(strict=True)
    result_json: str = Field(description="JSON-строка собранного результата OsagoParseResult")


class FixOsagoFieldInput(BaseModel):
    model_config = ConfigDict(strict=True)
    result_json: str = Field(description="Текущий JSON результата")
    field_path: str = Field(description="Путь к полю, напр. 'base.vehicle_number'")
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
        else:
            result[k] = v
    return result


@tool(args_schema=ExtractOsagoBaseInput)
def extract_osago_base(document_text: str) -> str:
    """Извлекает базовые поля заявления ОСАГО:
    страхователь, владелец ТС, марка/модель авто,
    гос номер, вин, тип ТС, цель использования.
    Блок DA: base_prompt / ainvoke(base_question).
    """
    try:
        logger.debug("🔧 extract_osago_base вызван")
        schema: dict[str, Any] = {
            "instruction": (
                "Извлеки из текста: Страхователь (название, ИНН, адрес), "
                "Владелец ТС (название, ИНН), Марка ТС, Модель ТС, "
                "Гос. номер ТС, ВИН, Тип ТС, Цель использования, "
                "Год выпуска, Дата начала страхования, Дата окончания страхования."
            ),
            "gaz_flag_hint": "Если в тексте есть 'Просьба выставить счет на Е-ОСАГО' — Страхователь=Газпром.",
            "extracted": {
                "insurer": None,
                "ts_owner": None,
                "vehicle_brand": None,
                "vehicle_model": None,
                "vehicle_number": None,
                "vin": None,
                "ts_type": None,
                "usage_purpose": None,
                "year": None,
                "date_start": None,
                "date_end": None,
            },
            "agent_note": "Даты — DD.MM.YYYY. Страхователь — объект с полями name, inn, address.",
        }
        logger.info("✅ extract_osago_base: шаблон сформирован")
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("❌ extract_osago_base: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=ExtractOsagoAdditionalInput)
def extract_osago_additional(document_text: str) -> str:
    """Извлекает дополнительные технические характеристики ТС:
    мощность, максимальная масса, разрешённая максимальная масса (РММ),
    количество мест, грузоподъёмность, категория (ТС с прицепом/без).
    Блок DA: additional_prompt / ainvoke(additional_question).
    """
    try:
        logger.debug("🔧 extract_osago_additional вызван")
        schema: dict[str, Any] = {
            "instruction": (
                "Извлеки из текста: Мощность (в лошадиных силах), "
                "Максимальная мощность (кВт), Максимальная масса (т), "
                "Разрешённая максимальная масса (РММ) (т), Количество мест, Грузоподъёмность (т), "
                "Категория ТС (если есть прицеп — 'с прицепом', иначе 'без прицепа')."
            ),
            "extracted": {
                "power_hp": None,
                "power_kw": None,
                "max_mass": None,
                "permitted_max_mass": None,
                "seats_count": None,
                "cargo_capacity": None,
                "category": None,
            },
            "agent_note": "Числа — в числовом формате (float). Если не найдено — null.",
        }
        logger.info("✅ extract_osago_additional: шаблон сформирован")
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("❌ extract_osago_additional: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=ValidateOsagoInput)
def validate_osago_result(result_json: str) -> str:
    """Валидирует собранный результат OsagoParseResult через Pydantic.
    Возвращает {valid: true, data: {...}} или {valid: false, errors: [...], data: {...}}.
    """
    try:
        logger.debug("🔧 validate_osago_result вызван")
        raw = json.loads(result_json) if isinstance(result_json, str) else result_json

        from pydantic import ValidationError
        try:
            validated = OsagoParseResult.model_validate(raw)
            clean = _strip_none(validated.model_dump(mode="json"))
            logger.info("✅ validate_osago_result: валидация прошла успешно")
            return json.dumps({"valid": True, "data": clean}, ensure_ascii=False, indent=2)
        except ValidationError as ve:
            errors = [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in ve.errors()]
            logger.warning("⚠️ validate_osago_result: ошибки %s", errors)
            return json.dumps(
                {"valid": False, "errors": errors, "data": _strip_none(raw)},
                ensure_ascii=False,
                indent=2,
            )
    except Exception as e:
        logger.error("❌ validate_osago_result: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=FixOsagoFieldInput)
def fix_osago_field(result_json: str, field_path: str, corrected_value: Any) -> str:
    """Точечно исправляет одно поле в результате разбора ОСАГО.
    После исправления автоматически перезапускает validate_osago_result.
    """
    try:
        logger.debug("🔧 fix_osago_field: path=%s", field_path)
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
        logger.info("✅ fix_osago_field: поле '%s' исправлено", field_path)
        return validate_osago_result.invoke({"result_json": json.dumps(data, ensure_ascii=False)})
    except Exception as e:
        logger.error("❌ fix_osago_field: ошибка %s", e)
        return json.dumps({"error": str(e)})
