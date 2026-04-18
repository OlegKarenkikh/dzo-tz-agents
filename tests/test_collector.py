"""Comprehensive tests for the collector agent (document collection for tender selection).

Tests cover:
- Document classification (anketa vs NDA vs other)
- Participant matching (by email, by INN, by name)
- Tender ID extraction from email subjects
- Validation logic (INN mismatch, name mismatch)
- Report generation
- Edge cases (missing documents, wrong tender ID, etc.)
- Folder structure planning
- Company name normalization and fuzzy matching
- collect_tender_documents tool
- Agent creation and invocation
- MCP tool registration
- API endpoint registration
"""

import json

import pytest

from agent3_collector_inspector.tools import (
    classify_document,
    collect_tender_documents,
    company_names_match,
    extract_tender_id,
    match_participant,
    normalize_company_name,
    plan_folder_structure,
    subject_contains_tender_id,
    validate_inn,
)


# ============================================================================
# Fixtures
# ============================================================================

PARTICIPANTS = [
    {
        "name": 'АО "Ромашка"',
        "inn": "7702365551",
        "contact_person": "Петров П.П.",
        "contact_email": "petrov@romashka.ru",
    },
    {
        "name": 'АО "Лютик"',
        "inn": "7702365751",
        "contact_person": "Сидоров С.В.",
        "contact_email": "sidorov@lutik.ru",
    },
    {
        "name": 'ООО "Гвоздика"',
        "inn": "7704565559",
        "contact_person": "Иванов П.А.",
        "contact_email": "ivanov@gvozdika.ru",
    },
]

TENDER_ID = "3115-ДИТ-Сервер"


def _make_email(
    from_email: str,
    from_name: str,
    subject: str,
    attachments: list[dict] | None = None,
    body: str = "",
) -> dict:
    return {
        "from_email": from_email,
        "from_name": from_name,
        "subject": subject,
        "body": body,
        "attachments": attachments or [],
    }


def _make_attachment(
    filename: str,
    content_hint: str = "",
    content_type: str = "application/pdf",
    size_bytes: int = 10000,
) -> dict:
    return {
        "filename": filename,
        "content_type": content_type,
        "size_bytes": size_bytes,
        "content_hint": content_hint,
    }


# ============================================================================
# Document Classification Tests
# ============================================================================

class TestClassifyDocument:
    def test_anketa_by_filename(self):
        assert classify_document("Анкета участника ТО 3115.pdf") == "anketa"

    def test_anketa_by_content_hint(self):
        assert classify_document(
            "document.pdf",
            "АНКЕТА УЧАСТНИКА ТЕНДЕРНОГО ОТБОРА 3115-ДИТ-Сервер",
        ) == "anketa"

    def test_anketa_partial_match(self):
        assert classify_document("Анкета_компании.docx") == "anketa"

    def test_nda_by_filename(self):
        assert classify_document("NDA.pdf") == "nda"

    def test_nda_russian(self):
        assert classify_document("Соглашение о неразглашении.pdf") == "nda"

    def test_nda_by_content(self):
        assert classify_document(
            "agreement.pdf",
            "Соглашение о конфиденциальности между сторонами",
        ) == "nda"

    def test_nda_english(self):
        assert classify_document("Non-Disclosure Agreement.pdf") == "nda"

    def test_other_document(self):
        assert classify_document("Referens-list.pdf") == "other"

    def test_other_certificate(self):
        assert classify_document("Сертификат ISO 9001.pdf") == "other"

    def test_empty_filename(self):
        assert classify_document("") == "other"

    def test_anketa_case_insensitive(self):
        assert classify_document("АНКЕТА.PDF") == "anketa"

    def test_nda_case_insensitive(self):
        assert classify_document("nda_signed.pdf") == "nda"


# ============================================================================
# Participant Matching Tests
# ============================================================================

class TestMatchParticipant:
    def test_match_by_email(self):
        result = match_participant(
            "petrov@romashka.ru", "", None, PARTICIPANTS,
        )
        assert result is not None
        assert result["inn"] == "7702365551"

    def test_match_by_email_case_insensitive(self):
        result = match_participant(
            "Petrov@Romashka.RU", "", None, PARTICIPANTS,
        )
        assert result is not None
        assert result["inn"] == "7702365551"

    def test_match_by_inn(self):
        result = match_participant(
            "unknown@example.com", "", "7704565559", PARTICIPANTS,
        )
        assert result is not None
        assert result["name"] == 'ООО "Гвоздика"'

    def test_match_by_name(self):
        result = match_participant(
            "unknown@example.com", 'АО "Лютик"', None, PARTICIPANTS,
        )
        assert result is not None
        assert result["inn"] == "7702365751"

    def test_no_match(self):
        result = match_participant(
            "stranger@example.com", "Unknown Co", None, PARTICIPANTS,
        )
        assert result is None

    def test_match_priority_email_first(self):
        """Email match takes priority over INN."""
        result = match_participant(
            "petrov@romashka.ru", "", "7704565559", PARTICIPANTS,
        )
        assert result is not None
        # Matched by email, not INN
        assert result["inn"] == "7702365551"

    def test_match_by_inn_when_email_unknown(self):
        result = match_participant(
            "unknown@example.com", "", "7702365751", PARTICIPANTS,
        )
        assert result is not None
        assert result["name"] == 'АО "Лютик"'

    def test_match_empty_participants(self):
        result = match_participant("any@email.com", "Any", "123", [])
        assert result is None


