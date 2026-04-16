"""Tests for _normalize_decision() in api/app.py."""
import json

import pytest

from api.app import _normalize_decision, _KNOWN_DECISIONS, _TECHNICAL_STATUSES


class TestNormalizeDecision:
    """Unit tests for the decision normalizer."""

    def test_already_expert_decision_unchanged(self):
        """If current decision is already expert, return as-is."""
        decision, technical = _normalize_decision("ПРИНЯТЬ", "some output")
        assert decision == "ПРИНЯТЬ"
        assert technical is None

    def test_already_expert_case_insensitive(self):
        """Known decisions are matched case-insensitively."""
        decision, technical = _normalize_decision("Принять", "some output")
        assert decision == "Принять"
        assert technical is None

    def test_technical_status_with_json_decision_in_output(self):
        """Technical status 'documents_found' + output with expert decision → use output."""
        output = '```json\n{"decision": "ДОКУМЕНТАЦИЯ ПОЛНАЯ", "completeness_pct": 95}\n```'
        decision, technical = _normalize_decision("documents_found", output)
        assert decision == "ДОКУМЕНТАЦИЯ ПОЛНАЯ"
        assert technical == "documents_found"

    def test_technical_status_with_raw_json_decision(self):
        """Raw JSON (no fenced block) with "decision" key."""
        output = 'Результат анализа: {"decision": "ПРИНЯТЬ", "score_pct": 92}'
        decision, technical = _normalize_decision("documents_found", output)
        assert decision == "ПРИНЯТЬ"
        assert technical == "documents_found"

    def test_markdown_decision_extraction(self):
        """Markdown format: Оценка: **РЕШЕНИЕ**."""
        output = "## Итог\nОценка: **ВЕРНУТЬ НА ДОРАБОТКУ**\n\nДетали..."
        decision, technical = _normalize_decision("Неизвестно", output)
        assert decision == "ВЕРНУТЬ НА ДОРАБОТКУ"
        assert technical == "Неизвестно"

    def test_collector_status_extraction(self):
        """Collector agent uses "status" key instead of "decision"."""
        output = '{"status": "СБОР НЕ ЗАВЕРШЁН", "total_participants": 3}'
        decision, technical = _normalize_decision("Неизвестно", output)
        assert decision == "СБОР НЕ ЗАВЕРШЁН"
        assert technical == "Неизвестно"

    def test_no_output_returns_current(self):
        """Empty output → keep current decision."""
        decision, technical = _normalize_decision("documents_found", "")
        assert decision == "documents_found"
        assert technical is None

    def test_none_output_returns_current(self):
        """None-ish output → keep current decision."""
        decision, technical = _normalize_decision("tool_error", "")
        assert decision == "tool_error"
        assert technical is None

    def test_output_without_known_decision(self):
        """Output with no recognizable expert decision → keep current."""
        output = '{"decision": "SOMETHING_UNKNOWN", "score": 50}'
        decision, technical = _normalize_decision("documents_found", output)
        assert decision == "documents_found"
        assert technical is None

    def test_json_block_with_expert_decision_key(self):
        """JSON block with 'expert_decision' key."""
        output = '```json\n{"expert_decision": "ПРИНЯТЬ С ЗАМЕЧАНИЕМ", "score_pct": 78}\n```'
        decision, technical = _normalize_decision("tool_calls_missing", output)
        assert decision == "ПРИНЯТЬ С ЗАМЕЧАНИЕМ"
        assert technical == "tool_calls_missing"

    def test_json_block_with_verdict_key(self):
        """JSON block with 'verdict' key."""
        output = '```json\n{"verdict": "ЗАЯВКА ПОЛНАЯ", "details": "ok"}\n```'
        decision, technical = _normalize_decision("Неизвестно", output)
        assert decision == "ЗАЯВКА ПОЛНАЯ"
        assert technical == "Неизвестно"

    def test_token_limit_exhausted_with_output(self):
        """token_limit_exhausted + output with decision → normalizes."""
        output = 'Анализ завершен.\n{"decision": "ТРЕБУЕТСЯ ДОРАБОТКА", "issues": []}'
        decision, technical = _normalize_decision("token_limit_exhausted", output)
        assert decision == "ТРЕБУЕТСЯ ДОРАБОТКА"
        assert technical == "token_limit_exhausted"

    def test_rate_limit_exhausted_no_output(self):
        """rate_limit_exhausted + empty output → stays."""
        decision, technical = _normalize_decision("rate_limit_exhausted", "")
        assert decision == "rate_limit_exhausted"
        assert technical is None

    def test_malformed_json_in_output(self):
        """Malformed JSON block → falls through to next strategy."""
        output = '```json\n{broken json here\n```\n\n"decision": "ПРИНЯТЬ"'
        decision, technical = _normalize_decision("documents_found", output)
        assert decision == "ПРИНЯТЬ"
        assert technical == "documents_found"

    def test_multiple_decisions_first_wins(self):
        """Multiple decision keys → first recognized one wins (JSON block priority)."""
        output = '```json\n{"decision": "ПРИНЯТЬ", "status": "ВЕРНУТЬ НА ДОРАБОТКУ"}\n```'
        decision, technical = _normalize_decision("documents_found", output)
        assert decision == "ПРИНЯТЬ"
        assert technical == "documents_found"

    def test_known_decisions_set_completeness(self):
        """Verify all expected decisions are in the set."""
        expected = {
            "ПРИНЯТЬ", "ПРИНЯТЬ С ЗАМЕЧАНИЕМ", "ВЕРНУТЬ НА ДОРАБОТКУ",
            "ЗАЯВКА ПОЛНАЯ", "ТРЕБУЕТСЯ ДОРАБОТКА", "ТРЕБУЕТСЯ ЭСКАЛАЦИЯ",
            "ДОКУМЕНТАЦИЯ ПОЛНАЯ", "КРИТИЧЕСКИЕ НАРУШЕНИЯ",
            "СБОР ЗАВЕРШЁН", "СБОР НЕ ЗАВЕРШЁН", "ТРЕБУЕТСЯ ПРОВЕРКА",
        }
        assert expected.issubset(_KNOWN_DECISIONS)

    def test_technical_statuses_set(self):
        """Verify technical statuses set."""
        expected = {
            "documents_found", "tool_error", "tool_calls_missing",
            "token_limit_exhausted", "rate_limit_exhausted", "Неизвестно",
        }
        assert expected == _TECHNICAL_STATUSES

    def test_dzo_decision_from_output(self):
        """DZO agent with 'ТРЕБУЕТСЯ ЭСКАЛАЦИЯ' in output."""
        output = '{"decision": "ТРЕБУЕТСЯ ЭСКАЛАЦИЯ", "reason": "превышен бюджет"}'
        decision, technical = _normalize_decision("Неизвестно", output)
        assert decision == "ТРЕБУЕТСЯ ЭСКАЛАЦИЯ"
        assert technical == "Неизвестно"

    def test_collector_sbor_zavershen(self):
        """Collector 'СБОР ЗАВЕРШЁН' in status field."""
        output = json.dumps({
            "status": "СБОР ЗАВЕРШЁН",
            "total_participants": 2,
            "received_anketa": 2,
        }, ensure_ascii=False)
        decision, technical = _normalize_decision("Неизвестно", output)
        assert decision == "СБОР ЗАВЕРШЁН"
        assert technical == "Неизвестно"

    def test_prinyat_s_zamechaniem_markdown(self):
        """Markdown format: ПРИНЯТЬ С ЗАМЕЧАНИЕМ."""
        output = "Оценка: ПРИНЯТЬ С ЗАМЕЧАНИЕМ\nЗамечания: отсутствует место поставки"
        decision, technical = _normalize_decision("tool_calls_missing", output)
        assert decision == "ПРИНЯТЬ С ЗАМЕЧАНИЕМ"
        assert technical == "tool_calls_missing"
