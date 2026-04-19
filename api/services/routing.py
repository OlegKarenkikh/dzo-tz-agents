"""
Реестр агентов и логика автоопределения типа документа.

Перенесено из api/app.py (TD-01).
"""
import logging

logger = logging.getLogger("api")

AGENT_REGISTRY: dict[str, dict] = {
    "dzo": {
        "name": "Инспектор ДЗО",
        "description": "Проверяет заявки ДЗО на полноту и соответствие требованиям",
        "decisions": ["Заявка полная", "Требуется доработка", "Требуется эскалация"],
        "auto_detect": {
            "priority": 10,
            "keywords": ["заявка на закупку", "инициатор", "форма тезис", "обоснование закупки", "дзо"],
        },
    },
    "tz": {
        "name": "Инспектор ТЗ",
        "description": "Анализирует технические задания на соответствие ГОСТ и внутренним стандартам",
        "decisions": ["Соответствует", "Требует доработки", "Не соответствует"],
        "auto_detect": {
            "priority": 80,
            "keywords": [
                "техническое задание", "техзадание", "технического задания",
                "terms of reference", "tor", "тз №", "тз к",
                "требования к поставке", "технические требования", "тз",
            ],
        },
    },
    "collector": {
        "name": "Сборщик документов ТО",
        "description": "Автоматизирует сбор и проверку анкет участников тендерного отбора",
        "decisions": ["documents_collected", "tool_error"],
        "auto_detect": {
            "priority": 90,
            "keywords": [
                "тендерный отбор", "анкета участника", "nda",
                "приглашение на участие", "сбор документов", "сбор анкет",
                "участники тендера", "участники то",
                "анкета участника тендерного отбора",
                "соглашение о неразглашении",
                "3115", "дит",
            ],
        },
    },
    "tender": {
        "name": "Парсер тендерной документации",
        "description": "Извлекает полный список документов, требуемых от участника закупки",
        "decisions": ["documents_found", "tool_error"],
        "auto_detect": {
            "priority": 100,
            "keywords": [
                "тендерная документация", "закупочная документация", "конкурсная документация",
                "аукционная документация", "извещение о закупке", "документация о закупке",
                "44-фз", "223-фз", "тендер",
                "страхование", "осаго", "каско", "дмс", "омс",
                "страховая премия", "страховая сумма", "полис",
                "франшиза", "лимит покрытия", "страховой случай",
                "страховщик", "перестрахование",
                "опо", "осгоп", "нс и болезней",
                "строительно-монтажных рисков", "смр",
                "страхование грузов", "страхование имущества",
                "страхование ответственности",
                "65.12", "65.11",
            ],
        },
    },
}


def _fallback_agent_id() -> str:
    if "dzo" in AGENT_REGISTRY:
        return "dzo"
    return next(iter(AGENT_REGISTRY.keys()), "dzo")


def resolve_agent(request) -> tuple[str, str | None]:
    """Определяет агента по содержимому запроса через keyword-matching."""
    combined = (request.text[:2000] + " " + request.subject + " " + request.filename).lower()
    profiles: list[tuple[int, str, list[str]]] = []
    for agent_id, info in AGENT_REGISTRY.items():
        auto_detect = info.get("auto_detect") or {}
        raw_keywords = auto_detect.get("keywords") or []
        keywords = [str(k).strip().lower() for k in raw_keywords if str(k).strip()]
        if not keywords:
            continue
        priority = int(auto_detect.get("priority", 0))
        profiles.append((priority, agent_id, sorted(keywords, key=len, reverse=True)))
    profiles.sort(key=lambda x: x[0], reverse=True)
    for _priority, agent_id, keywords in profiles:
        for kw in keywords:
            if kw in combined:
                logger.debug("resolve_agent: '%s' → %s (ключ: '%s')", request.subject[:50], agent_id, kw)
                return agent_id, kw
    return _fallback_agent_id(), None


def detect_agent_type(request) -> str:
    agent_type, _ = resolve_agent(request)
    return agent_type
