import json
import logging
import re
from datetime import datetime
from html import escape as html_escape

from langchain.tools import tool

logger = logging.getLogger("agent_tz")

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
    # Это нужно когда LLM вызывает инструменты параллельно и в конец query
    # попадает фрагмент следующего вызова, например: ...}},{'} или ...}}]}]}
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
    # Попытка 3: добавить { } вокруг — LLM иногда генерирует key: "value" без скобок
    try:
        # Цитируем незакавыченные ключи: word: → "word":
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


def _extract_email_fields_from_text(text: str) -> dict:
    """Вытащить поля decision/dzo_name/tz_subject/issues/recommendations из плоского текста."""

    def grab_str(key):
        m = re.search(rf'{key}\s*[=:]\s*"([^"]*)"', text)
        if m:
            return m.group(1)
        m = re.search(rf'{key}\s*[=:]\s*([^\n,\[{{]+)', text)
        return m.group(1).strip().strip('"\'') if m else ""

    def grab_list(key):
        m = re.search(rf'{key}\s*[=:]?\s*\[([^\]]*)\]', text, re.DOTALL)
        if not m:
            return []
        return [s.strip().strip('"\'') for s in re.findall(r'"([^"]+)"', m.group(1))]

    return {
        "decision":        grab_str("decision"),
        "dzo_name":        grab_str("dzo_name"),
        "tz_subject":      grab_str("tz_subject"),
        "issues":          grab_list("issues"),
        "recommendations": grab_list("recommendations"),
        "has_corrected_tz": "has_corrected_tz: true" in text or '"has_corrected_tz": true' in text,
    }


# --------------------------------------------------------------------------- #
#  Инструменты агента                                                          #
# --------------------------------------------------------------------------- #