# ============================================================================
# Tender ID Extraction Tests
# ============================================================================

class TestTenderIdExtraction:
    def test_extract_from_subject(self):
        assert extract_tender_id("Re: Приглашение на участие в ТО 3115-ДИТ-Сервер") == "3115-ДИТ-Сервер"

    def test_extract_from_simple_subject(self):
        assert extract_tender_id("ТО 3115-ДИТ-Сервер документы") == "3115-ДИТ-Сервер"

    def test_no_tender_id(self):
        assert extract_tender_id("Обычное письмо без номера ТО") is None

    def test_subject_contains_tender_id_true(self):
        assert subject_contains_tender_id(
            "Re: ТО 3115-ДИТ-Сервер", "3115-ДИТ-Сервер",
        )

    def test_subject_contains_tender_id_case_insensitive(self):
        assert subject_contains_tender_id(
            "Документы к ТО 3115-дит-сервер", "3115-ДИТ-Сервер",
        )

    def test_subject_missing_tender_id(self):
        assert not subject_contains_tender_id(
            "Обычное письмо", "3115-ДИТ-Сервер",
        )

    def test_subject_wrong_tender_id(self):
        assert not subject_contains_tender_id(
            "ТО 4444-ДИТ-Другой", "3115-ДИТ-Сервер",
        )


# ============================================================================
# INN Validation Tests
# ============================================================================

class TestValidateInn:
    def test_matching_inn(self):
        assert validate_inn("7702365551", "7702365551") is True

    def test_mismatching_inn(self):
        assert validate_inn("7702365551", "7704565559") is False

    def test_inn_with_spaces(self):
        assert validate_inn(" 7702365551 ", "7702365551") is True

    def test_empty_inn(self):
        assert validate_inn("", "7702365551") is False


# ============================================================================
# Company Name Normalization Tests
# ============================================================================

class TestCompanyNameNormalization:
    def test_strip_ooo(self):
        assert normalize_company_name('ООО "Гвоздика"') == "гвоздика"

    def test_strip_ao(self):
        assert normalize_company_name('АО "Ромашка"') == "ромашка"

    def test_strip_pao(self):
        assert normalize_company_name('ПАО "Сбербанк"') == "сбербанк"

    def test_strip_spao(self):
        assert normalize_company_name('Страховая компания') == "страховая компания"

    def test_strip_guillemets(self):
        assert normalize_company_name("АО «Ромашка»") == "ромашка"

    def test_strip_double_quotes(self):
        assert normalize_company_name('АО "Ромашка"') == "ромашка"

    def test_normalize_spaces(self):
        assert normalize_company_name('ООО  "Газ   Нефть"') == "газ нефть"

    def test_company_names_match_same_org_form(self):
        assert company_names_match('АО "Ромашка"', 'АО "Ромашка"')

    def test_company_names_match_different_org_form(self):
        assert company_names_match('ООО "Ромашка"', 'АО "Ромашка"')

    def test_company_names_match_different_quotes(self):
        assert company_names_match('АО «Ромашка»', 'АО "Ромашка"')

    def test_company_names_no_match(self):
        assert not company_names_match('АО "Ромашка"', 'АО "Лютик"')

    def test_empty_names(self):
        assert company_names_match("", "")

    def test_org_form_only(self):
        # Both reduce to empty string after stripping
        assert company_names_match("ООО", "АО")


# ============================================================================
# Folder Structure Tests
# ============================================================================

class TestFolderStructure:
    def test_basic_structure(self):
        folders = plan_folder_structure("3115-ДИТ-Сервер", PARTICIPANTS)
        assert len(folders) == 3
        for name in ['АО "Ромашка"', 'АО "Лютик"', 'ООО "Гвоздика"']:
            assert name in folders
            assert "ТО 3115-ДИТ-Сервер" in folders[name]
            assert "Предложения" in folders[name]
            assert "Документы участника ТО" in folders[name]

    def test_participant_numbering(self):
        folders = plan_folder_structure("3115-ДИТ-Сервер", PARTICIPANTS)
        paths = list(folders.values())
        assert "Участник 1" in paths[0]
        assert "Участник 2" in paths[1]
        assert "Участник 3" in paths[2]

    def test_empty_participants(self):
        folders = plan_folder_structure("3115-ДИТ-Сервер", [])
        assert folders == {}


# ============================================================================
# collect_tender_documents Tool Tests
# ============================================================================

