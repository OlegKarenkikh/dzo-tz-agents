import json
from datetime import datetime
from html import escape as html_escape

from langchain.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from shared.agent_tooling import invoke_agent_as_tool
from shared.logger import setup_logger

logger = setup_logger("agent_dzo")


# ---------------------------------------------------------------------------
# Pydantic-схемы аргументов (args_schema).
# Заменяют паттерн query: str + json.loads(query).
# Это снижает частоту ошибок парсинга LLM и даёт явную OpenAPI-документацию.
# ---------------------------------------------------------------------------

class ChecklistItem(BaseModel):
    model_config = ConfigDict(strict=True)

    field: str
    status: str  # "Да" | "Нет" | "ОК"
    comment: str = ""


class ValidationReportInput(BaseModel):
    model_config = ConfigDict(strict=True)

    decision: str = Field(
        default="Не определено",
        description="Итоговое решение: 'Заявка полная' | 'Требуется доработка' | 'Требуется эскалация'",
    )
    checklist_attachments: list[ChecklistItem] = Field(default_factory=list)
    checklist_required: list[ChecklistItem] = Field(default_factory=list)
    checklist_additional: list[ChecklistItem] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


class Supplier(BaseModel):
    model_config = ConfigDict(strict=True)

    inn: str = ""
    name: str = ""


class TezisFormInput(BaseModel):
    model_config = ConfigDict(strict=True)

    procurement_subject: str = Field(default="", description="Предмет закупки")
    justification: str | None = None
    budget: str | None = None
    initiator_name: str = ""
    initiator_contacts: str = ""
    budget_manager: str | None = None
    recommended_suppliers: list[Supplier] = Field(default_factory=list)
    additional_info: str | None = None
    tz_filename: str | None = None


class MissingField(BaseModel):
    model_config = ConfigDict(strict=True)

    field: str
    description: str


class InfoRequestInput(BaseModel):
    model_config = ConfigDict(strict=True)

    dzo_name: str = "коллега"
    subject: str = ""
    missing_fields: list[MissingField] = Field(default_factory=list)
    has_corrected_form: bool = False


class EscalationInput(BaseModel):
    model_config = ConfigDict(strict=True)

    subject: str = ""
    reason: str = ""
    details: str = ""


class ResponseEmailInput(BaseModel):
    model_config = ConfigDict(strict=True)

    decision: str = ""
    subject: str = ""
    agent_summary: str = ""


