import json
import logging
import re
from datetime import datetime

from langchain.tools import tool

logger = logging.getLogger("agent_tender")

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

    return {
        "id": idx + 1,
        "name": name,
        "type": doc_type,
        "mandatory": mandatory,
        "section_reference": str(doc.get("section_reference", "")).strip(),
        "requirements": str(doc.get("requirements", "")).strip(),
        "basis": str(doc.get("basis", "")).strip(),
    }


# --------------------------------------------------------------------------- #
#  Инструменты агента                                                          #
# --------------------------------------------------------------------------- #

@tool
def generate_document_list(query: str) -> str:
    """
    Генерирует структурированный JSON-список документов, требуемых от участника закупки.

    ⚠️ НЕ передавай полный текст документации! Передай ТОЛЬКО результаты анализа:
    {"procurement_subject":"Строительство объекта",
     "documents":[
       {"name":"Копия лицензии на строительную деятельность",
        "type":"лицензия","mandatory":true,
        "section_reference":"Раздел 3.2, п. 3.2.1",
        "requirements":"Нотариально заверенная копия, действующая на дату подачи",
        "basis":"Прямое требование"},
       {"name":"Свидетельство о членстве в СРО",
        "type":"свидетельство","mandatory":true,
        "section_reference":"Раздел 2.5",
        "requirements":"Действующее на дату подачи заявки",
        "basis":"Вытекает из предмета закупки (строительные работы)"}
     ]}
    """
    try:
        logger.debug("🔧 generate_document_list вызван (%d симв.)", len(query) if query else 0)

        # Если сам запрос пустой/пробелы — LLM не смогла выдать результат
        if not query or not query.strip():
            return json.dumps(
                {"error": "Пустой запрос инструмента (превышен лимит токенов LLM)"},
                ensure_ascii=False,
            )

        d = _parse_query(query, "generate_document_list")

        if d is None or not isinstance(d, dict):
            logger.warning(
                "⚠️ generate_document_list: получен не-JSON или не-dict, создаём скелет результата"
            )
            d = {
                "procurement_subject": "Не определён",
                "documents": [],
            }

        raw_docs = d.get("documents", [])
        if not isinstance(raw_docs, list):
            raw_docs = []

        # Оставляем только dict-элементы, чтобы _normalize_document не падал на doc.get(...)
        valid_docs = [doc for doc in raw_docs if isinstance(doc, dict)]
        skipped_count = len(raw_docs) - len(valid_docs)
        if skipped_count > 0:
            logger.warning(
                "⚠️ generate_document_list: пропущено %d не-dict документов из %d",
                skipped_count,
                len(raw_docs),
            )

        documents = [_normalize_document(doc, i) for i, doc in enumerate(valid_docs)]

        mandatory_count = sum(1 for doc in documents if doc["mandatory"])
        conditional_count = len(documents) - mandatory_count

        result = {
            "timestamp": datetime.now().isoformat(),
            "procurement_subject": str(d.get("procurement_subject", "Не определён")).strip(),
            "documents": documents,
            "summary": {
                "total": len(documents),
                "mandatory": mandatory_count,
                "conditional": conditional_count,
            },
        }
        logger.info(
            "✅ generate_document_list: список готов (%d документов, %d обязательных)",
            len(documents), mandatory_count,
        )
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ generate_document_list: ошибка %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)
