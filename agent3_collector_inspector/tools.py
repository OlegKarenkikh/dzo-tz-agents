"""Инструменты агента сбора анкет участников тендерного отбора (collector).

Provides tools for:
- Filtering emails by tender ID
- Matching email senders to participant list
- Classifying attachments (Anketa / NDA / other)
- Validating anketa data against participant list
- Planning folder structure
- Generating collection report
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from langchain.tools import tool

from shared.agent_tooling import invoke_agent_as_tool
from shared.logger import setup_logger

logger = setup_logger("agent_collector")


# --------------------------------------------------------------------------- #
#  Helper: JSON parsing (same pattern as tender tools)                         #
# --------------------------------------------------------------------------- #

def _parse_query(query: str, tool_name: str):
    """Parse query as JSON, returning dict | None | {}."""
    if not query or not query.strip():
        logger.warning("⚠️ %s: пустой query", tool_name)
        return {}
    q = query.strip()
    try:
        return json.loads(q)
    except json.JSONDecodeError:
        pass
    try:
        obj, _ = json.JSONDecoder().raw_decode(q)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    logger.warning("⚠️ %s: query не является JSON (%d симв.)", tool_name, len(q))
    return None


# --------------------------------------------------------------------------- #
#  Helper: fuzzy company name matching                                         #
# --------------------------------------------------------------------------- #

_ORG_FORM_PATTERN = re.compile(
    r"(?:ООО|ОАО|ЗАО|ПАО|АО|СПАО|НАО|ИП|ГУП|МУП|ФГУП)\s*",
    re.IGNORECASE,
)
_QUOTES_PATTERN = re.compile(r'[«»"\'""„]')
_MULTI_SPACE = re.compile(r"\s+")


def normalize_company_name(name: str) -> str:
    """Strip org form, quotes, extra spaces; lowercase."""
    n = _ORG_FORM_PATTERN.sub("", name)
    n = _QUOTES_PATTERN.sub("", n)
    n = _MULTI_SPACE.sub(" ", n).strip().lower()
    return n


def company_names_match(name_a: str, name_b: str) -> bool:
    """Fuzzy match: strip org form and quotes, compare lowercased."""
    return normalize_company_name(name_a) == normalize_company_name(name_b)


# --------------------------------------------------------------------------- #
#  Helper: tender ID extraction                                                #
# --------------------------------------------------------------------------- #

_TENDER_ID_PATTERN = re.compile(
    r"\d{3,5}[-–—]\s*[А-Яа-яA-Za-z]{2,}[-–—]\s*[А-Яа-яA-Za-z0-9]+",
)


def extract_tender_id(text: str) -> str | None:
    """Extract tender ID like '3115-ДИТ-Сервер' from text."""
    m = _TENDER_ID_PATTERN.search(text)
    return m.group(0) if m else None


def subject_contains_tender_id(subject: str, tender_id: str) -> bool:
    """Check if email subject contains the tender ID (case-insensitive)."""
    return tender_id.lower() in subject.lower()


# --------------------------------------------------------------------------- #
#  Helper: document classification                                             #
# --------------------------------------------------------------------------- #

_ANKETA_MARKERS = [
    "анкета участника тендерного отбора",
    "анкета участника то",
    "анкета участника",
]

_NDA_MARKERS = [
    "соглашение о неразглашении",
    "nda",
    "соглашение о конфиденциальности",
    "non-disclosure agreement",
    "non disclosure agreement",
]


def classify_document(filename: str, content_hint: str = "") -> str:
    """Classify document as 'anketa', 'nda', or 'other'.

    Uses filename and optional content hint (first ~500 chars of extracted text).
    """
    combined = (filename + " " + content_hint).lower()

    for marker in _ANKETA_MARKERS:
        if marker in combined:
            return "anketa"
    # Filename-based anketa detection
    if "анкет" in combined:
        return "anketa"

    for marker in _NDA_MARKERS:
        if marker in combined:
            return "nda"

    return "other"


# --------------------------------------------------------------------------- #
#  Helper: participant matching                                                #
# --------------------------------------------------------------------------- #

def match_participant(
    from_email: str,
    from_name: str,
    inn_from_anketa: str | None,
    participants: list[dict],
) -> dict | None:
    """Match email sender to participant list by email, INN, or name.

    Returns matched participant dict or None.
    """
    from_email_lower = from_email.lower().strip()

    # 1. Match by email
    for p in participants:
        if p.get("contact_email", "").lower().strip() == from_email_lower:
            return p

    # 2. Match by INN from anketa
    if inn_from_anketa:
        inn_clean = inn_from_anketa.strip()
        for p in participants:
            if p.get("inn", "").strip() == inn_clean:
                return p

    # 3. Match by company name (fuzzy)
    if from_name:
        for p in participants:
            if company_names_match(from_name, p.get("name", "")):
                return p

    return None


# --------------------------------------------------------------------------- #
#  Helper: INN validation                                                      #
# --------------------------------------------------------------------------- #

def validate_inn(anketa_inn: str, expected_inn: str) -> bool:
    """Check if INN from anketa matches expected INN."""
    return anketa_inn.strip() == expected_inn.strip()


# --------------------------------------------------------------------------- #
#  Helper: folder structure                                                    #
# --------------------------------------------------------------------------- #

def plan_folder_structure(
    tender_id: str,
    participants: list[dict],
) -> dict[str, str]:
    """Generate folder path mapping for each participant.

    Returns dict: participant_name -> folder_path
    """
    result = {}
    for idx, p in enumerate(participants, start=1):
        name = p.get("name", f"Участник {idx}")
        clean_name = normalize_company_name(name).title()
        folder = f"ТО {tender_id}/Предложения/Участник {idx} – {clean_name}/Документы участника ТО/"
        result[name] = folder
    return result


# --------------------------------------------------------------------------- #
#  Tools                                                                       #
# --------------------------------------------------------------------------- #

@tool
def collect_tender_documents(query: str) -> str:
    """Собирает и анализирует документы участников тендерного отбора.

    ⚠️ Передай ТОЛЬКО структурированный JSON с результатами анализа:
    {
      "tender_id": "3115-ДИТ-Сервер",
      "emails": [
        {
          "from_email": "petrov@romashka.ru",
          "from_name": "Петров П.П.",
          "subject": "Re: Приглашение на участие в ТО 3115-ДИТ-Сервер",
          "body": "...",
          "attachments": [
            {"filename": "Анкета.pdf", "content_type": "application/pdf",
             "size_bytes": 12345, "content_hint": "АНКЕТА УЧАСТНИКА ТО..."},
          ]
        }
      ],
      "participants_list": [
        {"name": "АО «Ромашка»", "inn": "7702365551",
         "contact_person": "Петров П.П.", "contact_email": "petrov@romashka.ru"}
      ]
    }
    """
    try:
        logger.debug("🔧 collect_tender_documents вызван (%d симв.)", len(query) if query else 0)

        if not query or not query.strip():
            return json.dumps(
                {"error": "Пустой запрос инструмента"},
                ensure_ascii=False,
            )

        d = _parse_query(query, "collect_tender_documents")
        if not isinstance(d, dict):
            return json.dumps(
                {"error": "query должен быть JSON-объектом"},
                ensure_ascii=False,
            )

        tender_id = str(d.get("tender_id", "")).strip()
        emails = d.get("emails", [])
        participants_list = d.get("participants_list", [])

        if not tender_id:
            return json.dumps(
                {"error": "Не указан tender_id"},
                ensure_ascii=False,
            )

        if not isinstance(emails, list):
            emails = []
        if not isinstance(participants_list, list):
            participants_list = []
        # Filter out non-dict entries
        participants_list = [p for p in participants_list if isinstance(p, dict)]

        # Track participant status
        participant_results: dict[str, dict] = {}
        for p in participants_list:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name", ""))
            participant_results[name] = {
                "name": name,
                "inn": str(p.get("inn", "")),
                "status": "missing",
                "anketa_received": False,
                "nda_received": False,
                "other_documents": [],
                "inn_match": None,
                "name_match": None,
                "discrepancies": [],
                "folder_path": "",
            }

        # Plan folder structure
        folders = plan_folder_structure(tender_id, participants_list)
        for name, folder in folders.items():
            if name in participant_results:
                participant_results[name]["folder_path"] = folder

        discrepancies: list[dict] = []

        # Process each email
        for email in emails:
            if not isinstance(email, dict):
                continue

            subject = str(email.get("subject", ""))
            from_email = str(email.get("from_email", ""))
            from_name = str(email.get("from_name", ""))
            attachments = email.get("attachments", [])

            # Filter: subject must contain tender ID
            if not subject_contains_tender_id(subject, tender_id):
                continue

            # Try to find INN in attachment content hints
            inn_from_anketa = None
            for att in (attachments or []):
                if not isinstance(att, dict):
                    continue
                hint = str(att.get("content_hint", ""))
                # Look for INN pattern in content hint
                inn_match = re.search(r"ИНН[:\s]*(\d{10,12})", hint)
                if inn_match:
                    inn_from_anketa = inn_match.group(1)
                    break

            # Match to participant
            matched = match_participant(
                from_email, from_name, inn_from_anketa, participants_list,
            )
            if not matched:
                continue

            matched_name = str(matched.get("name", ""))
            if matched_name not in participant_results:
                continue

            pr = participant_results[matched_name]
            pr["status"] = "received"

            # Classify attachments
            for att in (attachments or []):
                if not isinstance(att, dict):
                    continue
                filename = str(att.get("filename", ""))
                content_hint = str(att.get("content_hint", ""))
                doc_type = classify_document(filename, content_hint)

                if doc_type == "anketa":
                    pr["anketa_received"] = True
                    # Validate INN
                    if inn_from_anketa:
                        expected_inn = str(matched.get("inn", ""))
                        inn_ok = validate_inn(inn_from_anketa, expected_inn)
                        pr["inn_match"] = inn_ok
                        if not inn_ok:
                            disc = {
                                "participant": matched_name,
                                "field": "inn",
                                "expected": expected_inn,
                                "actual": inn_from_anketa,
                            }
                            pr["discrepancies"].append(disc)
                            discrepancies.append(disc)

                    # Validate company name from content hint
                    name_in_anketa = None
                    name_match_re = re.search(
                        r"(?:Наименование|Организация|Компания)[:\s]*(.+?)(?:\n|$)",
                        content_hint,
                        re.IGNORECASE,
                    )
                    if name_match_re:
                        name_in_anketa = name_match_re.group(1).strip()

                    if name_in_anketa:
                        name_ok = company_names_match(name_in_anketa, matched_name)
                        pr["name_match"] = name_ok
                        if not name_ok:
                            disc = {
                                "participant": matched_name,
                                "field": "name",
                                "expected": matched_name,
                                "actual": name_in_anketa,
                            }
                            pr["discrepancies"].append(disc)
                            discrepancies.append(disc)
                    else:
                        pr["name_match"] = True  # No name to compare -> assume OK

                elif doc_type == "nda":
                    pr["nda_received"] = True
                else:
                    pr["other_documents"].append(filename)

        # Build report
        received_count = sum(1 for pr in participant_results.values() if pr["status"] == "received")
        missing_count = sum(1 for pr in participant_results.values() if pr["status"] == "missing")

        report_lines = [
            f"Отчёт о сборе документов по ТО {tender_id}",
            f"Дата: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
            f"Всего ожидаемых участников: {len(participants_list)}",
            f"Получены документы от: {received_count}",
            f"Не получены от: {missing_count}",
            "",
        ]

        for pr in participant_results.values():
            status_icon = "✅" if pr["status"] == "received" else "❌"
            report_lines.append(f"{status_icon} {pr['name']} (ИНН: {pr['inn']})")
            if pr["status"] == "received":
                report_lines.append(f"  Анкета: {'✅' if pr['anketa_received'] else '❌'}")
                report_lines.append(f"  NDA: {'✅' if pr['nda_received'] else '❌'}")
                if pr["discrepancies"]:
                    for disc in pr["discrepancies"]:
                        report_lines.append(
                            f"  ⚠️ Расхождение {disc['field']}: "
                            f"ожидалось {disc['expected']!r}, получено {disc['actual']!r}"
                        )
            else:
                report_lines.append("  Документы не получены")
            report_lines.append("")

        result = {
            "tender_id": tender_id,
            "total_expected_participants": len(participants_list),
            "received_count": received_count,
            "missing_count": missing_count,
            "participants": list(participant_results.values()),
            "discrepancies": discrepancies,
            "folder_structure": folders,
            "report_text": "\n".join(report_lines),
        }

        logger.info(
            "✅ collect_tender_documents: %d/%d участников прислали документы",
            received_count, len(participants_list),
        )
        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        logger.error("❌ collect_tender_documents: ошибка %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@tool
def invoke_peer_agent(query: str) -> str:
    """Универсальный вызов другого агента как инструмента.

    Ожидает JSON:
    {"target_agent":"dzo|tz|tender|...","query_text":"...","subject":"...","sender":"..."}
    """
    try:
        d = _parse_query(query, "invoke_peer_agent")
        if not isinstance(d, dict):
            return json.dumps({"error": "query должен быть JSON-объектом"}, ensure_ascii=False)

        target_agent = str(d.get("target_agent", "")).strip()
        query_text = str(d.get("query_text", "")).strip()
        if not target_agent or not query_text:
            return json.dumps(
                {"error": "Обязательные поля: target_agent, query_text"},
                ensure_ascii=False,
            )

        result = invoke_agent_as_tool(
            source_agent="collector",
            target_agent=target_agent,
            chat_input=query_text,
            metadata={
                "delegated_by": "collector",
                "subject": str(d.get("subject", "")),
                "sender": str(d.get("sender", "")),
            },
        )

        return json.dumps(
            {
                "peerAgentResult": {
                    "target_agent": target_agent,
                    "output": result.get("output", ""),
                    "observations": result.get("observations", []),
                }
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error("❌ invoke_peer_agent(collector): ошибка %s", e)
        return json.dumps(
            {
                "peerAgentResult": {
                    "target_agent": "",
                    "output": "",
                    "observations": [],
                    "error": str(e),
                }
            },
            ensure_ascii=False,
        )
