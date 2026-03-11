import json
from datetime import datetime
from langchain.tools import tool


@tool
def generate_json_report(query: str) -> str:
    """
    Генерирует JSON-отчёт проверки ТЗ по 8 разделам эталонной структуры.
    Вход: JSON с полями: overall_status, category,
    sections (array {id, name, status, comment}),
    critical_issues (array), recommendations (array).
    """
    try:
        d        = json.loads(query)
        sections = d.get("sections", [])
        report   = {
            "timestamp":      datetime.now().isoformat(),
            "overall_status": d.get("overall_status", "Не определено"),
            "category":       d.get("category", "Не определена"),
            "sections":       sections,
            "critical_issues": d.get("critical_issues", []),
            "recommendations": d.get("recommendations", []),
            "stats": {
                "total":  8,
                "ok":     sum(1 for s in sections if s.get("status") == "ОК"),
                "issues": sum(1 for s in sections if s.get("status") != "ОК"),
            },
        }
        return json.dumps(report, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def generate_corrected_tz(query: str) -> str:
    """
    Генерирует HTML-версию исправленного ТЗ с цветовой разметкой.
    Вход: JSON с полями: title,
    original_sections (array {name, content, status}),
    added_sections (array {name, content}),
    modifications (array {section, old_text, new_text}).
    """
    try:
        d = json.loads(query)
        sections_html = ""
        for sec in d.get("original_sections", []):
            mods = [m for m in d.get("modifications", []) if m.get("section") == sec["name"]]
            sections_html += f"<h2>{sec['name']}</h2>"
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
                f"<h2><span style='background:#FFFF00;color:#CC0000'>[ДОБАВЛЕНО] {sec['name']}</span></h2>"
                f"<p><span style='background:#FFFF00;color:#CC0000'>"
                f"{sec.get('content', '[Заполните данный раздел]')}</span></p>"
            )

        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
body{{font-family:"Times New Roman",serif;font-size:14px;margin:40px;line-height:1.6}}
h1{{text-align:center;font-size:18px}}
h2{{font-size:16px;border-bottom:1px solid #ccc;padding-bottom:5px}}
</style></head><body>
<h1>ПРОЕКТ ИСПРАВЛЕННОГО ТЕХНИЧЕСКОГО ЗАДАНИЯ</h1>
<p><em>Сформировано: {datetime.now().strftime('%d.%m.%Y')}</em></p>
{sections_html}
<hr><p><em>Пожалуйста, заполните выделенные жёлтым разделы и направьте исправленное ТЗ повторно.</em></p>
</body></html>"""
        return json.dumps({"html": html, "title": d.get("title", "Исправленное ТЗ")})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def generate_email_to_dzo(query: str) -> str:
    """
    Генерирует деловое письмо-ответ в ДЗО с результатами проверки ТЗ.
    Вход: JSON с полями: decision, dzo_name, tz_subject,
    issues (array of strings), recommendations (array of strings),
    has_corrected_tz (bool).
    """
    try:
        d        = json.loads(query)
        decision = d.get("decision", "")
        issues_html = "".join(f"<li>{i}</li>" for i in d.get("issues", []))
        recs_html   = "".join(f"<li>{r}</li>" for r in d.get("recommendations", []))

        corrected_note = ""
        if d.get("has_corrected_tz"):
            corrected_note = (
                "<p>📎 К письму приложен <strong>проект исправленного ТЗ</strong> с цветовой разметкой: "
                "<span style='background:#FFFF00;color:#CC0000;padding:1px 4px'>[ДОБАВЛЕНО]</span> — новые разделы, "
                "<span style='background:#D7FFD7;padding:1px 4px'>[СТАЛО]</span> — исправленный текст, "
                "<span style='background:#FFD7D7;text-decoration:line-through;padding:1px 4px'>[БЫЛО]</span> — удалённый текст.</p>"
            )

        html = f"""<div style="font-family:Arial;font-size:14px;line-height:1.8">
<p>Уважаем(ый/ая) {d.get('dzo_name', 'коллега')}!</p>
<p>Благодарим за направленное ТЗ по теме: <strong>«{d.get('tz_subject', '')}»</strong>.</p>
<p><strong>Результат проверки: {decision}</strong></p>
{"<p>Замечания:<ul>" + issues_html + "</ul></p>" if issues_html else ""}
{"<p>Рекомендации:<ul>" + recs_html + "</ul></p>" if recs_html else ""}
{corrected_note}
<p>С уважением,<br>Служба централизованных закупок</p></div>"""
        return json.dumps({
            "emailHtml": html,
            "decision":  decision,
            "subject":   f"Результат проверки ТЗ: {d.get('tz_subject', '')}",
        })
    except Exception as e:
        return json.dumps({"error": str(e)})
