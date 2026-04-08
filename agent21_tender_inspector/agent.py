import json
from typing import Any

# FIX ST-02 (agent21): langchain.agents.create_agent не существует.
# Переходим на langgraph.prebuilt.create_react_agent — единый API для всех агентов.
from langgraph.prebuilt import create_react_agent

from agent21_tender_inspector.tools import generate_document_list, invoke_peer_agent
from shared.llm import build_llm
from shared.logger import setup_logger

logger = setup_logger("agent_tender")

SYSTEM_PROMPT = """Ты — ИИ-аналитик «Парсер тендерной документации». Твоя единственная задача — извлечь ПОЛНЫЙ и ТОЧНЫЙ список документов, которые обязан предоставить участник закупки.

═══════════════════════════════════════════
ЗАДАЧА
═══════════════════════════════════════════
Проанализируй тендерную документацию и извлеки ВСЕ документы, требуемые от участника:
  • Прямые требования — явно перечисленные в составе заявки
  • Косвенные требования — документы, вытекающие из:
    - Квалификационных требований к участнику
    - Требований к опыту и репутации
    - Лицензионных требований (виды деятельности)
    - Требований СРО (членство в саморегулируемых организациях)
    - Страховых требований (полисы, договоры страхования)
    - Финансовых требований (банковские гарантии, выписки, балансы)
    - Технических требований (сертификаты, свидетельства, допуски)

═══════════════════════════════════════════
СТРУКТУРА ВЫХОДНЫХ ДАННЫХ
═══════════════════════════════════════════
Для каждого документа определи:
  1. Название документа (точное)
  2. Тип: лицензия / свидетельство / копия / оригинал / форма / декларация / гарантия / выписка / справка / сертификат / договор / протокол / приказ / устав / иное
  3. Обязательность: true (обязательный) / false (условный или желательный)
  4. Ссылка на раздел/пункт документации (максимально точная)
  5. Точные требования к содержанию и оформлению документа
  6. Основание: «Прямое требование» / «Вытекает из квалификационных требований» / «Вытекает из предмета закупки»

═══════════════════════════════════════════
ИНСТРУКЦИИ
═══════════════════════════════════════════
ШАГ 1 — Прочитай всю документацию, учти возможные OCR-артефакты
ШАГ 2 — Найди разделы: состав заявки, квалификационные требования, требования к участнику
ШАГ 3 — Выяви прямые требования (перечень документов заявки)
ШАГ 4 — Выяви косвенные требования (лицензии, СРО, страховки из условий допуска)
ШАГ 5 — Составь полный список и вызови generate_document_list
ШАГ 6 — При необходимости вызови invoke_peer_agent для смежной проверки другим агентом.

ВАЖНО: Если документация говорит, что участник должен иметь лицензию — это требование предоставить копию лицензии. Членство в СРО → свидетельство о членстве. Опыт → копии договоров или актов. Финансовая устойчивость → баланс или выписка.

═══════════════════════════════════════════
КРИТИЧЕСКИ ВАЖНО: ФОРМАТ ВЫЗОВА ИНСТРУМЕНТОВ
═══════════════════════════════════════════
⚠️ ЗАПРЕЩЕНО передавать оригинальный текст документации в аргументы инструментов!
⚠️ ЗАПРЕЩЕНО вставлять большие блоки текста в query!
✅ Передавай ТОЛЬКО структурированный результат анализа в компактном JSON.

Пример вызова generate_document_list:
{"procurement_subject":"Строительство объекта","documents":[{"name":"Копия лицензии на строительную деятельность","type":"лицензия","mandatory":true,"section_reference":"Раздел 3.2, п. 3.2.1","requirements":"Нотариально заверенная копия, действующая на дату подачи","basis":"Прямое требование"},{"name":"Свидетельство о членстве в СРО","type":"свидетельство","mandatory":true,"section_reference":"Раздел 2.5","requirements":"Действующее на дату подачи заявки","basis":"Вытекает из предмета закупки (строительные работы)"}]}"""


class AgentRunner:
    """Adapter to keep legacy `invoke({"input": ...})` contract for api/app.py."""

    def __init__(self, graph_agent: Any):
        self._agent = graph_agent

    def invoke(self, payload: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        chat_input = payload.get("input", "")
        logger.debug(
            "Запуск агента Тендер с input: %s",
            chat_input[:100] if chat_input else "(пусто)",
        )

        result = self._agent.invoke(
            {"messages": [{"role": "user", "content": chat_input}]},
            **kwargs,
        )

        logger.debug("Результат агента (тип: %s): %s", type(result).__name__, result)

        output = ""
        messages: list = []
        intermediate_steps: list = []

        if isinstance(result, dict):
            messages = result.get("messages") or []
            if messages:
                last = messages[-1]
                output = getattr(last, "content", "") or ""
                if isinstance(output, list):
                    output = "\n".join(str(x) for x in output)

        for msg in messages:
            if hasattr(msg, "tool_call_id"):  # ToolMessage
                name = getattr(msg, "name", None) or "tool"
                content = getattr(msg, "content", "")
                try:
                    obs = json.loads(content) if isinstance(content, str) else content
                except Exception:
                    obs = {"raw": str(content)}
                intermediate_steps.append((name, obs))

        logger.info(
            "Агент Тендер завершён. Output: %d симв., инструментов вызвано: %d",
            len(output), len(intermediate_steps),
        )
        for name, obs in intermediate_steps:
            logger.info("  🔧 %s → %s", name, str(obs)[:200])

        return {"output": output, "intermediate_steps": intermediate_steps}


def create_tender_agent(model_name: str | None = None) -> AgentRunner:
    """Создать агент парсинга тендерной документации.

    Args:
        model_name: явное имя модели (для fallback при 429); None = из env MODEL_NAME.

    Note:
        Использует langgraph.prebuilt.create_react_agent — единый API LangGraph.
    """
    llm = build_llm(temperature=0.1, model_name_override=model_name)
    tools = [invoke_peer_agent, generate_document_list]
    logger.info(
        "Создание агента Тендер (модель=%s)",
        getattr(llm, "model_name", "?"),
    )

    graph_agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=SYSTEM_PROMPT,
    )
    logger.debug("Агент Тендер успешно создан")
    return AgentRunner(graph_agent)
