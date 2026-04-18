"""
agent4_leasing_parser/tools.py
Инструменты LangChain для агента разбора договоров лизинга.
Каждый инструмент соответствует одному блоку DA leasing_pipeline.
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from shared.logger import setup_logger
from shared.schemas import LeasingParseResult

logger = setup_logger("agent_leasing")

# ---------------------------------------------------------------------------
# Pydantic-схемы аргументов
# ---------------------------------------------------------------------------

class ExtractBaseInput(BaseModel):
    model_config = ConfigDict(strict=True)
    document_text: str = Field(description="Полный текст документа лизинга")


class ExtractAdditionalInput(BaseModel):
    model_config = ConfigDict(strict=True)
    document_text: str = Field(description="Полный текст документа лизинга")
    table_text: str = Field(default="", description="Текст таблиц из docx-документа")


class ExtractRolesInput(BaseModel):
    model_config = ConfigDict(strict=True)
    document_text: str = Field(description="Полный текст документа лизинга")


class ExtractTerritoryInput(BaseModel):
    model_config = ConfigDict(strict=True)
    territory_raw: str = Field(description="Сырая строка территории страхования из base-блока")


class ExtractRisksInput(BaseModel):
    model_config = ConfigDict(strict=True)
    document_text: str = Field(description="Полный текст документа")
    rules: list[str] = Field(default_factory=list, description="Правила страхования")
    numbered_risks: list[str] = Field(default_factory=list, description="Явно перечисленные риски")


class ValidateLeasingInput(BaseModel):
    model_config = ConfigDict(strict=True)
    result_json: str = Field(description="JSON-строка собранного результата LeasingParseResult")


class FixFieldInput(BaseModel):
    model_config = ConfigDict(strict=True)
    result_json: str = Field(description="Текущий JSON результата")
    field_path: str = Field(description="Путь к полю для исправления, напр. 'base.policy_number'")
    corrected_value: Any = Field(description="Исправленное значение поля")


# ---------------------------------------------------------------------------
# Вспомогательные функции (зеркало DA utils)
# ---------------------------------------------------------------------------

MONTH_MAP = {
    "января": "01", "февраля": "02", "марта": "03",
    "апреля": "04", "мая": "05", "июня": "06",
    "июля": "07", "августа": "08", "сентября": "09",
    "октября": "10", "ноября": "11", "декабря": "12",
}

CURRENCY_MAP = {"RUR": 35, "USD": 53, "EUR": 29448516}

ROLE_ISN_MAP = {
    "страхователь": 430,
    "страховщик": 431,
    "собственник": 44090916,
    "лизингодатель": 3249377103,
    "лизингополучатель": 682566316,
    "выгодоприобретатель": 433,
}

_MAX_FIELD_LEN = 250
_SHORT_FIELD_LEN = 20


def _cut(value: Any, length: int = _MAX_FIELD_LEN) -> Any:
    """Обрезать строку до length символов; не-строки возвращает как есть."""
    if isinstance(value, str):
        return value[:length]
    return value


def _normalize_date(date_str: str) -> str:
    """Нормализовать строку даты к формату DD.MM.YYYY."""
    if not date_str or not isinstance(date_str, str):
        return ""
    cleaned = re.sub(r"[гг\.]+\s*$", "", date_str.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r'[^\w\s./\-«»"\']', "", cleaned)
    cleaned_lower = cleaned.lower()
    day_match = re.search(r'[«"`\'„]([0-9]{1,2})[»"\']', cleaned)
    day = day_match.group(1) if day_match else None
    if day is None:
        m = re.search(r"\b(\d{1,2})\b", cleaned)
        day = m.group(1) if m else None
    for month_ru, month_num in MONTH_MAP.items():
        if month_ru in cleaned_lower:
            year_m = re.search(r"(\d{4})", cleaned)
            if year_m and day:
                return f"{day.zfill(2)}.{month_num}.{year_m.group(1)}"
    return cleaned


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


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(float(value.replace(" ", "").replace(",", ".")))
        except (ValueError, TypeError):
            return None
    return None


def _strip_none(d: dict) -> dict:
    """Рекурсивно удаляет None и пустые строки из словаря."""
    result = {}
    for k, v in d.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        if isinstance(v, dict):
            sub = _strip_none(v)
            if sub:
                result[k] = sub
        elif isinstance(v, list):
            clean_list = []
            for item in v:
                if isinstance(item, dict):
                    sub = _strip_none(item)
                    if sub:
                        clean_list.append(sub)
                elif item not in (None, ""):
                    clean_list.append(item)
            if clean_list:
                result[k] = clean_list
        else:
            result[k] = v
    return result


# ---------------------------------------------------------------------------
# Инструменты
# ---------------------------------------------------------------------------

@tool(args_schema=ExtractBaseInput)
def extract_leasing_base(document_text: str) -> str:
    """Извлекает базовые поля договора лизинга: номер полиса, дата подписания,
    валюта, территория страхования, правила страхования, подписант, кадастровый номер.
    Возвращает JSON с извлечёнными полями.
    Блок DA: base_prompt / ainvoke(base_question).
    """
    try:
        logger.debug("🔧 extract_leasing_base вызван (длина текста: %d)", len(document_text))
        fields: dict[str, Any] = {
            "document_length": len(document_text),
            "instruction": (
                "Извлеки из текста договора лизинга следующие поля: "
                "Номер полиса, Дата подписания, Валюта (RUR/USD/EUR), "
                "Территория страхования, Правила страхования, Правила страхования список, "
                "Подписант со стороны ИГС, Кадастровый номер, Индекс адреса, "
                "Генеральный договор, Риски."
            ),
            "extracted": {
                "policy_number": None,
                "date_sign": None,
                "currency": None,
                "territory": None,
                "insurance_rules": None,
                "insurance_rules_list": [],
                "signer_igs": None,
                "cadastre_number": None,
                "postal_code": None,
                "general_contract": None,
                "risks_list": [],
            },
            "validation_status": "pending",
            "agent_note": (
                "Заполни поле 'extracted' на основе документа. "
                "Для Валюты используй только RUR, USD, EUR. "
                "Дату приводи к формату DD.MM.YYYY."
            ),
        }
        logger.info("✅ extract_leasing_base: шаблон сформирован")
        return json.dumps(fields, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("❌ extract_leasing_base: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=ExtractAdditionalInput)
def extract_leasing_additional(document_text: str, table_text: str = "") -> str:
    """Извлекает дополнительные поля: объекты страхования, платежи страховой суммы,
    общие платежи, дату начала/окончания, франшизу, класс объекта.
    Блок DA: additional_prompt / ainvoke(additional_question).
    """
    try:
        logger.debug("🔧 extract_leasing_additional вызван")
        schema: dict[str, Any] = {
            "instruction": (
                "Извлеки из текста: Дата начала, Дата окончания, Класс объекта страхования, "
                "Статус валидации, Франшиза (число), "
                "Объекты страхования (список: Серийный номер, Название объекта страхования, "
                "Платежи страховой суммы: [{Номер, Ставка премии, Дата начала, Дата окончания, "
                "Страховая премия, Сумма}]), "
                "Платежи (список: [{Номер, Срок оплаты, Сумма, Дата начала платежа, Дата окончания платежа}])."
            ),
            "has_table_text": bool(table_text),
            "extracted": {
                "date_start": None,
                "date_end": None,
                "object_class": None,
                "franchise": None,
                "validation_status": None,
                "insurance_objects": [],
                "payments": [],
            },
            "agent_note": (
                "Заполни поле 'extracted'. Платежи страховой суммы находятся ВНУТРИ каждого объекта. "
                "Общие Платежи — отдельный список. Все суммы — числа. Даты — DD.MM.YYYY."
            ),
        }
        logger.info("✅ extract_leasing_additional: шаблон сформирован")
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("❌ extract_leasing_additional: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=ExtractRolesInput)
def extract_leasing_roles(document_text: str) -> str:
    """Извлекает участников (роли) договора: страхователь, страховщик,
    лизингодатель, лизингополучатель, собственник, выгодоприобретатель.
    Для каждого: Роль, Название организации, ИНН, Адрес.
    Блок DA: roles_prompt + roles_add_prompt / ainvoke(roles_*_question).
    """
    try:
        logger.debug("🔧 extract_leasing_roles вызван")
        schema: dict[str, Any] = {
            "instruction": (
                "Извлеки всех участников договора. Для каждого укажи:"
                " Роль (страхователь/страховщик/лизингодатель/лизингополучатель/собственник/выгодоприобретатель),"
                " Название организации, ИНН, Адрес."
                " Если одна организация имеет несколько ролей — запиши их через запятую в поле Роль."
            ),
            "role_isn_map": ROLE_ISN_MAP,
            "extracted": [],
            "agent_note": "Верни список объектов в поле 'extracted'.",
        }
        logger.info("✅ extract_leasing_roles: шаблон сформирован")
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("❌ extract_leasing_roles: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=ExtractTerritoryInput)
def extract_leasing_territory(territory_raw: str) -> str:
    """Детализирует территорию страхования: страна, регион, город, улица, дом, строение.
    Принимает сырую строку территории из base-блока.
    Блок DA: territory_prompt / ainvoke(territory_question).
    """
    try:
        logger.debug("🔧 extract_leasing_territory вызван")
        schema: dict[str, Any] = {
            "territory_raw": _cut(territory_raw),
            "instruction": (
                "Разбери строку территории страхования на компоненты: "
                "Страна, Регион, Город, Улица (до 250 символов), Дом (до 20 символов), "
                "Строение (до 20 символов). "
                "Также укажи поле 'Территория до детализации' — исходную строку без изменений."
            ),
            "extracted": {
                "territory_raw": _cut(territory_raw),
                "country": None,
                "region": None,
                "city": None,
                "street": None,
                "house": None,
                "building": None,
            },
            "agent_note": "Заполни поле 'extracted'. Все строки обрезай: Улица до 250, Дом/Строение до 20 символов.",
        }
        logger.info("✅ extract_leasing_territory: шаблон сформирован")
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("❌ extract_leasing_territory: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=ExtractRisksInput)
def extract_leasing_risks(
    document_text: str,
    rules: list[str] | None = None,
    numbered_risks: list[str] | None = None,
) -> str:
    """Определяет застрахованные риски по правилам страхования.
    Если риски уже перечислены в numbered_risks — маппит их.
    Иначе — запрашивает у агента.
    Блок DA: risks_prompt / ainvoke(risks_question).
    """
    rules = rules or []
    numbered_risks = numbered_risks or []
    try:
        logger.debug("🔧 extract_leasing_risks вызван")
        schema: dict[str, Any] = {
            "instruction": (
                "Определи застрахованные риски по тексту договора. "
                "Если risks_from_doc не пуст — используй их. "
                "Иначе найди секцию 'Застрахованные риски' и извлеки все риски. "
                "Для каждого риска определи short_name, classisn, ruleisn."
            ),
            "rules": rules,
            "risks_from_doc": numbered_risks,
            "extracted": [],
            "agent_note": "Верни список рисков в поле 'extracted': [{short_name, classisn, ruleisn}].",
        }
        logger.info("✅ extract_leasing_risks: шаблон сформирован")
        return json.dumps(schema, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("❌ extract_leasing_risks: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=ValidateLeasingInput)
def validate_leasing_result(result_json: str) -> str:
    """Валидирует собранный результат LeasingParseResult через Pydantic.
    Возвращает {valid: true, data: {...}} или {valid: false, errors: [...], data: {...}}.
    Автоматически нормализует даты и обрезает строки до допустимых длин.
    """
    try:
        logger.debug("🔧 validate_leasing_result вызван")
        raw = json.loads(result_json) if isinstance(result_json, str) else result_json

        # Нормализация дат в base-блоке
        base = raw.get("base", {})
        for date_field in ("date_sign", "date_start", "date_end"):
            if isinstance(base.get(date_field), str):
                base[date_field] = _normalize_date(base[date_field])

        # Обрезка строк
        for field in ("policy_number", "signer_igs"):
            if isinstance(base.get(field), str):
                base[field] = _cut(base[field])

        address = base.get("address", {})
        if isinstance(address, dict):
            for short_f in ("house", "building", "cadastre_number"):
                if isinstance(address.get(short_f), str):
                    address[short_f] = _cut(address[short_f], _SHORT_FIELD_LEN)
            for long_f in ("country", "city", "street", "territory_raw"):
                if isinstance(address.get(long_f), str):
                    address[long_f] = _cut(address[long_f])

        from pydantic import ValidationError
        try:
            validated = LeasingParseResult.model_validate(raw)
            clean = _strip_none(validated.model_dump(mode="json"))
            logger.info("✅ validate_leasing_result: валидация прошла успешно")
            return json.dumps({"valid": True, "data": clean}, ensure_ascii=False, indent=2)
        except ValidationError as ve:
            errors = [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in ve.errors()]
            logger.warning("⚠️ validate_leasing_result: ошибки %s", errors)
            return json.dumps(
                {"valid": False, "errors": errors, "data": _strip_none(raw)},
                ensure_ascii=False,
                indent=2,
            )
    except Exception as e:
        logger.error("❌ validate_leasing_result: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=FixFieldInput)
def fix_leasing_field(result_json: str, field_path: str, corrected_value: Any) -> str:
    """Точечно исправляет одно поле в результате разбора.
    field_path использует точечную нотацию: 'base.policy_number', 'roles.0.inn'.
    После исправления автоматически перезапускает validate_leasing_result.
    """
    try:
        logger.debug("🔧 fix_leasing_field: path=%s", field_path)
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

        logger.info("✅ fix_leasing_field: поле '%s' исправлено", field_path)
        return validate_leasing_result.invoke({"result_json": json.dumps(data, ensure_ascii=False)})
    except Exception as e:
        logger.error("❌ fix_leasing_field: ошибка %s", e)
        return json.dumps({"error": str(e)})