class TestCollectTenderDocuments:
    def _invoke(self, data: dict) -> dict:
        result_str = collect_tender_documents.invoke(json.dumps(data, ensure_ascii=False))
        return json.loads(result_str)

    def test_all_participants_received(self):
        """All 3 participants sent anketa and NDA."""
        emails = [
            _make_email(
                "petrov@romashka.ru", "Петров П.П.",
                f"Re: ТО {TENDER_ID}",
                [
                    _make_attachment("Анкета Ромашка.pdf", f"АНКЕТА УЧАСТНИКА ТО {TENDER_ID}\nИНН: 7702365551"),
                    _make_attachment("NDA.pdf"),
                ],
            ),
            _make_email(
                "sidorov@lutik.ru", "Сидоров С.В.",
                f"Документы к ТО {TENDER_ID}",
                [
                    _make_attachment("Анкета.pdf", f"АНКЕТА УЧАСТНИКА ТО {TENDER_ID}\nИНН: 7702365751"),
                    _make_attachment("Соглашение о неразглашении.pdf"),
                ],
            ),
            _make_email(
                "ivanov@gvozdika.ru", "Иванов П.А.",
                f"ТО {TENDER_ID} анкета и NDA",
                [
                    _make_attachment("Анкета_Гвоздика.docx", "Анкета участника\nИНН: 7704565559"),
                    _make_attachment("NDA_signed.pdf"),
                ],
            ),
        ]
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": emails,
            "participants_list": PARTICIPANTS,
        })
        assert result["tender_id"] == TENDER_ID
        assert result["total_expected_participants"] == 3
        assert result["received_count"] == 3
        assert result["missing_count"] == 0
        for p in result["participants"]:
            assert p["status"] == "received"
            assert p["anketa_received"] is True
            assert p["nda_received"] is True

    def test_one_participant_missing(self):
        """Only 2 out of 3 participants responded."""
        emails = [
            _make_email(
                "petrov@romashka.ru", "Петров П.П.",
                f"Re: ТО {TENDER_ID}",
                [
                    _make_attachment("Анкета.pdf", "АНКЕТА\nИНН: 7702365551"),
                    _make_attachment("NDA.pdf"),
                ],
            ),
            _make_email(
                "sidorov@lutik.ru", "Сидоров С.В.",
                f"ТО {TENDER_ID}",
                [
                    _make_attachment("Анкета Лютик.pdf", "Анкета\nИНН: 7702365751"),
                    _make_attachment("NDA Лютик.pdf", "Соглашение о неразглашении"),
                ],
            ),
        ]
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": emails,
            "participants_list": PARTICIPANTS,
        })
        assert result["received_count"] == 2
        assert result["missing_count"] == 1
        missing = [p for p in result["participants"] if p["status"] == "missing"]
        assert len(missing) == 1
        assert missing[0]["name"] == 'ООО "Гвоздика"'

    def test_inn_mismatch_discrepancy(self):
        """Anketa has different INN than expected."""
        emails = [
            _make_email(
                "petrov@romashka.ru", "Петров П.П.",
                f"ТО {TENDER_ID}",
                [
                    _make_attachment("Анкета.pdf", "АНКЕТА\nИНН: 9999999999"),
                ],
            ),
        ]
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": emails,
            "participants_list": PARTICIPANTS,
        })
        romashka = next(p for p in result["participants"] if p["inn"] == "7702365551")
        assert romashka["status"] == "received"
        assert romashka["inn_match"] is False
        assert len(romashka["discrepancies"]) > 0
        assert romashka["discrepancies"][0]["field"] == "inn"
        assert result["discrepancies"][0]["expected"] == "7702365551"
        assert result["discrepancies"][0]["actual"] == "9999999999"

    def test_email_without_tender_id_ignored(self):
        """Emails without tender ID in subject are ignored."""
        emails = [
            _make_email(
                "petrov@romashka.ru", "Петров П.П.",
                "Обычное письмо без номера ТО",
                [_make_attachment("Анкета.pdf", "АНКЕТА\nИНН: 7702365551")],
            ),
        ]
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": emails,
            "participants_list": PARTICIPANTS,
        })
        assert result["received_count"] == 0
        assert result["missing_count"] == 3

    def test_empty_emails(self):
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": [],
            "participants_list": PARTICIPANTS,
        })
        assert result["received_count"] == 0
        assert result["missing_count"] == 3

    def test_empty_participants(self):
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": [],
            "participants_list": [],
        })
        assert result["received_count"] == 0
        assert result["missing_count"] == 0
        assert result["total_expected_participants"] == 0

    def test_no_tender_id_error(self):
        result = self._invoke({
            "tender_id": "",
            "emails": [],
            "participants_list": [],
        })
        assert "error" in result

    def test_empty_query(self):
        result_str = collect_tender_documents.invoke("")
        result = json.loads(result_str)
        assert "error" in result

    def test_invalid_json_query(self):
        result_str = collect_tender_documents.invoke("not json at all")
        result = json.loads(result_str)
        assert "error" in result

    def test_report_text_generated(self):
        """Report text is generated and contains key info."""
        emails = [
            _make_email(
                "petrov@romashka.ru", "Петров",
                f"ТО {TENDER_ID}",
                [_make_attachment("Анкета.pdf", "Анкета\nИНН: 7702365551")],
            ),
        ]
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": emails,
            "participants_list": PARTICIPANTS,
        })
        assert "report_text" in result
        assert TENDER_ID in result["report_text"]
        assert "Ромашка" in result["report_text"]

    def test_folder_structure_in_result(self):
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": [],
            "participants_list": PARTICIPANTS,
        })
        assert "folder_structure" in result
        assert len(result["folder_structure"]) == 3

    def test_nda_only_no_anketa(self):
        """Participant sends NDA but not anketa."""
        emails = [
            _make_email(
                "petrov@romashka.ru", "Петров П.П.",
                f"ТО {TENDER_ID}",
                [_make_attachment("NDA_signed.pdf")],
            ),
        ]
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": emails,
            "participants_list": PARTICIPANTS,
        })
        romashka = next(p for p in result["participants"] if p["inn"] == "7702365551")
        assert romashka["status"] == "received"
        assert romashka["anketa_received"] is False
        assert romashka["nda_received"] is True

    def test_anketa_only_no_nda(self):
        """Participant sends anketa but not NDA."""
        emails = [
            _make_email(
                "sidorov@lutik.ru", "Сидоров",
                f"ТО {TENDER_ID}",
                [_make_attachment("Анкета.pdf", "Анкета\nИНН: 7702365751")],
            ),
        ]
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": emails,
            "participants_list": PARTICIPANTS,
        })
        lutik = next(p for p in result["participants"] if p["inn"] == "7702365751")
        assert lutik["anketa_received"] is True
        assert lutik["nda_received"] is False

    def test_other_documents_tracked(self):
        """Non-anketa non-NDA documents are listed in other_documents."""
        emails = [
            _make_email(
                "petrov@romashka.ru", "Петров",
                f"ТО {TENDER_ID}",
                [
                    _make_attachment("Анкета.pdf", "Анкета\nИНН: 7702365551"),
                    _make_attachment("Referens-list.pdf"),
                    _make_attachment("Сертификат.pdf"),
                ],
            ),
        ]
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": emails,
            "participants_list": PARTICIPANTS,
        })
        romashka = next(p for p in result["participants"] if p["inn"] == "7702365551")
        assert len(romashka["other_documents"]) == 2
        assert "Referens-list.pdf" in romashka["other_documents"]
        assert "Сертификат.pdf" in romashka["other_documents"]

    def test_unknown_sender_ignored(self):
        """Email from unknown sender (not in participants list) is ignored."""
        emails = [
            _make_email(
                "stranger@unknown.com", "Unknown",
                f"ТО {TENDER_ID}",
                [_make_attachment("Анкета.pdf", "Анкета\nИНН: 0000000000")],
            ),
        ]
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": emails,
            "participants_list": PARTICIPANTS,
        })
        assert result["received_count"] == 0

    def test_name_mismatch_discrepancy(self):
        """Company name in anketa doesn't match participants list."""
        emails = [
            _make_email(
                "petrov@romashka.ru", "Петров",
                f"ТО {TENDER_ID}",
                [
                    _make_attachment(
                        "Анкета.pdf",
                        "АНКЕТА\nИНН: 7702365551\nНаименование: ОАО Совсем Другое",
                    ),
                ],
            ),
        ]
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": emails,
            "participants_list": PARTICIPANTS,
        })
        romashka = next(p for p in result["participants"] if p["inn"] == "7702365551")
        assert romashka["name_match"] is False
        has_name_disc = any(d["field"] == "name" for d in romashka["discrepancies"])
        assert has_name_disc

    def test_non_dict_email_skipped(self):
        """Non-dict items in emails list are skipped."""
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": ["not-a-dict", 42, None],
            "participants_list": PARTICIPANTS,
        })
        assert result["received_count"] == 0

    def test_non_dict_participant_skipped(self):
        """Non-dict items in participants_list are skipped."""
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": [],
            "participants_list": ["not-a-dict"],
        })
        assert result["total_expected_participants"] == 0

    def test_non_dict_attachment_skipped(self):
        """Non-dict attachments are skipped gracefully."""
        emails = [
            _make_email(
                "petrov@romashka.ru", "Петров",
                f"ТО {TENDER_ID}",
                ["not-a-dict", 42],
            ),
        ]
        result = self._invoke({
            "tender_id": TENDER_ID,
            "emails": emails,
            "participants_list": PARTICIPANTS,
        })
        romashka = next(p for p in result["participants"] if p["inn"] == "7702365551")
        assert romashka["status"] == "received"
        assert romashka["anketa_received"] is False


