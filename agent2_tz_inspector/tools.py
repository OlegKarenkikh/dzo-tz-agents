import json
from datetime import datetime
from html import escape as html_escape

from langchain.tools import tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from shared.agent_tooling import invoke_agent_as_tool
from shared.logger import setup_logger
from shared.schemas import TZInspectionResult

logger = setup_logger("agent_tz")


# ---------------------------------------------------------------------------
# Pydantic-схемы аргументов (args_schema).
# Заменяют паттерн query: str + json.loads(query).
# LangChain использует схему для генерации structured function call,
# что исключает ошибки JSON-парсинга на стороне LLM.
# ---------------------------------------------------------------------------

class SectionResult(BaseModel):
    model_config = ConfigDict(strict=True)

    id: int
    name: str
    status: str = Field(description="'ОК' | '❌' | '❓'")
    comment: str = ""


class JsonReportInput(BaseModel):
    model_config = ConfigDict(strict=True)

    overall_status: str = Field(description="'Соответствует' | 'Требует доработки' | 'Не соответствует'")
    category: str = "Не определена"
    sections: list[SectionResult] = Field(default_factory=list)
    critical_issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class OriginalSection(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str
    content: str = ""
    status: str = "ОК"


class AddedSection(BaseModel):
    model_config = ConfigDict(strict=True)

    name: str
    content: str = ""


class Modification(BaseModel):
    model_config = ConfigDict(strict=True)

    section: str
    old_text: str = ""
    new_text: str = ""


class CorrectedTzInput(BaseModel):
    model_config = ConfigDict(strict=True)

    title: str = "Исправленное ТЗ"
    original_sections: list[OriginalSection] = Field(default_factory=list)
    added_sections: list[AddedSection] = Field(default_factory=list)
    modifications: list[Modification] = Field(default_factory=list)


class EmailToDzoInput(BaseModel):
    model_config = ConfigDict(strict=True)

    decision: str = Field(description="'Соответствует' | 'Требует доработки' | 'Не соответствует'")
    dzo_name: str = "коллега"
    tz_subject: str = ""
    issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    has_corrected_tz: bool = False


class PeerAgentInvokeInput(BaseModel):
    model_config = ConfigDict(strict=True)

    target_agent: str = Field(description="ID целевого агента (например: dzo, tender)")
    query_text: str = Field(description="Краткий структурированный запрос для целевого агента")
    subject: str = ""
    sender: str = ""


# ---------------------------------------------------------------------------
# Инструменты агента
# ---------------------------------------------------------------------------

class _TZReportInput(BaseModel):
    """Permissive input schema — принимает новый формат tz_v2.md и старый формат."""
    model_config = ConfigDict(extra="allow")

    decision: str = ""
    sections_present: dict = Field(default_factory=dict)
    missing_critical: list = Field(default_factory=list)
    missing_optional: list = Field(default_factory=list)
    summary: str = ""
    overall_status: str = "Требует доработки"
    category: str = "Не определена"
    sections: list = Field(default_factory=list)
    critical_issues: list = Field(default_factory=list)
    recommendations: list = Field(default_factory=list)
    score_pct: float = 0


@tool(args_schema=_TZReportInput)
def generate_json_report(
    decision: str = "",
    sections_present: dict = None,
    missing_critical: list = None,
    missing_optional: list = None,
    summary: str = "",
    overall_status: str = "Требует доработки",
    category: str = "Не определена",
    sections: list = None,
    critical_issues: list = None,
    recommendations: list = None,
    score_pct: float = 0,
) -> str:
    """
    Генерирует структурированный JSON-отчёт проверки ТЗ по 8 разделам.
    Передай ТОЛЬКО краткие результаты анализа — не полный текст ТЗ.
    Принимает новый формат (decision, sections_present, missing_critical) и старый (overall_status, sections).
    """
    effective = decision if decision else overall_status
    kwargs = {
        "decision": effective,
        "overall_status": effective,
        "category": category,
        "sections": sections or [],
        "sections_present": sections_present or {},
        "critical_issues": critical_issues or missing_critical or [],
        "missing_critical": missing_critical or [],
        "missing_optional": missing_optional or [],
        "recommendations": recommendations or [],
        "score_pct": score_pct,
        "summary": summary,
    }
    try:
        validated = TZInspectionResult.model_validate(kwargs)
        return json.dumps(validated.model_dump(), ensure_ascii=False, indent=2)
    except ValidationError as e:
        logger.warning("⚠️ generate_json_report ValidationError: %s", e)
        return json.dumps({
            "decision": effective,
            "score_pct": score_pct,
            "sections_present": sections_present or {},
            "missing_critical": missing_critical or [],
            "missing_optional": missing_optional or [],
            "recommendations": recommendations or [],
            "summary": summary,
        }, ensure_ascii=False, indent=2)


@tool(args_schema=CorrectedTzInput)
def generate_corrected_tz(
    title: str = "Исправленное ТЗ",
    original_sections: list[OriginalSection] | None = None,
    added_sections: list[AddedSection] | None = None,
    modifications: list[Modification] | None = None,
) -> str:
    """
    Генерирует HTML-версию исправленного ТЗ с цветовой разметкой.
    Передай только список изменений — не полный текст ТЗ.
    """
    original_sections = original_sections or []
    added_sections = added_sections or []
    modifications = modifications or []
    try:
        logger.debug("🔧 generate_corrected_tz вызван (разделов: %d, изменений: %d)",
                     len(original_sections), len(modifications))
        sections_html = ""
        for sec in original_sections:
            mods = [m for m in modifications if m.section == sec.name]
            sections_html += f"<h2>{html_escape(sec.name)}</h2>"
            if mods:
                for m in mods:
                    old, new = html_escape(m.old_text), html_escape(m.new_text)
                    sections_html += (
                        f"<p><span style='background:#FFD7D7;text-decoration:line-through'>[БЫЛО: {old}]</span>"
                        f" → <span style='background:#D7FFD7'>[СТАЛО: {new}]</span></p>"
                    )
                if sec.content:
                    sections_html += f"<p>{html_escape(sec.content)}</p>"
            elif sec.status == "ОК":
                sections_html += f"<p style='color:#006600'>{html_escape(sec.content)}</p>"
            else:
                sections_html += f"<p>{html_escape(sec.content)}</p>"

        for sec in added_sections:
            sections_html += (
                f"<h2><span style='background:#FFFF00;color:#CC0000'>[ДОБАВЛЕНО] {html_escape(sec.name)}</span></h2>"
                f"<p><span style='background:#FFFF00;color:#CC0000'>"
                f"{html_escape(sec.content or '[Заполните раздел]')}</span></p>"
            )

        html = (
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
            "<style>"
            "body{font-family:\"Times New Roman\",serif;font-size:14px;margin:40px;line-height:1.6}"
            "h1{text-align:center;font-size:18px}"
            "h2{font-size:16px;border-bottom:1px solid #ccc;padding-bottom:5px}"
            "</style></head><body>"
            "<h1>ПРОЕКТ ИСПРАВЛЕННОГО ТЕХНИЧЕСКОГО ЗАДАНИЯ</h1>"
            f"<p><em>Сформировано: {datetime.now().strftime('%d.%m.%Y')}</em></p>"
            f"{sections_html}"
            "<hr><p><em>Пожалуйста, заполните выделенные жёлтым разделы и направьте исправленное ТЗ повторно.</em></p>"
            "</body></html>"
        )
        logger.info("✅ generate_corrected_tz: HTML готов (заголовок: %s)", title)
        return json.dumps({"html": html, "title": title}, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ generate_corrected_tz: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=EmailToDzoInput)
def generate_email_to_dzo(
    decision: str,
    dzo_name: str = "коллега",
    tz_subject: str = "",
    issues: list[str] = None,
    recommendations: list[str] = None,
    has_corrected_tz: bool = False,
) -> str:
    """
    Генерирует деловое письмо-ответ в ДЗО с результатами проверки ТЗ.
    Передай только поля решения — не полный текст ТЗ.
    """
    issues = issues or []
    recommendations = recommendations or []
    try:
        logger.debug("🔧 generate_email_to_dzo вызван (решение: %s)", decision)
        issues_html = "".join(f"<li>{html_escape(i)}</li>" for i in issues)
        recs_html   = "".join(f"<li>{html_escape(r)}</li>" for r in recommendations)
        corrected_note = "<p>📎 К письму приложен проект исправленного ТЗ с цветовой разметкой.</p>" if has_corrected_tz else ""

        html = (
            "<div style=\"font-family:Arial;font-size:14px;line-height:1.8\">"
            f"<p>Уважаем(ый/ая) {html_escape(dzo_name)}!</p>"
            f"<p>Благодарим за направленное ТЗ по теме: <strong>«{html_escape(tz_subject)}»</strong>.</p>"
            f"<p><strong>Результат проверки: {html_escape(decision)}</strong></p>"
            + (f"<p>Замечания:<ul>{issues_html}</ul></p>" if issues_html else "")
            + (f"<p>Рекомендации:<ul>{recs_html}</ul></p>" if recs_html else "")
            + corrected_note
            + "<p>С уважением,<br>Служба централизованных закупок</p></div>"
        )
        logger.info("✅ generate_email_to_dzo: письмо-ответ готово (решение: %s)", decision)
        return json.dumps({
            "emailHtml": html,
            "decision":  decision,
            "subject":   f"Результат проверки ТЗ: {tz_subject}",
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ generate_email_to_dzo: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=PeerAgentInvokeInput)
def invoke_peer_agent(
    target_agent: str,
    query_text: str,
    subject: str = "",
    sender: str = "",
) -> str:
    """Универсальный вызов другого агента как инструмента."""
    try:
        logger.debug("🔁 invoke_peer_agent: source=tz target=%s", target_agent)
        result = invoke_agent_as_tool(
            source_agent="tz",
            target_agent=target_agent,
            chat_input=query_text,
            metadata={"delegated_by": "tz", "subject": subject, "sender": sender},
        )
        return json.dumps({
            "peerAgentResult": {
                "target_agent": target_agent,
                "output": result.get("output", ""),
                "observations": result.get("observations", []),
            }
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ invoke_peer_agent(tz): ошибка %s", e)
        return json.dumps({
            "peerAgentResult": {
                "target_agent": target_agent,
                "output": "",
                "observations": [],
                "error": str(e),
            }
        }, ensure_ascii=False)
