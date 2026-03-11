import json
from datetime import datetime
from langchain.tools import tool


@tool
def generate_validation_report(query: str) -> str:
    """
    Генерирует JSON-отчёт по чек-листам проверки заявки ДЗО.
    Вход: JSON с полями: decision, checklist_attachments, checklist_required,
    checklist_additional, missing_fields.
    """
    try:
        d = json.loads(query)
        report = {
            "timestamp": datetime.now().isoformat(),
            "decision":  d.get("decision", "Не определено"),
            "checklist_attachments": d.get("checklist_attachments", []),
            "checklist_required":    d.get("checklist_required", []),
            "checklist_additional":  d.get("checklist_additional", []),
            "missing_fields":        d.get("missing_fields", []),
            "stats": {
                "attachments_ok": sum(1 for c in d.get("checklist_attachments", []) if c.get("status") == "Да"),
                "required_ok":    sum(1 for c in d.get("checklist_required", [])    if c.get("status") in ("Да", "ОК")),
                "additional_ok":  sum(1 for c in d.get("checklist_additional", []) if c.get("status") in ("Да", "ОК")),
            },
        }
        return json.dumps(report, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "raw": query})


@tool
def generate_tezis_form(query: str) -> str:
    """
    Генерирует предзаполненную HTML-форму заявки для ЭДО «Тезис».
    Вход: JSON с полями: procurement_subject, justification, budget,
    initiator_name, initiator_contacts, budget_manager,
    recommended_suppliers (array {inn, name}), additional_info, tz_filename.
    """
    try:
        d = json.loads(query)
        fields = [
            ("Предмет закупки",         d.get("procurement_subject")),
            ("Обоснование закупки",     d.get("justification")),
            ("Бюджет, руб.",            d.get("budget")),
            ("Инициатор закупки",       f"{d.get('initiator_name', '')} ({d.get('initiator_contacts', '')})"),
            ("Распорядитель бюджета",   d.get("budget_manager")),
            ("Рекомендуемые поставщики",
             "; ".join(f"{s['name']} (ИНН: {s['inn']})" for s in d.get("recommended_suppliers", []))),
            ("Иная информация",         d.get("additional_info")),
            ("ТЗ (вложение)",           d.get("tz_filename")),
        ]
        rows = "".join(
            f"<tr><th>{label}</th>"
            f"<td class=\"{'filled' if val else 'empty'}\">"
            f"{val or '[Требуется заполнить]'}</td></tr>"
            for label, val in fields
        )
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
body{{font-family:Arial,sans-serif;font-size:14px;margin:40px}}
table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #999;padding:10px}}
th{{background:#e8e8e8;width:40%}}
.filled{{background:#D7FFD7;font-weight:bold}}
.empty{{background:#FFFF00;color:#CC0000;font-style:italic}}
</style></head><body>
<h1 style="text-align:center">ЗАЯВКА НА ЗАКУПКУ — ФОРМА ДЛЯ ЭДО «ТЕЗИС»</h1>
<p><em>Сформировано: {datetime.now().strftime('%d.%m.%Y')}</em></p>
<table>{rows}</table></body></html>"""
        return json.dumps({"tezisFormHtml": html})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def generate_info_request(query: str) -> str:
    """
    Генерирует HTML-письмо запроса недостающей информации.
    Вход: JSON с полями: dzo_name, subject,
    missing_fields (array {field, description}), has_corrected_form.
    """
    try:
        d = json.loads(query)
        rows = "".join(
            f"<tr><td style='border:1px solid #999;padding:8px;font-weight:bold'>{f['field']}</td>"
            f"<td style='border:1px solid #999;padding:8px'>{f['description']}</td></tr>"
            for f in d.get("missing_fields", [])
        )
        html = f"""<div style="font-family:Arial;font-size:14px;line-height:1.8">
<p>Уважаем(ый/ая) {d.get('dzo_name', 'коллега')}!</p>
<p>Благодарим за направленную заявку по теме: <strong>«{d.get('subject', '')}»</strong>.</p>
<p>Для корректного оформления в ЭДО «Тезис» просим предоставить следующую информацию:</p>
<table style="border-collapse:collapse;width:100%">
<tr><th style="border:1px solid #999;padding:8px;background:#e8e8e8">Поле</th>
<th style="border:1px solid #999;padding:8px;background:#e8e8e8">Что необходимо указать</th></tr>
{rows}</table>
<p>Просим направить ответным письмом.</p>
<p>С уважением,<br>Служба централизованных закупок</p></div>"""
        return json.dumps({
            "emailHtml": html,
            "decision":  "Требуется доработка",
            "subject":   f"Запрос информации по заявке: {d.get('subject', '')}",
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def generate_escalation(query: str) -> str:
    """
    Генерирует письмо-эскалацию руководителю.
    Вход: JSON с полями: subject, reason, details.
    """
    try:
        d = json.loads(query)
        html = f"""<div style="font-family:Arial;font-size:14px">
<p><strong>⚠️ ТРЕБУЕТСЯ ЭСКАЛАЦИЯ</strong></p>
<p>Тема заявки: {d.get('subject', '')}</p>
<p>Причина: {d.get('reason', '')}</p>
<p>Детали: {d.get('details', '')}</p>
</div>"""
        return json.dumps({
            "escalationHtml": html,
            "decision": "Требуется эскалация",
            "subject":  f"⚠️ Эскалация заявки ДЗО: {d.get('subject', '')}",
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def generate_response_email(query: str) -> str:
    """
    Генерирует финальное ответное письмо отправителю заявки.
    Вход: JSON с полями: decision, subject, agent_summary.
    """
    try:
        d = json.loads(query)
        html = f"""<div style="font-family:Arial;font-size:14px;line-height:1.8">
<p>Уважаемый коллега!</p>
<p>Ваша заявка по теме <strong>«{d.get('subject', '')}»</strong> была обработана ИИ-инспектором.</p>
<p><strong>Решение: {d.get('decision', '')}</strong></p>
<p>{d.get('agent_summary', '')}</p>
<p>С уважением,<br>Служба централизованных закупок</p></div>"""
        return json.dumps({"emailHtml": html})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def generate_corrected_application(query: str) -> str:
    """
    Генерирует HTML проект исправленной заявки с цветовой разметкой.
    Вход: JSON с полями: fields (array {name, old_value, new_value, status}).
    status: 'added' | 'changed' | 'ok'
    """
    try:
        d = json.loads(query)
        rows = ""
        for f in d.get("fields", []):
            old = f.get("old_value", "")
            new = f.get("new_value", "")
            if f.get("status") == "added":
                rows += (f"<tr><th>{f['name']}</th>"
                         f"<td style='background:#FFFF00;color:#CC0000'>[ДОБАВЛЕНО: {new}]</td></tr>")
            elif old and new:
                rows += (f"<tr><th>{f['name']}</th><td>"
                         f"<span style='background:#FFD7D7;text-decoration:line-through'>[БЫЛО: {old}]</span> → "
                         f"<span style='background:#D7FFD7'>[СТАЛО: {new}]</span></td></tr>")
            else:
                rows += f"<tr><th>{f['name']}</th><td>{new or old}</td></tr>"
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<h1>ПРОЕКТ ИСПРАВЛЕННОЙ ЗАЯВКИ</h1>
<table style="border-collapse:collapse;width:100%">{rows}</table></body></html>"""
        return json.dumps({"correctedHtml": html})
    except Exception as e:
        return json.dumps({"error": str(e)})