# ============================================================================
# Agent Creation Tests
# ============================================================================

class TestCollectorAgent:
    def test_create_agent(self):
        from agent3_collector_inspector.agent import create_collector_agent
        agent = create_collector_agent()
        assert agent is not None
        assert hasattr(agent, "invoke")

    def test_agent_invoke(self):
        from agent3_collector_inspector.agent import create_collector_agent
        agent = create_collector_agent()
        result = agent.invoke({"input": "test input"})
        assert isinstance(result, dict)
        assert "output" in result
        assert "intermediate_steps" in result


# ============================================================================
# AGENT_REGISTRY Integration Tests
# ============================================================================

class TestCollectorRegistration:
    def test_collector_in_registry(self):
        from api.app import AGENT_REGISTRY
        assert "collector" in AGENT_REGISTRY

    def test_collector_has_required_fields(self):
        from api.app import AGENT_REGISTRY
        collector = AGENT_REGISTRY["collector"]
        assert "name" in collector
        assert "description" in collector
        assert "decisions" in collector
        assert "auto_detect" in collector
        assert "keywords" in collector["auto_detect"]
        assert "priority" in collector["auto_detect"]

    def test_collector_auto_detect_keywords(self):
        from api.app import AGENT_REGISTRY
        keywords = AGENT_REGISTRY["collector"]["auto_detect"]["keywords"]
        assert "тендерный отбор" in keywords
        assert "анкета участника" in keywords
        assert "nda" in keywords

    def test_collector_resolve_by_keyword(self):
        """Test that resolve-agent picks collector for collector-unique keywords."""
        from api.app import ProcessRequest, _resolve_agent
        # Use keywords unique to collector that won't match higher-priority agents
        req = ProcessRequest(text="нужен сбор анкет от участников, анкета участника")
        agent_id, keyword = _resolve_agent(req)
        assert agent_id == "collector"

    def test_collector_in_agents_endpoint(self):
        from fastapi.testclient import TestClient
        from api.app import app
        client = TestClient(app)
        resp = client.get("/agents")
        assert resp.status_code == 200
        agents = resp.json()["agents"]
        ids = [a["id"] for a in agents]
        assert "collector" in ids


