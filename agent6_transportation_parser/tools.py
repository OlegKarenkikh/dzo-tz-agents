"""
agent6_transportation_parser/tools.py
Инструменты LangChain для агента разбора заявок на страхование грузоперевозок.
Каждый инструмент соответствует одному блоку DA transportation_pipeline.
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from shared.logger import setup_logger
from shared.schemas import TransportParseResult

logger = setup_logger("agent_transportation")

# ---------------------------------------------------------------------------
# Справочник видов перевозки (зеркало DA transport_types CSV)
# ---------------------------------------------------------------------------
TRANSPORT_TYPES = [
    "Автомобильный транспорт",
    "Железнодорожный транспорт",
    "Авиационный транспорт",
    "Морской транспорт",
    "Речной транспорт",
    "Смешанный транспорт",
    "Почтовые отправления",
    "Курьерская доставка",
]

# ---------------------------------------------------------------------------
# Pydantic-схемы аргументов
# ---------------------------------------------------------------------------

class ExtractTransportBaseInput(BaseModel):
    model_config = ConfigDict(strict=True)
    document_text: str = Field(description="Полный текст заявки/договора перевозки")


class ExtractTransportRouteInput(BaseModel):
    model_config = ConfigDict(strict=True)
    document_text: str = Field(description="Полный текст документа")


class ExtractTransportAdditionalInput(BaseModel):
    model_config = ConfigDict(strict=True)
    document_text: str = Field(description="Полный текст документа")


class ResolveTransportTypeInput(BaseModel):
    model_config = ConfigDict(strict=True)
    transport_types_raw: list[str] = Field(
        description="Список видов перевозки, извлечённых из документа"
    )


class ValidateTransportInput(BaseModel):
    model_config = ConfigDict(strict=True)
    result_json: str = Field(description="JSON-строка собранного результата TransportParseResult")


class FixTransportFieldInput(BaseModel):
    model_config = ConfigDict(strict=True)
    result_json: str = Field(description="Текущий JSON результата")
    field_path: str = Field(description="Путь к полю, напр. \'cargo_weight\'")
    corrected_value: Any = Field(description="Исправленное значение поля")


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _strip_none(d: dict) -> dict:
    """Рекурсивно удаляет None, пустые строки, пустые списки и словари."""
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


def _validate_weight(value: Any) -> float | None:
    """Парсит вес: если тонны — конвертирует в кг (DA PostProcessing.validate_cargo_weight)."""
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return None
    s = str(value).lower()
    num = _parse_float(re.sub(r"[^\d.,]", "", s))
    if num is None:
        return None
    if "тонн" in s or s.strip().endswith("т"):
        num *= 1000
    return num


def _format_route(departure: str, destination: str, via: list[str] | None = None) -> str:
    """Формирует строку маршрута: А → В → Б (DA PostProcessing.format_route)."""
    parts = [departure]
    if via:
        parts.extend(via)
    parts.append(destination)
    return " → ".join(p for p in parts if p)


def _resolve_type(raw: str, types_list: list[str]) -> str | None:
    """Нечёткое сопоставление вида перевозки со справочником."""
    cleaned = re.sub(r"[^\w\s]", "", raw.strip()).lower()
    mapping = {re.sub(r"[^\w\s]", "", t).lower(): t for t in types_list}
    return mapping.get(cleaned)


# ---------------------------------------------------------------------------
# Инструменты
# ---------------------------------------------------------------------------

@tool(args_schema=ExtractTransportBaseInput)
def extract_transport_base(document_text: str) -> str:
    """Извлекает базовые поля заявки на страхование грузоперевозки:
    страхователь, наименование груза, страховая сумма, премия, валюта,
    дата начала и окончания страхования, номер полиса/заявки.
    Блок DA: base_prompt / ainvoke(base_prompt).
    """
    try:
        logger.debug("🔧 extract_transport_base вызван (длина текста: %d)", len(document_text))
        schema: dict[str, Any] = {
            "instruction": (
                "Извлеки из текста заявки: Страхователь (название, ИНН, адрес), "
                "Наименование груза, Страховая сумма (число), Страховая премия (число), "
                "Валюта (RUR/USD/EUR), Дата начала страхования (DD.MM.YYYY), "
                "Дата окончания страхования (DD.MM.YYYY), Номер заявки/полиса."
            ),
            "extracted": {
                "policy_number": None,
                "insurer": None,
                "insurer_inn": None,
                "cargo_name": None,
                "insurance_sum": None,
                "premium": None,
                "currency": None,
                "date_start": None,
                "date_end": None,
            },
            "agent_note": (
                "Заполни поле \'extracted\'. Суммы — числа float. "
                "Валюта: только RUR, USD, EUR. Даты: DD.MM.YYYY."
            ),
        }
        logger.info("✅ extract_transport_base: шаблон сформирован")
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("❌ extract_transport_base: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=ExtractTransportRouteInput)
def extract_transport_route(document_text: str) -> str:
    """Извлекает и структурирует маршрут перевозки груза:
    пункт отправления, пункты перегрузки (если есть), пункт назначения.
    Определяет, указан ли маршрут явно.
    Блок DA: extract_route_prompt + transform_route_prompt.
    """
    try:
        logger.debug("🔧 extract_transport_route вызван")
        schema: dict[str, Any] = {
            "instruction": (
                "Определи маршрут перевозки. Укажи: "
                "\'route_specified\': true/false (указан ли маршрут явно), "
                "\'departure\': пункт отправления, "
                "\'destination\': пункт назначения, "
                "\'via\': список пунктов перегрузки (может быть пустым), "
                "\'route_string\': строка формата \'А → Б\' или \'А → В → Б\'."
            ),
            "extracted": {
                "route_specified": False,
                "departure": None,
                "destination": None,
                "via": [],
                "route_string": None,
                "route_raw": None,
            },
            "agent_note": (
                "Разделители в маршруте: -, –, —, →, запятая. "
                "Если маршрут не указан явно — route_specified=false, остальные поля null."
            ),
        }
        logger.info("✅ extract_transport_route: шаблон сформирован")
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("❌ extract_transport_route: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=ExtractTransportAdditionalInput)
def extract_transport_additional(document_text: str) -> str:
    """Извлекает дополнительные поля заявки на перевозку:
    вид перевозки груза, вес груза (число + единица), упаковка,
    особые условия, количество мест, марка/модель ТС.
    Блок DA: additional_prompt / ainvoke(additional_prompt).
    """
    try:
        logger.debug("🔧 extract_transport_additional вызван")
        schema: dict[str, Any] = {
            "instruction": (
                "Извлеки из текста: Вид перевозки груза (список строк), "
                "Вес груза (строка с единицей, напр. \'10 тонн\' или \'500 кг\'), "
                "Упаковка, Особые условия перевозки, "
                "Количество мест (число), Марка/модель ТС (если указана)."
            ),
            "extracted": {
                "transport_types_raw": [],
                "cargo_weight_raw": None,
                "packaging": None,
                "special_conditions": None,
                "cargo_places": None,
                "vehicle_info": None,
            },
            "agent_note": (
                "transport_types_raw — список строк. "
                "cargo_weight_raw — строка как есть (напр. \'10 тонн\', \'500 кг\'). "
                "Числа не округляй."
            ),
        }
        logger.info("✅ extract_transport_additional: шаблон сформирован")
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("❌ extract_transport_additional: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=ResolveTransportTypeInput)
def resolve_transport_type(transport_types_raw: list[str]) -> str:
    """Сопоставляет извлечённые виды перевозки со справочником TRANSPORT_TYPES.
    Если одно совпадение — возвращает его. Если несколько — возвращает список.
    Блок DA: get_transport_types_list() + type/several_types prompt.
    """
    try:
        logger.debug("🔧 resolve_transport_type: %s", transport_types_raw)
        resolved = []
        unresolved = []
        for raw in transport_types_raw:
            match = _resolve_type(raw, TRANSPORT_TYPES)
            if match:
                resolved.append(match)
            else:
                unresolved.append(raw)

        result: dict[str, Any] = {
            "transport_types_list": TRANSPORT_TYPES,
            "input_raw": transport_types_raw,
            "resolved": list(set(resolved)),
            "unresolved": unresolved,
            "instruction": (
                "Для каждого элемента из \'unresolved\' найди наиближайшее значение "
                "из \'transport_types_list\' и добавь в \'resolved\'."
            ) if unresolved else "",
            "agent_note": "Верни финальный список resolved как transport_type в результат.",
        }
        logger.info("✅ resolve_transport_type: resolved=%s", result["resolved"])
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("❌ resolve_transport_type: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=ValidateTransportInput)
def validate_transport_result(result_json: str) -> str:
    """Валидирует собранный результат TransportParseResult через Pydantic.
    Автоматически конвертирует вес в кг (если тонны).
    Возвращает {valid: true, data: {...}} или {valid: false, errors: [...], data: {...}}.
    """
    try:
        logger.debug("🔧 validate_transport_result вызван")
        raw = json.loads(result_json) if isinstance(result_json, str) else result_json

        # Автонормализация веса
        w = raw.get("cargo_weight_raw") or raw.get("cargo_weight")
        if w and raw.get("cargo_weight") is None:
            raw["cargo_weight"] = _validate_weight(w)

        # Автонормализация float-полей
        for field in ("insurance_sum", "premium", "cargo_weight"):
            if isinstance(raw.get(field), str):
                raw[field] = _parse_float(raw[field])

        from pydantic import ValidationError
        try:
            validated = TransportParseResult.model_validate(raw)
            clean = _strip_none(validated.model_dump(mode="json"))
            logger.info("✅ validate_transport_result: валидация прошла успешно")
            return json.dumps({"valid": True, "data": clean}, ensure_ascii=False, indent=2)
        except ValidationError as ve:
            errors = [f"{\'.\'join(str(x) for x in e[\'loc\'])}: {e[\'msg\']}" for e in ve.errors()]
            logger.warning("⚠️ validate_transport_result: ошибки %s", errors)
            return json.dumps(
                {"valid": False, "errors": errors, "data": _strip_none(raw)},
                ensure_ascii=False, indent=2,
            )
    except Exception as e:
        logger.error("❌ validate_transport_result: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=FixTransportFieldInput)
def fix_transport_field(result_json: str, field_path: str, corrected_value: Any) -> str:
    """Точечно исправляет одно поле в результате разбора перевозки.
    field_path использует точечную нотацию: \'cargo_weight\', \'insurer\'.
    После исправления автоматически перезапускает validate_transport_result.
    """
    try:
        logger.debug("🔧 fix_transport_field: path=%s", field_path)
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
        logger.info("✅ fix_transport_field: поле \"%s\" исправлено", field_path)
        return validate_transport_result.invoke(
            {"result_json": json.dumps(data, ensure_ascii=False)}
        )
    except Exception as e:
        logger.error("❌ fix_transport_field: ошибка %s", e)
        return json.dumps({"error": str(e)})