@tool
def generate_json_report(query: str) -> str:
    """
    Генерирует JSON-отчёт проверки ТЗ по 8 разделам.

    ⚠️ НЕ передавай полный текст ТЗ! Передай ТОЛЬКО результаты анализа:
    {"overall_status":"Требует доработки","category":"ИТ-услуги",
     "sections":[{"id":1,"name":"Цель закупки","status":"ОК","comment":""},
                 {"id":3,"name":"Количество","status":"❌","comment":"Не указано"}],
     "critical_issues":["Отсутствует раздел 3"],
     "recommendations":["Добавить количество и единицы измерения"]}
    """
    try:
        logger.debug("🔧 generate_json_report вызван (%d симв.)", len(query) if query else 0)
        d = _parse_query(query, "generate_json_report")

        if not d and d is not None:
            # Пустой строки — токены обрезаны
            return json.dumps({"error": "Пустой запрос инструмента (превышен лимит токенов LLM)"})

        if d is None:
            # Неверный формат — создаём базовый скелет
            logger.warning("⚠️ generate_json_report: получен не-JSON, создаём скелет отчёта")
            d = {
                "overall_status": "Требует доработки",
                "category": "Не определена",
                "sections": [],
                "critical_issues": ["Анализ завершён неполностью — инструмент получил неструктурированные данные"],
                "recommendations": ["Повторите запрос, передав в инструмент только краткий JSON с результатами анализа"],
            }

        # Дополняем отсутствующие из 8 обязательных разделов
        sections = list(d.get("sections", []))
        existing_ids = {s.get("id") for s in sections}
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
        for rid, rname in required:
            if rid not in existing_ids:
                sections.append({"id": rid, "name": rname, "status": "❓", "comment": "Не проверено"})
        sections.sort(key=lambda s: s.get("id", 99))

        report = {
            "timestamp":       datetime.now().isoformat(),
            "overall_status":  d.get("overall_status", "Не определено"),
            "category":        d.get("category", "Не определена"),
            "sections":        sections,
            "critical_issues": d.get("critical_issues", []),
            "recommendations": d.get("recommendations", []),
            "stats": {
                "total":  8,
                "ok":     sum(1 for s in sections if s.get("status") == "ОК"),
                "issues": sum(1 for s in sections if s.get("status") not in ("ОК", "❓")),
            },
        }
        logger.info(
            "✅ generate_json_report: отчёт готов (статус: %s, разделов: %d)",
            report["overall_status"], len(sections),
        )
        return json.dumps(report, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ generate_json_report: ошибка %s", e)
        return json.dumps({"error": str(e)})


@tool
def generate_corrected_tz(query: str) -> str:
    """
    Генерирует HTML-версию исправленного ТЗ с цветовой разметкой.

    ⚠️ НЕ передавай полный текст! Передай только изменения:
    {"title":"Исправленное ТЗ",
     "original_sections":[{"name":"Цель закупки","content":"...","status":"ОК"}],
     "added_sections":[{"name":"Количество","content":"1 лицензия"}],
     "modifications":[{"section":"Требования","old_text":"хорошее","new_text":"по ГОСТ Р ISO"}]}
    """
    try:
        logger.debug("🔧 generate_corrected_tz вызван (%d симв.)", len(query) if query else 0)
        d = _parse_query(query, "generate_corrected_tz")

        if not d and d is not None:
            return json.dumps({"error": "Пустой запрос инструмента (превышен лимит токенов LLM)"})

        sections_html = ""

        if d is None:
            # Получили текст — оборачиваем напрямую в HTML
            logger.warning("⚠️ generate_corrected_tz: получен не-JSON, оборачиваем текст")
            safe = query.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
            sections_html = f"<div>{safe}</div>"
            title = "Исправленное ТЗ"
        else:
            title = d.get("title", "Исправленное ТЗ")
            for sec in d.get("original_sections", []):
                mods = [m for m in d.get("modifications", []) if m.get("section") == sec.get("name")]
                sections_html += f"<h2>{sec.get('name', '')}</h2>"
                if mods:
                    for m in mods:
                        old, new = m.get("old_text", ""), m.get("new_text", "")
                        sections_html += (
                            f"<p><span style='background:#FFD7D7;text-decoration:line-through'>[БЫЛО: {old}]</span>"
                            f" → <span style='background:#D7FFD7'>[СТАЛО: {new}]</span></p>"
                        )
                    if sec.get("content"):
                        sections_html += f"<p>{sec['content']}</p>"
                elif sec.get("status") == "ОК":
                    sections_html += f"<p style='color:#006600'>{sec.get('content', '')}</p>"
                else:
                    sections_html += f"<p>{sec.get('content', '')}</p>"

            for sec in d.get("added_sections", []):
                sections_html += (
                    f"<h2><span style='background:#FFFF00;color:#CC0000'>[ДОБАВЛЕНО] {sec.get('name', '')}</span></h2>"
                    f"<p><span style='background:#FFFF00;color:#CC0000'>"
                    f"{sec.get('content', '[Заполните раздел]')}</span></p>"
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


@tool
def generate_email_to_dzo(query: str) -> str:
    """
    Генерирует деловое письмо-ответ в ДЗО с результатами проверки ТЗ.

    ⚠️ Передай только поля решения (краткий JSON):
    {"decision":"Требует доработки","dzo_name":"Название ДЗО",
     "tz_subject":"Тема ТЗ","issues":["Замечание 1"],
     "recommendations":["Рекомендация 1"],"has_corrected_tz":true}
    """
    try:
        logger.debug("🔧 generate_email_to_dzo вызван (%d симв.)", len(query) if query else 0)
        d = _parse_query(query, "generate_email_to_dzo")

        if not d and d is not None:
            return json.dumps({"error": "Пустой запрос инструмента (превышен лимит токенов LLM)"})

        if d is None:
            # Неверный формат — пробуем regex-парсинг key: value
            logger.warning("⚠️ generate_email_to_dzo: получен не-JSON, парсим regex")
            d = _extract_email_fields_from_text(query)

        decision = d.get("decision", "На рассмотрении")
        issues_html = "".join(f"<li>{html_escape(str(i))}</li>" for i in d.get("issues", []))
        recs_html   = "".join(f"<li>{html_escape(str(r))}</li>" for r in d.get("recommendations", []))

        corrected_note = ""
        if d.get("has_corrected_tz"):
            corrected_note = "<p>📎 К письму приложен проект исправленного ТЗ с цветовой разметкой.</p>"

        html = (
            "<div style=\"font-family:Arial;font-size:14px;line-height:1.8\">"
            f"<p>Уважаем(ый/ая) {html_escape(str(d.get('dzo_name', 'коллега')))}!</p>"
            f"<p>Благодарим за направленное ТЗ по теме: <strong>«{html_escape(str(d.get('tz_subject', '')))}»</strong>.</p>"
            f"<p><strong>Результат проверки: {html_escape(str(decision))}</strong></p>"
            + (f"<p>Замечания:<ul>{issues_html}</ul></p>" if issues_html else "")
            + (f"<p>Рекомендации:<ul>{recs_html}</ul></p>" if recs_html else "")
            + corrected_note
            + "<p>С уважением,<br>Служба централизованных закупок</p></div>"
        )
        logger.info("✅ generate_email_to_dzo: письмо-ответ готово (решение: %s)", decision)
        return json.dumps({
            "emailHtml": html,
            "decision":  decision,
            "subject":   f"Результат проверки ТЗ: {d.get('tz_subject', '')}",
        }, ensure_ascii=False)
    except Exception as e:
        logger.error("❌ generate_email_to_dzo: ошибка %s", e)
        return json.dumps({"error": str(e)})