# ============================================================================
# MCP Integration Tests
# ============================================================================

class TestCollectorMCP:
    def test_collector_in_mcp_tool_map(self):
        from shared.mcp_server import _AGENT_TOOL_MAP
        assert "collector" in _AGENT_TOOL_MAP
        assert _AGENT_TOOL_MAP["collector"] == "collect_documents"

    def test_list_agents_includes_collector(self):
        from shared.mcp_server import list_agents
        result = list_agents()
        ids = [a["id"] for a in result["agents"]]
        assert "collector" in ids
        collector = next(a for a in result["agents"] if a["id"] == "collector")
        assert collector["tool"] == "collect_documents"


# ============================================================================
# A2A Agent Card Tests
# ============================================================================

class TestCollectorA2A:
    def test_agent_card_includes_collector(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from api.app import app
        with patch("api.app.PUBLIC_BASE_URL", "http://localhost:8000"):
            client = TestClient(app)
            resp = client.get("/.well-known/agent.json")
            assert resp.status_code == 200
            card = resp.json()
            skill_ids = [s["id"] for s in card["skills"]]
            assert "collect_documents" in skill_ids


# ============================================================================
# Agent Tooling Integration Tests
# ============================================================================

class TestCollectorAgentTooling:
    def test_collector_in_default_registry(self):
        from shared.agent_tooling import _DEFAULT_AGENT_FACTORY_REGISTRY
        assert "collector" in _DEFAULT_AGENT_FACTORY_REGISTRY
        assert "create_collector_agent" in _DEFAULT_AGENT_FACTORY_REGISTRY["collector"]


# ============================================================================
# API Endpoint Tests
# ============================================================================

class TestCollectorAPI:
    def test_process_collector_endpoint_exists(self):
        from fastapi.testclient import TestClient
        from api.app import app
        client = TestClient(app)
        # Without API key should get 401
        resp = client.post(
            "/api/v1/process/collector",
            json={"text": "test"},
        )
        assert resp.status_code == 401

    def test_process_collector_with_api_key(self):
        from fastapi.testclient import TestClient
        from api.app import app
        client = TestClient(app)
        resp = client.post(
            "/api/v1/process/collector",
            json={"text": "Сбор анкет участников тендерного отбора"},
            headers={"X-API-Key": os.environ.get("API_KEY", "sandbox-test-api-key-12345")},
        )
        # Should return 200 with job_id (background processing)
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data or "duplicate" in data


# ============================================================================
# Edge Case Tests
# ============================================================================

class TestCollectorEdgeCases:
    def test_multiple_emails_from_same_participant(self):
        """Same participant sends multiple emails — all are processed."""
        emails = [
            _make_email(
                "petrov@romashka.ru", "Петров",
                f"ТО {TENDER_ID} - анкета",
                [_make_attachment("Анкета.pdf", "Анкета\nИНН: 7702365551")],
            ),
            _make_email(
                "petrov@romashka.ru", "Петров",
                f"ТО {TENDER_ID} - NDA",
                [_make_attachment("NDA.pdf")],
            ),
        ]
        result_str = collect_tender_documents.invoke(json.dumps({
            "tender_id": TENDER_ID,
            "emails": emails,
            "participants_list": PARTICIPANTS,
        }, ensure_ascii=False))
        result = json.loads(result_str)
        romashka = next(p for p in result["participants"] if p["inn"] == "7702365551")
        assert romashka["status"] == "received"
        assert romashka["anketa_received"] is True
        assert romashka["nda_received"] is True

    def test_pdf_and_docx_accepted(self):
        """Both PDF and DOCX formats are accepted."""
        emails = [
            _make_email(
                "petrov@romashka.ru", "Петров",
                f"ТО {TENDER_ID}",
                [
                    _make_attachment(
                        "Анкета.docx",
                        "Анкета участника\nИНН: 7702365551",
                        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                ],
            ),
        ]
        result_str = collect_tender_documents.invoke(json.dumps({
            "tender_id": TENDER_ID,
            "emails": emails,
            "participants_list": PARTICIPANTS,
        }, ensure_ascii=False))
        result = json.loads(result_str)
        romashka = next(p for p in result["participants"] if p["inn"] == "7702365551")
        assert romashka["anketa_received"] is True

    def test_participant_folder_path_set(self):
        """Each participant has a folder_path assigned."""
        result_str = collect_tender_documents.invoke(json.dumps({
            "tender_id": TENDER_ID,
            "emails": [],
            "participants_list": PARTICIPANTS,
        }, ensure_ascii=False))
        result = json.loads(result_str)
        for p in result["participants"]:
            assert p["folder_path"] != ""
            assert "Документы участника ТО" in p["folder_path"]


# ============================================================================
# Decision Field Tests (v2.1.0)
# ============================================================================

class TestCollectTenderDocumentsDecision:
    def test_collect_tender_documents_returns_decision_field(self):
        """collect_tender_documents returns decision field in result."""
        query = json.dumps({
            "tender_id": "TEST-001",
            "emails": [],
            "participants_list": [
                {"name": "ООО Тест", "inn": "1234567890", "contact_email": "test@test.ru"}
            ]
        })
        result = json.loads(collect_tender_documents.invoke(query))
        assert "decision" in result
        assert result["decision"] == "СБОР НЕ ЗАВЕРШЁН"  # No emails received → not complete

    def test_collect_tender_documents_decision_completed(self):
        """collect_tender_documents returns СБОР ЗАВЕРШЁН when all docs received."""
        query = json.dumps({
            "tender_id": "TEST-002",
            "emails": [
                {
                    "from_email": "test@test.ru",
                    "from_name": "Тест",
                    "subject": "Re: TEST-002 документы",
                    "attachments": [
                        {"filename": "Анкета.pdf", "content_hint": "АНКЕТА УЧАСТНИКА ТО TEST-002 ИНН: 1234567890"},
                        {"filename": "NDA.pdf", "content_hint": "Соглашение о неразглашении"}
                    ]
                }
            ],
            "participants_list": [
                {"name": "ООО Тест", "inn": "1234567890", "contact_email": "test@test.ru"}
            ]
        })
        result = json.loads(collect_tender_documents.invoke(query))
        assert "decision" in result
        assert result["decision"] == "СБОР ЗАВЕРШЁН"


# ============================================================================
# collector_to_2025_0183: 2 участника, 1 NDA отсутствует → СБОР НЕ ЗАВЕРШЁН
# Ref: tests/fixtures/real_procurement_expected.json#collector_to_2025_0183
# ============================================================================

class TestCollectorTO2025_0183:
    """
    Реальный кейс: Страхование имущества ЮЛ — ТО-2025-0183
    2 участника: ООО «СК Гарант» (анкета+NDA), АО «Росгосстрах» (только анкета).
    Ожидаемый результат: СБОР НЕ ЗАВЕРШЁН (NDA от Росгосстрах отсутствует).
    """

    TENDER_ID = "ТО-2025-0183"

    PARTICIPANTS = [
        {
            "name": 'ООО "СК Гарант"',
            "inn": "7710100956",
            "contact_email": "tender@skg.ru",
        },
        {
            "name": 'АО "Росгосстрах"',
            "inn": "7706169564",
            "contact_email": "tender@rgs.ru",
        },
    ]

    EMAILS_BOTH_COMPLETE = [
        {
            "from_email": "tender@skg.ru",
            "from_name": 'ООО "СК Гарант"',
            "subject": f"Re: {TENDER_ID} — анкета и NDA",
            "body": "Направляем анкету и NDA на ТО-2025-0183.",
            "attachments": [
                {
                    "filename": "СК Гарант - Анкета ТО-2025-0183.pdf",
                    "content_hint": f"АНКЕТА УЧАСТНИКА ТО {TENDER_ID} ИНН: 7710100956",
                },
                {
                    "filename": "СК Гарант - NDA ТО-2025-0183.pdf",
                    "content_hint": "Соглашение о неразглашении конфиденциальной информации",
                },
            ],
        },
        {
            "from_email": "tender@rgs.ru",
            "from_name": 'АО "Росгосстрах"',
            "subject": f"Re: {TENDER_ID} — анкета участника",
            "body": "Направляем анкету участника.",
            "attachments": [
                {
                    "filename": "Росгосстрах - Анкета ТО-2025-0183.pdf",
                    "content_hint": f"АНКЕТА УЧАСТНИКА ТО {TENDER_ID} ИНН: 7706169564",
                },
                # NDA отсутствует намеренно
            ],
        },
    ]

    EMAILS_MISSING_ALL = [
        {
            "from_email": "tender@rgs.ru",
            "from_name": 'АО "Росгосстрах"',
            "subject": f"Re: {TENDER_ID} — анкета участника",
            "body": "Направляем анкету участника.",
            "attachments": [
                {
                    "filename": "Росгосстрах - Анкета ТО-2025-0183.pdf",
                    "content_hint": f"АНКЕТА УЧАСТНИКА ТО {TENDER_ID} ИНН: 7706169564",
                },
            ],
        },
    ]

    def _invoke(self, emails: list) -> dict:
        payload = json.dumps({
            "tender_id": self.TENDER_ID,
            "emails": emails,
            "participants_list": self.PARTICIPANTS,
        })
        return json.loads(collect_tender_documents.invoke(payload))

    def test_missing_nda_returns_not_complete(self):
        """NDA от одного участника отсутствует → СБОР НЕ ЗАВЕРШЁН."""
        result = self._invoke(self.EMAILS_BOTH_COMPLETE)
        assert "decision" in result
        assert result["decision"] == "СБОР НЕ ЗАВЕРШЁН"

    def test_all_docs_present_returns_complete(self):
        """Когда оба участника прислали все документы → СБОР ЗАВЕРШЁН."""
        full_emails = [
            self.EMAILS_BOTH_COMPLETE[0],
            {
                **self.EMAILS_BOTH_COMPLETE[1],
                "attachments": [
                    *self.EMAILS_BOTH_COMPLETE[1]["attachments"],
                    {
                        "filename": "Росгосстрах - NDA ТО-2025-0183.pdf",
                        "content_hint": "Соглашение о неразглашении конфиденциальной информации",
                    },
                ],
            },
        ]
        result = self._invoke(full_emails)
        assert "decision" in result
        assert result["decision"] == "СБОР ЗАВЕРШЁН"

    def test_only_one_participant_sent_docs(self):
        """Только один участник прислал документы → СБОР НЕ ЗАВЕРШЁН."""
        result = self._invoke(self.EMAILS_MISSING_ALL)
        assert result["decision"] == "СБОР НЕ ЗАВЕРШЁН"

    def test_participant_count(self):
        """В результате 2 участника."""
        result = self._invoke(self.EMAILS_BOTH_COMPLETE)
        participants_result = result.get("participants", [])
        assert len(participants_result) == 2

    def test_rossgosstrakh_matched_by_email(self):
        """АО Росгосстрах сопоставлен по email."""
        result = self._invoke(self.EMAILS_BOTH_COMPLETE)
        rgs = next(
            (p for p in result.get("participants", []) if "7706169564" in str(p)),
            None,
        )
        assert rgs is not None, "АО Росгосстрах (ИНН 7706169564) не найден в результатах"

    def test_sk_garant_has_both_docs(self):
        """ООО СК Гарант подал анкету и NDA."""
        result = self._invoke(self.EMAILS_BOTH_COMPLETE)
        garant = next(
            (p for p in result.get("participants", []) if "7710100956" in str(p)),
            None,
        )
        assert garant is not None, "ООО СК Гарант (ИНН 7710100956) не найден"
        docs = garant.get("documents", [])
        doc_types = {d.get("doc_type") for d in docs}
        assert "anketa" in doc_types or any("анкет" in str(d).lower() for d in docs), \
            f"Анкета не найдена у СК Гарант, документы: {docs}"

    def test_completeness_below_100_when_nda_missing(self):
        """completeness_pct < 100 когда NDA отсутствует."""
        result = self._invoke(self.EMAILS_BOTH_COMPLETE)
        pct = result.get("completeness_pct", 100)
        assert pct < 100, f"completeness_pct должен быть < 100, получено: {pct}"

    def test_fixture_matches_expected_json(self):
        """Решение соответствует real_procurement_expected.json."""
        import os, json as _json
        fixture_path = os.path.join(
            os.path.dirname(__file__),
            "fixtures", "real_procurement_expected.json",
        )
        with open(fixture_path) as f:
            gt = _json.load(f)
        expected = gt["collector_to_2025_0183"]["expert_decision"]
        result = self._invoke(self.EMAILS_BOTH_COMPLETE)
        assert result["decision"] == expected, (
            f"GT ожидает '{expected}', агент вернул '{result['decision']}'"
        )


# ============================================================================
# collector_to_2025_0183: 2 участника, 1 NDA отсутствует → СБОР НЕ ЗАВЕРШЁН
# Ref: tests/fixtures/real_procurement_expected.json#collector_to_2025_0183
# ============================================================================

class TestCollectorTO2025_0183:
    """
    Реальный кейс: Страхование имущества ЮЛ — ТО-2025-0183
    2 участника: ООО «СК Гарант» (анкета+NDA), АО «Росгосстрах» (только анкета).
    Ожидаемый результат: СБОР НЕ ЗАВЕРШЁН (NDA от Росгосстрах отсутствует).
    """

    TENDER_ID = "ТО-2025-0183"

    PARTICIPANTS = [
        {"name": 'ООО "СК Гарант"', "inn": "7710100956", "contact_email": "tender@skg.ru"},
        {"name": 'АО "Росгосстрах"', "inn": "7706169564", "contact_email": "tender@rgs.ru"},
    ]

    EMAILS_PARTIAL = [
        {
            "from_email": "tender@skg.ru",
            "from_name": 'ООО "СК Гарант"',
            "subject": "Re: ТО-2025-0183 — анкета и NDA",
            "body": "Направляем анкету и NDA.",
            "attachments": [
                {"filename": "СК Гарант - Анкета ТО-2025-0183.pdf",
                 "content_hint": "АНКЕТА УЧАСТНИКА ТО ТО-2025-0183 ИНН: 7710100956"},
                {"filename": "СК Гарант - NDA ТО-2025-0183.pdf",
                 "content_hint": "Соглашение о неразглашении конфиденциальной информации"},
            ],
        },
        {
            "from_email": "tender@rgs.ru",
            "from_name": 'АО "Росгосстрах"',
            "subject": "Re: ТО-2025-0183 — анкета участника",
            "body": "Направляем анкету участника.",
            "attachments": [
                {"filename": "Росгосстрах - Анкета ТО-2025-0183.pdf",
                 "content_hint": "АНКЕТА УЧАСТНИКА ТО ТО-2025-0183 ИНН: 7706169564"},
                # NDA намеренно отсутствует
            ],
        },
    ]

    EMAILS_FULL = [
        EMAILS_PARTIAL[0],
        {
            **EMAILS_PARTIAL[1],
            "attachments": [
                *EMAILS_PARTIAL[1]["attachments"],
                {"filename": "Росгосстрах - NDA ТО-2025-0183.pdf",
                 "content_hint": "Соглашение о неразглашении конфиденциальной информации"},
            ],
        },
    ]

    def _invoke(self, emails):
        import json as _json
        payload = _json.dumps({
            "tender_id": self.TENDER_ID,
            "emails": emails,
            "participants_list": self.PARTICIPANTS,
        })
        return _json.loads(collect_tender_documents.invoke(payload))

    def test_missing_nda_returns_not_complete(self):
        """NDA от одного участника отсутствует → СБОР НЕ ЗАВЕРШЁН."""
        result = self._invoke(self.EMAILS_PARTIAL)
        assert "decision" in result
        assert result["decision"] == "СБОР НЕ ЗАВЕРШЁН"

    def test_all_docs_present_returns_complete(self):
        """Оба участника прислали все документы → СБОР ЗАВЕРШЁН."""
        result = self._invoke(self.EMAILS_FULL)
        assert result["decision"] == "СБОР ЗАВЕРШЁН"

    def test_participant_count(self):
        """В результате 2 участника."""
        result = self._invoke(self.EMAILS_PARTIAL)
        assert len(result.get("participants", [])) == 2

    def test_rgs_matched_by_email(self):
        """АО Росгосстрах сопоставлен по email."""
        result = self._invoke(self.EMAILS_PARTIAL)
        rgs = next((p for p in result.get("participants", []) if "7706169564" in str(p)), None)
        assert rgs is not None, "АО Росгосстрах (ИНН 7706169564) не найден в результатах"

    def test_completeness_below_100_when_nda_missing(self):
        """completeness_pct < 100 когда NDA отсутствует."""
        result = self._invoke(self.EMAILS_PARTIAL)
        assert result.get("completeness_pct", 100) < 100

    def test_fixture_matches_expected_json(self):
        """Решение совпадает с real_procurement_expected.json."""
        import os, json as _json
        path = os.path.join(os.path.dirname(__file__), "fixtures", "real_procurement_expected.json")
        with open(path) as f:
            gt = _json.load(f)
        expected = gt["collector_to_2025_0183"]["expert_decision"]
        result = self._invoke(self.EMAILS_PARTIAL)
        assert result["decision"] == expected, (
            f"GT ожидает {expected!r}, агент вернул {result['decision']!r}"
        )
