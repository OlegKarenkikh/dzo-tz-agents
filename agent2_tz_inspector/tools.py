import json
from datetime import datetime
from html import escape as html_escape

from langchain.tools import tool
from pydantic import BaseModel, Field

from shared.logger import setup_logger

logger = setup_logger("agent_tz")


# ---------------------------------------------------------------------------
# Pydantic-схемы аргументов (args_schema).
# Заменяют паттерн query: str + json.loads(query).
# LangChain использует схему для генерации structured function call,
# что исключает ошибки JSON-парсинга на стороне LLM.
# ---------------------------------------------------------------------------

class SectionResult(BaseModel):
    id: int
    name: str
    status: str = Field(description="'ОК' | '❌' | '❓'")
    comment: str = ""


class JsonReportInput(BaseModel):
    overall_status: str = Field(description="'Соответствует' | 'Требует доработки' | 'Не соответствует'")
    category: str = "Не определена"
    sections: list[SectionResult] = Field(default_factory=list)
    critical_issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class OriginalSection(BaseModel):
    name: str
    content: str = ""
    status: str = "ОК"


class AddedSection(BaseModel):
    name: str
    content: str = ""


class Modification(BaseModel):
    section: str
    old_text: str = ""
    new_text: str = ""


class CorrectedTzInput(BaseModel):
    title: str = "Исправленное ТЗ"
    original_sections: list[OriginalSection] = Field(default_factory=list)
    added_sections: list[AddedSection] = Field(default_factory=list)
    modifications: list[Modification] = Field(default_factory=list)


class EmailToDzoInput(BaseModel):
    decision: str = Field(description="'Соответствует' | 'Требует доработки' | 'Не соответствует'")
    dzo_name: str = "коллега"
    tz_subject: str = ""
    issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    has_corrected_tz: bool = False


# ---------------------------------------------------------------------------
# Инструменты агента
# ---------------------------------------------------------------------------

@tool(args_schema=JsonReportInput)
def generate_json_report(
    overall_status: str,
    category: str = "Не определена",
    sections: list[SectionResult] = None,
    critical_issues: list[str] = None,
    recommendations: list[str] = None,
) -> str:
    """
    Генерирует JSON-отчёт проверки ТЗ по 8 разделам.
    Передай ТОЛЬКО краткие результаты анализа — не полный текст ТЗ.
    """
    sections = sections or []
    critical_issues = critical_issues or []
    recommendations = recommendations or []
    try:
        logger.debug("🔧 generate_json_report вызван (%d разделов)", len(sections))

        # Дополняем отсутствующие из 8 обязательных разделов
        existing_ids = {s.id for s in sections}
        required = [
            (1, "Цель закупки"),
            (2, "Требования к товару/работе/услуге"),
            (3, "Количество и единицы измерения"),
            (4, "Срок и условия поставки"),
            (5, "Место поставки"),
            (6, "Требования к исполнителю"),
            (7, "Критерии оценки заявок"),
            (8, "Приложения"),
        ]
        sections_list = [s.model_dump() for s in sections]
        for rid, rname in required:
            if rid not in existing_ids:
                sections_list.append({"id": rid, "name": rname, "status": "❓", "comment": "Не проверено"})
        sections_list.sort(key=lambda s: s.get("id", 99))

        report = {
            "timestamp":       datetime.now().isoformat(),
            "overall_status":  overall_status,
            "category":        category,
            "sections":        sections_list,
            "critical_issues": critical_issues,
            "recommendations": recommendations,
            "stats": {
                "total":  8,
                "ok":     sum(1 for s in sections_list if s.get("status") == "ОК"),
                "issues": sum(1 for s in sections_list if s.get("status") not in ("ОК", "❓")),
            },
        }
        logger.info(
            "✅ generate_json_report: отчёт готов (статус: %s, разделов: %d)",
            overall_status, len(sections_list),
        )
        return json.dumps(report, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ generate_json_report: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool(args_schema=CorrectedTzInput)
def generate_corrected_tz(
    title: str = "Исправленное ТЗ",
    original_sections: list[OriginalSection] = None,
    added_sections: list[AddedSection] = None,
    modifications: list[Modification] = None,
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
