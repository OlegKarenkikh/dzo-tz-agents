import json
import re
from datetime import UTC, datetime

from langchain.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from shared.agent_tooling import invoke_agent_as_tool
from shared.logger import setup_logger

logger = setup_logger("agent_tender")

# --------------------------------------------------------------------------- #
#  Вспомогательные функции парсинга                                            #
# --------------------------------------------------------------------------- #

def _parse_query(query: str, tool_name: str):
    """Пытается распарсить query как JSON.

    Возвращает:
      - dict   — если успешно распарсен JSON
      - None   — если строка непустая, но не является JSON
      - {}     — если строка пустая/пробелы (обрыв из-за лимита токенов)
    """
    if not query or not query.strip():
        logger.warning("⚠️ %s: пустой query (вероятно, превышен лимит токенов)", tool_name)
        return {}
    q = query.strip()
    try:
        return json.loads(q)
    except json.JSONDecodeError:
        pass
    # Попытка 2: raw_decode извлекает первый валидный JSON, игнорируя хвостовой мусор.
    try:
        obj, _ = json.JSONDecoder().raw_decode(q)
        if isinstance(obj, dict):
            logger.debug(
                "✅ %s: JSON извлечён через raw_decode (trailing-мусор обрезан)",
                tool_name,
            )
            return obj
    except json.JSONDecodeError:
        pass
    # Попытка 3: цитируем незакавыченные ключи
    try:
        fixed = re.sub(r'(?<!["\w])([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'"\1":', q)
        if not fixed.startswith("{"):
            fixed = "{" + fixed + "}"
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    logger.warning(
        "⚠️ %s: query не является JSON (%d симв.): %s…",
        tool_name, len(q), q[:120],
    )
    return None  # None = непустой, но не JSON


# Допустимые типы документов
_VALID_TYPES = {
    "лицензия", "свидетельство", "копия", "оригинал", "форма",
    "декларация", "гарантия", "выписка", "справка", "сертификат",
    "договор", "протокол", "приказ", "устав", "иное",
}

# Стандартизированные категории (совместимы с tender-assistant)
_VALID_CATEGORIES = {
    "form",           # Заявки, анкеты, декларации (форма участника)
    "certificate",    # Лицензии, свидетельства, сертификаты, допуски
    "statement",      # Декларации, заявления, согласия
    "extract",        # Выписки, справки (ЕГРЮЛ, ФНС, реестры)
    "qualification",  # Подтверждение опыта, квалификации (договоры, акты)
    "other",          # Всё остальное (гарантии, балансы, доверенности)
}

# Маппинг типов dzo -> стандартная категория
_TYPE_TO_CATEGORY: dict[str, str] = {
    "форма": "form",
    "декларация": "statement",
    "лицензия": "certificate",
    "свидетельство": "certificate",
    "сертификат": "certificate",
    "выписка": "extract",
    "справка": "extract",
    "договор": "qualification",
    "протокол": "qualification",
    "копия": "qualification",
    "оригинал": "form",
    "гарантия": "other",
    "приказ": "other",
    "устав": "other",
    "иное": "other",
}


def _infer_category(doc_type: str) -> str:
    """Определяет стандартную категорию по типу документа."""
    return _TYPE_TO_CATEGORY.get(doc_type, "other")



def _normalize_document(doc: dict, idx: int) -> dict:
    """Нормализует и дополняет запись о документе обязательными полями."""
    name = str(doc.get("name", "")).strip()
    if not name:
        name = f"Документ {idx + 1}"

    doc_type = str(doc.get("type", "иное")).strip().lower()
    if doc_type not in _VALID_TYPES:
        doc_type = "иное"

    raw_mandatory = doc.get("mandatory", True)
    if isinstance(raw_mandatory, str):
        mandatory = raw_mandatory.lower() not in {"false", "нет", "0", "условный", "желательный"}
    else:
        mandatory = bool(raw_mandatory)

    category = _infer_category(doc_type)
    llm_category = str(doc.get("category", "")).strip().lower()
    if llm_category in _VALID_CATEGORIES:
        category = llm_category

    validity = str(doc.get("validity", "Не указан")).strip() or "Не указан"

    quote = str(doc.get("quote", "")).strip()
    if not quote:
        quote = str(doc.get("requirements", "")).strip()[:180]

    raw_part = str(doc.get("application_part", "")).strip().lower()
    application_part = raw_part if raw_part in {"qualification", "price", "other"} else "qualification"

    return {
        "id": idx + 1,
        "name": name,
        "type": doc_type,
        "category": category,
        "mandatory": mandatory,
        "section_reference": str(doc.get("section_reference", "")).strip(),
        "requirements": str(doc.get("requirements", "")).strip(),
        "validity": validity,
        "quote": quote,
        "application_part": application_part,
        "basis": str(doc.get("basis", "")).strip(),
    }


# --------------------------------------------------------------------------- #
#  Инструменты агента                                                          #
# --------------------------------------------------------------------------- #

class _DocItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = ""
    type: str = "иное"
    category: str = "other"
    mandatory: bool = True
    section_reference: str = ""
    requirements: str = ""
    validity: str = "Не указан"
    quote: str = ""
    application_part: str = "qualification"
    basis: str = "Прямое требование"


class _GenDocListInput(BaseModel):
    """Structured args — исключает ошибку 'Error invoking tool with kwargs'."""
    model_config = ConfigDict(extra="allow")
    procurement_subject: str = "Не определён"
    documents: list = Field(default_factory=list)
    decision: str = "ДОКУМЕНТАЦИЯ ПОЛНАЯ"
    procurement_type: str = "запрос_предложений"
    applicable_sections: int = 0
    documents_found: int = 0
    completeness_pct: float = 100.0
    critical_issues: list = Field(default_factory=list)
    recommendations: list = Field(default_factory=list)
    summary: str = ""


@tool(args_schema=_GenDocListInput)
def generate_document_list(
    procurement_subject: str = "Не определён",
    documents: list = None,
    decision: str = "ДОКУМЕНТАЦИЯ ПОЛНАЯ",
    procurement_type: str = "запрос_предложений",
    applicable_sections: int = 0,
    documents_found: int = 0,
    completeness_pct: float = 100.0,
    critical_issues: list = None,
    recommendations: list = None,
    summary: str = "",
) -> str:
    """
    Генерирует JSON-список документов и оценку полноты тендерной документации.
    Передаётся РЕЗУЛЬТАТ анализа (список документов + решение), НЕ полный текст документации.
    """
    try:
        raw = documents or []
        valid = []
        for item in raw:
            if hasattr(item, 'model_dump'):
                valid.append(item.model_dump())
            elif isinstance(item, dict):
                valid.append(item)
        normalized = [_normalize_document(doc, i) for i, doc in enumerate(valid)]
        mandatory_n = sum(1 for d in normalized if d["mandatory"])
        result = {
            "timestamp": datetime.now(UTC).isoformat(),
            "decision": decision,
            "procurement_type": procurement_type,
            "applicable_sections": applicable_sections,
            "documents_found": documents_found or len(normalized),
            "completeness_pct": completeness_pct,
            "critical_issues": critical_issues or [],
            "recommendations": recommendations or [],
            "summary": summary,
            "procurement_subject": str(procurement_subject).strip(),
            "documents": normalized,
            "doc_summary": {"total": len(normalized), "mandatory": mandatory_n, "conditional": len(normalized)-mandatory_n},
        }
        logger.info("✅ generate_document_list: %s | docs=%d, oblig=%d", decision, len(normalized), mandatory_n)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ generate_document_list: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def invoke_peer_agent(query: str) -> str:
    """
    Универсальный вызов другого агента как инструмента.

    Ожидает JSON:
    {"target_agent":"dzo|tz|tender|...","query_text":"...","subject":"...","sender":"..."}
    """
    try:
        d = _parse_query(query, "invoke_peer_agent")
        if not isinstance(d, dict):
            return json.dumps({"error": "query должен быть JSON-объектом"}, ensure_ascii=False)

        target_agent = str(d.get("target_agent", "")).strip()
        query_text = str(d.get("query_text", "")).strip()
        if not target_agent or not query_text:
            return json.dumps(
                {"error": "Обязательные поля: target_agent, query_text"},
                ensure_ascii=False,
            )

        result = invoke_agent_as_tool(
            source_agent="tender",
            target_agent=target_agent,
            chat_input=query_text,
            metadata={
                "delegated_by": "tender",
                "subject": str(d.get("subject", "")),
                "sender": str(d.get("sender", "")),
            },
        )

        return json.dumps(
            {
                "peerAgentResult": {
                    "target_agent": target_agent,
                    "output": result.get("output", ""),
                    "observations": result.get("observations", []),
                }
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error("❌ invoke_peer_agent(tender): ошибка %s", e)
        return json.dumps(
            {
                "peerAgentResult": {
                    "target_agent": "",
                    "output": "",
                    "observations": [],
                    "error": str(e),
                }
            },
            ensure_ascii=False,
        )
