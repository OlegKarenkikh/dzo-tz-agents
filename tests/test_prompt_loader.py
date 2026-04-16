"""Tests for prompt loader."""
import pytest

from shared.prompt_loader import load_prompt, list_prompts


class TestPromptLoader:
    def test_load_dzo_prompt(self):
        prompt = load_prompt("dzo_v1.md")
        assert len(prompt) > 100
        assert "ДЗО" in prompt or "заявк" in prompt.lower()

    def test_load_tz_prompt(self):
        prompt = load_prompt("tz_v1.md")
        assert len(prompt) > 100
        assert "ТЗ" in prompt or "техническ" in prompt.lower()

    def test_load_tender_prompt(self):
        prompt = load_prompt("tender_v1.md")
        assert len(prompt) > 100

    def test_load_collector_prompt(self):
        prompt = load_prompt("collector_v1.md")
        assert len(prompt) > 100

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            load_prompt("nonexistent_v99.md")

    def test_list_prompts_returns_all(self):
        prompts = list_prompts()
        names = [p["name"] for p in prompts]
        assert "dzo_v1.md" in names
        assert "tz_v1.md" in names
        assert "tender_v1.md" in names
        assert "collector_v1.md" in names

    def test_prompt_cached(self):
        """Second load should use cache (same object)."""
        load_prompt.cache_clear()
        p1 = load_prompt("dzo_v1.md")
        p2 = load_prompt("dzo_v1.md")
        assert p1 is p2  # lru_cache returns same object
