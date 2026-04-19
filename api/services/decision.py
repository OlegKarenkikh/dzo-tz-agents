"""
Нормализация решений агентов и пост-проверки артефактов.

Перенесено из api/app.py (TD-01).
"""
import html
import json
import logging
import re as _re_mod

logger = logging.getLogger("api")

_KNOWN_DECISIONS = {
    "ПРИНЯТЬ", "ПРИНЯТЬ С ЗАМЕЧАНИЕМ", "ВЕРНУТЬ НА ДОРАБОТКУ",
    "ЗАЯВКА ПОЛНАЯ", "ТРЕБУЕТСЯ ДОРАБОТКА", "ТРЕБУЕТСЯ ЭСКАЛАЦИЯ",
    "ДОКУМЕНТАЦИЯ ПОЛНАЯ", "КРИТИЧЕСКИЕ НАРУШЕНИЯ",
    "СБОР ЗАВЕРШЁН", "СБОР НЕ ЗАВЕРШЁН", "ТРЕБУЕТСЯ ПРОВЕРКА",
    "СООТВЕТСТВУЕТ", "НЕ СООТВЕТСТВУЕТ",
}

_DECISION_SYNONYMS: dict[str, str] = {
    "СООТВЕТСТВУЕТ": "ПРИНЯТЬ",
    "НЕ СООТВЕТСТВУЕТ": "ВЕРНУТЬ НА ДОРАБОТКУ",
    "ТРЕБУЕТ ДОРАБОТКИ": "ВЕРНУТЬ НА ДОРАБОТКУ",
    "ТРЕБУЕТСЯ ДОРАБОТКА": "ВЕРНУТЬ НА ДОРАБОТКУ",
    "ЗАЯВКА ПОЛНАЯ": "ЗАЯВКА ПОЛНАЯ",
}

_TECHNICAL_STATUSES = {
    "documents_found", "tool_error", "tool_calls_missing",
    "token_limit_exhausted", "rate_limit_exhausted", "Неизвестно",
}


def normalize_decision(current_decision: str, output: str) -> tuple[str, str | None]:
    """Извлекает экспертное решение из output агента."""
    canonical = _DECISION_SYNONYMS.get(current_decision.upper())
    if canonical:
        return canonical, None

    if current_decision.upper() in _KNOWN_DECISIONS:
        return current_decision, None

    if not output:
        return current_decision, None

    def _apply_synonyms(val: str) -> str:
        return _DECISION_SYNONYMS.get(val.upper(), val)

    json_match = _re_mod.search(r'```json\s*(\{.*?\})\s*```', output, _re_mod.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(1))
            if isinstance(parsed, dict):
                for key in ("decision", "expert_decision", "verdict", "status"):
                    val = parsed.get(key)
                    if isinstance(val, str) and val.upper() in _KNOWN_DECISIONS:
                        return _apply_synonyms(val), current_decision
        except (json.JSONDecodeError, TypeError):
            pass

    dec_match = _re_mod.search(r'"decision"\s*:\s*"([^"]+)"', output)
    if dec_match:
        val = dec_match.group(1).strip()
        if val.upper() in _KNOWN_DECISIONS:
            return _apply_synonyms(val), current_decision

    md_match = _re_mod.search(r'Оценка:\s*\*?\*?([^*\n]+)', output)
    if md_match:
        val = md_match.group(1).strip()
        if val.upper() in _KNOWN_DECISIONS:
            return _apply_synonyms(val), current_decision

    status_match = _re_mod.search(r'"status"\s*:\s*"([^"]+)"', output)
    if status_match:
        val = status_match.group(1).strip()
        if val.upper() in _KNOWN_DECISIONS:
            return _apply_synonyms(val), current_decision

    md_status_match = _re_mod.search(
        r'\*\*(?:Статус|Решение|Итог)\s*:?\*\*\s*\*?\*?([^*\n]+)', output
    )
    if md_status_match:
        val = md_status_match.group(1).strip()
        if val.upper() in _KNOWN_DECISIONS:
            return _apply_synonyms(val), current_decision

    return current_decision, None


def is_result_usable_for_agent(agent_type: str, model_result: dict) -> tuple[bool, str]:
    if not isinstance(model_result, dict):
        return False, "InvalidResultType"
    steps = model_result.get("intermediate_steps", []) or []
    if len(steps) == 0:
        return False, "NoToolCalls"
    return True, ""


def looks_like_tz_content(*, text: str, subject: str, attachment_names: list[str]) -> bool:
    keywords = ("тз", "tz", "техзад", "technical specification", "техническое задание")
    haystacks = [text or "", subject or "", " ".join(attachment_names or [])]
    joined = "\n".join(haystacks).lower()
    return any(k in joined for k in keywords)


def has_tz_agent_analysis_observation(model_result: dict) -> bool:
    if not isinstance(model_result, dict):
        return False
    for step in model_result.get("intermediate_steps", []) or []:
        if not isinstance(step, (list, tuple)) or len(step) < 2:
            continue
        obs = step[1]
        if isinstance(obs, str):
            try:
                obs = json.loads(obs)
            except json.JSONDecodeError:
                continue
        if isinstance(obs, dict) and isinstance(obs.get("tzAgentAnalysis"), dict):
            return True
    return False


def is_token_limit_error_text(error_text: str) -> bool:
    text = (error_text or "").lower()
    return (
        "tokens_limit_reached" in text
        or "413" in text
        or "too large" in text
        or "max size" in text
    )


def apply_email_artifact(artifacts: dict, tool_name: str, email_html: str) -> None:
    """Сохраняет email-артефакт с приоритетом decision-специфичных шаблонов."""
    if not email_html:
        return
    if tool_name == "generate_response_email" and artifacts.get("email_html"):
        artifacts["response_email_html"] = email_html
        return
    artifacts["email_html"] = email_html


def attachment_meta(attachments: list) -> list[dict]:
    """Формирует metadata-only список вложений (без content_base64)."""
    result = []
    for a in attachments:
        b64 = a.content_base64
        size = max(0, len(b64) * 3 // 4 - b64.count("="))
        result.append({"filename": a.filename, "mime_type": a.mime_type, "size_bytes": size})
    return result


def enrich_email_with_tz_summary(artifacts: dict) -> None:
    """Дополняет email_html результатом анализа ТЗ если он есть."""
    tz_summary = (artifacts.get("tz_agent_analysis") or {}).get("summary", "")
    if tz_summary and artifacts.get("email_html"):
        safe_summary = html.escape(str(tz_summary))
        if safe_summary not in artifacts["email_html"]:
            artifacts["email_html"] += (
                "<hr><div style='font-family:Arial'>"
                "<p><strong>Результат анализа технического задания:</strong></p>"
                f"<p>{safe_summary}</p>"
                "</div>"
            )