class CorrectedField(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str
    old_value: str = ""
    new_value: str = ""
    status: str = "ok"  # 'added' | 'changed' | 'ok'


class CorrectedApplicationInput(BaseModel):
    model_config = ConfigDict(strict=True)

    fields: list[CorrectedField] = Field(default_factory=list)


class TzAgentAnalysisInput(BaseModel):
    model_config = ConfigDict(strict=True)

    tz_text: str = Field(description="Извлечённый текст ТЗ для анализа")
    email_subject: str = ""
    source_sender: str = ""
    target_agent: str = Field(default="tz", description="ID целевого агента из AGENT_TOOL_REGISTRY")


class PeerAgentInvokeInput(BaseModel):
    model_config = ConfigDict(strict=True)

    target_agent: str = Field(description="ID целевого агента (например: tz, tender)")
    query_text: str = Field(description="Краткий структурированный запрос для целевого агента")
    subject: str = ""
    sender: str = ""


# ---------------------------------------------------------------------------
# Инструменты агента
# ---------------------------------------------------------------------------

@tool(args_schema=ValidationReportInput)
def generate_validation_report(
    decision: str,
    checklist_attachments: list[ChecklistItem] = None,
    checklist_required: list[ChecklistItem] = None,
    checklist_additional: list[ChecklistItem] = None,
    missing_fields: list[str] = None,
) -> str:
    """
    Генерирует JSON-отчёт по чек-листам проверки заявки ДЗО.
    Передай только результаты анализа — не полный текст заявки.
    """
    checklist_attachments = checklist_attachments or []
    checklist_required = checklist_required or []
    checklist_additional = checklist_additional or []
    missing_fields = missing_fields or []
    try:
        logger.debug("🔧 generate_validation_report вызван")
        atts = [c.model_dump() for c in checklist_attachments]
        reqs = [c.model_dump() for c in checklist_required]
        adds = [c.model_dump() for c in checklist_additional]
        report = {
            "timestamp": datetime.now().isoformat(),
            "decision":  decision,
            "checklist_attachments": atts,
            "checklist_required":    reqs,
            "checklist_additional":  adds,
            "missing_fields":        missing_fields,
            "stats": {
                "attachments_ok": sum(1 for c in atts if c.get("status") == "Да"),
                "required_ok":    sum(1 for c in reqs if c.get("status") in ("Да", "ОК")),
                "additional_ok":  sum(1 for c in adds if c.get("status") in ("Да", "ОК")),
            },
        }
        logger.info("✅ generate_validation_report: отчёт готов (decision=%s)", decision)
        return json.dumps(report, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ generate_validation_report: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=TezisFormInput)
def generate_tezis_form(
    procurement_subject: str,
    justification: str | None = None,
    budget: str | None = None,
    initiator_name: str = "",
    initiator_contacts: str = "",
    budget_manager: str | None = None,
    recommended_suppliers: list[Supplier] = None,
    additional_info: str | None = None,
    tz_filename: str | None = None,
) -> str:
    """
    Генерирует предзаполненную HTML-форму заявки для ЭДО «Тезис».
    Передай только реквизиты заявки — не полный текст документа.
    """
    recommended_suppliers = recommended_suppliers or []
    try:
        logger.debug("🔧 generate_tezis_form вызван")
        fields = [
            ("Предмет закупки",         procurement_subject),
            ("Обоснование закупки",     justification),
            ("Бюджет, руб.",            budget),
            ("Инициатор закупки",       f"{initiator_name} ({initiator_contacts})"),
            ("Распорядитель бюджета",   budget_manager),
            ("Рекомендуемые поставщики",
             "; ".join(f"{s.name} (ИНН: {s.inn})" for s in recommended_suppliers)),
            ("Иная информация",         additional_info),
            ("ТЗ (вложение)",           tz_filename),
        ]
        rows = "".join(
            f"<tr><th>{html_escape(str(label))}</th>"
            f"<td class=\"{'filled' if val else 'empty'}\">"
            f"{html_escape(str(val)) if val else '[Требуется заполнить]'}</td></tr>"
            for label, val in fields
        )
        html = (
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\"><style>"
            "body{font-family:Arial,sans-serif;font-size:14px;margin:40px}"
            "table{border-collapse:collapse;width:100%}"
            "td,th{border:1px solid #999;padding:10px}"
            "th{background:#e8e8e8;width:40%}"
            ".filled{background:#D7FFD7;font-weight:bold}"
            ".empty{background:#FFFF00;color:#CC0000;font-style:italic}"
            "</style></head><body>"
            "<h1 style=\"text-align:center\">ЗАЯВКА НА ЗАКУПКУ — ФОРМА ДЛЯ ЭДО «ТЕЗИС»</h1>"
            f"<p><em>Сформировано: {datetime.now().strftime('%d.%m.%Y')}</em></p>"
            f"<table>{rows}</table></body></html>"
        )
        logger.info("✅ generate_tezis_form: HTML-форма готова")
        return json.dumps({"tezisFormHtml": html})
    except Exception as e:
        logger.error("❌ generate_tezis_form: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=InfoRequestInput)
def generate_info_request(
    dzo_name: str = "коллега",
    subject: str = "",
    missing_fields: list[MissingField] = None,
    has_corrected_form: bool = False,
) -> str:
    """
    Генерирует HTML-письмо запроса недостающей информации.
    Передай только список недостающих полей — не полный текст заявки.
    """
    missing_fields = missing_fields or []
    try:
        logger.debug("🔧 generate_info_request вызван")
        rows = "".join(
            f"<tr><td style='border:1px solid #999;padding:8px;font-weight:bold'>{html_escape(f.field)}</td>"
            f"<td style='border:1px solid #999;padding:8px'>{html_escape(f.description)}</td></tr>"
            for f in missing_fields
        )
        corrected_note = "<p>📎 К письму приложена исправленная форма заявки.</p>" if has_corrected_form else ""
        html = (
            "<div style=\"font-family:Arial;font-size:14px;line-height:1.8\">"
            f"<p>Уважаем(ый/ая) {html_escape(dzo_name)}!</p>"
            f"<p>Благодарим за направленную заявку по теме: <strong>«{html_escape(subject)}»</strong>.</p>"
            "<p>Для корректного оформления в ЭДО «Тезис» просим предоставить следующую информацию:</p>"
            "<table style=\"border-collapse:collapse;width:100%\">"
            "<tr><th style=\"border:1px solid #999;padding:8px;background:#e8e8e8\">Поле</th>"
            "<th style=\"border:1px solid #999;padding:8px;background:#e8e8e8\">Что необходимо указать</th></tr>"
            f"{rows}</table>"
            + corrected_note
            + "<p>Просим направить ответным письмом.</p>"
            "<p>С уважением,<br>Служба централизованных закупок</p></div>"
        )
        logger.info("✅ generate_info_request: письмо с запросом готово (тема: %s)", subject)
        return json.dumps({
            "emailHtml": html,
            "decision":  "Требуется доработка",
            "subject":   f"Запрос информации по заявке: {subject}",
        })
    except Exception as e:
        logger.error("❌ generate_info_request: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=EscalationInput)
def generate_escalation(
    subject: str = "",
    reason: str = "",
    details: str = "",
) -> str:
    """
    Генерирует письмо-эскалацию руководителю.
    Передай тему, причину и детали — не полный текст заявки.
    """
    try:
        logger.debug("🔧 generate_escalation вызван")
        html = (
            "<div style=\"font-family:Arial;font-size:14px\">"
            "<p><strong>⚠️ ТРЕБУЕТСЯ ЭСКАЛАЦИЯ</strong></p>"
            f"<p>Тема заявки: {html_escape(subject)}</p>"
            f"<p>Причина: {html_escape(reason)}</p>"
            f"<p>Детали: {html_escape(details)}</p>"
            "</div>"
        )
        logger.warning("⚠️  generate_escalation: письмо эскалации готово (причина: %s)", reason)
        return json.dumps({
            "escalationHtml": html,
            "decision": "Требуется эскалация",
            "subject":  f"⚠️ Эскалация заявки ДЗО: {subject}",
        })
    except Exception as e:
        logger.error("❌ generate_escalation: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=ResponseEmailInput)
def generate_response_email(
    decision: str = "",
    subject: str = "",
    agent_summary: str = "",
) -> str:
    """
    Генерирует финальное ответное письмо отправителю заявки.
    Передай только решение и краткое резюме — не полный текст.
    """
    try:
        logger.debug("🔧 generate_response_email вызван")
        html = (
            "<div style=\"font-family:Arial;font-size:14px;line-height:1.8\">"
            "<p>Уважаемый коллега!</p>"
            f"<p>Ваша заявка по теме <strong>«{html_escape(subject)}»</strong> была обработана ИИ-инспектором.</p>"
            f"<p><strong>Решение: {html_escape(decision)}</strong></p>"
            f"<p>{html_escape(agent_summary)}</p>"
            "<p>С уважением,<br>Служба централизованных закупок</p></div>"
        )
        logger.info("✅ generate_response_email: ответное письмо готово (решение: %s)", decision)
        return json.dumps({"emailHtml": html})
    except Exception as e:
        logger.error("❌ generate_response_email: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=CorrectedApplicationInput)
def generate_corrected_application(
    fields: list[CorrectedField] = None,
) -> str:
    """
    Генерирует HTML проект исправленной заявки с цветовой разметкой.
    Передай только изменённые поля — не полный текст.
    status: 'added' | 'changed' | 'ok'
    """
    fields = fields or []
    try:
        logger.debug("🔧 generate_corrected_application вызван")
        rows = ""
        for f in fields:
            name = html_escape(f.name)
            old = html_escape(f.old_value)
            new = html_escape(f.new_value)
            if f.status == "added":
                rows += (
                    f"<tr><th>{name}</th>"
                    f"<td style='background:#FFFF00;color:#CC0000'>[ДОБАВЛЕНО: {new}]</td></tr>"
                )
            elif old and new:
                rows += (
                    f"<tr><th>{name}</th><td>"
                    f"<span style='background:#FFD7D7;text-decoration:line-through'>[БЫЛО: {old}]</span> → "
                    f"<span style='background:#D7FFD7'>[СТАЛО: {new}]</span></td></tr>"
                )
            else:
                rows += f"<tr><th>{name}</th><td>{new or old}</td></tr>"
        html = (
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\"></head><body>"
            "<h1>ПРОЕКТ ИСПРАВЛЕННОЙ ЗАЯВКИ</h1>"
            f"<table style=\"border-collapse:collapse;width:100%\">{rows}</table></body></html>"
        )
        logger.info("✅ generate_corrected_application: исправленная заявка готова (%d полей)", len(fields))
        return json.dumps({"correctedHtml": html})
    except Exception as e:
        logger.error("❌ generate_corrected_application: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=TzAgentAnalysisInput)
def analyze_tz_with_agent(
    tz_text: str,
    email_subject: str = "",
    source_sender: str = "",
    target_agent: str = "tz",
) -> str:
    """
    Делегирует анализ ТЗ другому агенту и возвращает компактный результат.
    Используй, когда в заявке ДЗО обнаружен файл/текст ТЗ.
    """
    try:
        logger.debug("🔁 analyze_tz_with_agent: source=dzo target=%s", target_agent)
        delegated_input = (
            "INCOMING TECHNICAL SPECIFICATION\n"
            "===========================================\n"
            f"От: {source_sender}\n"
            f"Тема: {email_subject}\n\n"
            "-- ТЕКСТ ТЗ --\n"
            f"{tz_text}"
        )
        delegated_result = invoke_agent_as_tool(
            source_agent="dzo",
            target_agent=target_agent,
            chat_input=delegated_input,
            metadata={"delegated_by": "dzo", "tool": "analyze_tz_with_agent"},
        )

        overall_status = "Не определён"
        critical_issues: list[str] = []
        recommendations: list[str] = []
        email_html = ""

        for obs in delegated_result.get("observations", []):
            if obs.get("overall_status"):
                overall_status = str(obs.get("overall_status"))
                critical_issues = [str(x) for x in obs.get("critical_issues", [])]
                recommendations = [str(x) for x in obs.get("recommendations", [])]
            if obs.get("emailHtml") and not email_html:
                email_html = str(obs.get("emailHtml"))

        summary = (
            f"Агент ТЗ: {overall_status}. "
            f"Критичных замечаний: {len(critical_issues)}. "
            f"Рекомендаций: {len(recommendations)}."
        )

        logger.info("✅ analyze_tz_with_agent: получен результат (%s)", overall_status)
        return json.dumps({
            "tzAgentAnalysis": {
                "target_agent": target_agent,
                "overall_status": overall_status,
                "critical_issues": critical_issues,
                "recommendations": recommendations,
                "summary": summary,
                "email_html": email_html,
                "raw_output": delegated_result.get("output", ""),
            }
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ analyze_tz_with_agent: ошибка %s", e)
        return json.dumps({
            "tzAgentAnalysis": {
                "target_agent": target_agent,
                "overall_status": "Ошибка анализа",
                "critical_issues": [],
                "recommendations": [],
                "summary": f"Не удалось выполнить анализ ТЗ: {e}",
                "email_html": "",
                "raw_output": "",
            }
        }, ensure_ascii=False)


@tool(args_schema=PeerAgentInvokeInput)
def invoke_peer_agent(
    target_agent: str,
    query_text: str,
    subject: str = "",
    sender: str = "",
) -> str:
    """Универсальный вызов другого агента как инструмента."""
    try:
        logger.debug("🔁 invoke_peer_agent: source=dzo target=%s", target_agent)
        result = invoke_agent_as_tool(
            source_agent="dzo",
            target_agent=target_agent,
            chat_input=query_text,
            metadata={"delegated_by": "dzo", "subject": subject, "sender": sender},
        )
        return json.dumps({
            "peerAgentResult": {
                "target_agent": target_agent,
                "output": result.get("output", ""),
                "observations": result.get("observations", []),
            }
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ invoke_peer_agent(dzo): ошибка %s", e)
        return json.dumps({
            "peerAgentResult": {
                "target_agent": target_agent,
                "output": "",
                "observations": [],
                "error": str(e),
            }
        }, ensure_ascii=False)
