"""Coverage tests for shared/agent_tooling.py — uncovered branches (60% → 85%+)."""
import pytest
from unittest.mock import MagicMock, patch
import shared.agent_tooling as at
import config


class TestGetRegistry:
    def test_returns_dict(self):
        assert isinstance(at._get_registry(), dict)

    def test_registry_keys_are_strings(self):
        for k, v in at._get_registry().items():
            assert isinstance(k, str) and isinstance(v, str)

    def test_custom_registry_merged(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_TOOL_REGISTRY",
                            {"custom_agent": "some.module:factory"})
        assert "custom_agent" in at._get_registry()

    def test_non_string_entries_skipped(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_TOOL_REGISTRY",
                            {123: "path", "valid_key": "mod:fn", None: "bad"})
        reg = at._get_registry()
        assert "valid_key" in reg
        assert 123 not in reg


class TestGetPermissions:
    def test_returns_dict(self):
        assert isinstance(at._get_permissions(), dict)

    def test_custom_permissions_merged(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_TOOL_PERMISSIONS",
                            {"agentX": ["agentY"]})
        perms = at._get_permissions()
        assert "agentX" in perms and "agentY" in perms["agentX"]

    def test_non_string_source_skipped(self, monkeypatch):
        monkeypatch.setattr(config, "AGENT_TOOL_PERMISSIONS",
                            {123: ["a"], "valid": ["b"]})
        perms = at._get_permissions()
        assert "valid" in perms and 123 not in perms


class TestLoadFactory:
    def test_raises_without_colon(self):
        with pytest.raises(ValueError, match="Некорректный"):
            at._load_factory("no_colon")

    def test_raises_on_missing_attr(self):
        with pytest.raises(AttributeError):
            at._load_factory("shared.logger:nonexistent_xyz")

    def test_returns_callable(self):
        fn = at._load_factory("shared.agent_tooling:_get_registry")
        assert callable(fn)


class TestGetAgentRunner:
    def setup_method(self):
        at._agent_cache.clear()

    def test_raises_on_unknown_agent(self):
        with pytest.raises(KeyError, match="не найден"):
            at._get_agent_runner("unknown_agent_xyz_777")

    def test_caches_runner(self):
        mock_runner = MagicMock()
        mock_factory = MagicMock(return_value=mock_runner)
        with patch.object(at, "_get_registry", return_value={"ag": "m:f"}):
            with patch.object(at, "_load_factory", return_value=mock_factory):
                r1 = at._get_agent_runner("ag")
                r2 = at._get_agent_runner("ag")
                assert r1 is r2
                mock_factory.assert_called_once()

    def test_model_override_separate_cache_key(self):
        calls = []
        def factory(**kw):
            calls.append(kw)
            return MagicMock()
        with patch.object(at, "_get_registry", return_value={"ag2": "m:f"}):
            with patch.object(at, "_load_factory", return_value=factory):
                r1 = at._get_agent_runner("ag2")
                r2 = at._get_agent_runner("ag2", model_name_override="gpt-4o-mini")
                assert r1 is not r2

    def test_factory_without_model_name_compat(self):
        """Factory without model_name param → TypeError caught, retry without."""
        mock_runner = MagicMock()
        def strict_factory(**kw):
            if "model_name" in kw:
                raise TypeError("no model_name param")
            return mock_runner
        with patch.object(at, "_get_registry", return_value={"ag3": "m:f"}):
            with patch.object(at, "_load_factory", return_value=strict_factory):
                runner = at._get_agent_runner("ag3", model_name_override="gpt-4o")
                assert runner is mock_runner


class TestDiscoverAgentFactories:
    def test_returns_dict(self):
        at._discover_agent_factories.cache_clear()
        assert isinstance(at._discover_agent_factories(), dict)

    def test_keys_have_colon(self):
        at._discover_agent_factories.cache_clear()
        for k, v in at._discover_agent_factories().items():
            assert ":" in v


class TestModelCooldown:
    def setup_method(self):
        at._model_cooldown_until.clear()

    def test_not_on_cooldown_initially(self):
        assert not at._is_model_on_cooldown("gpt-4o")

    def test_on_cooldown_after_mark(self):
        at._mark_model_cooldown("gpt-4o-mini", "rate limit please wait 60 seconds")
        assert at._is_model_on_cooldown("gpt-4o-mini")

    def test_expired_cooldown_returns_false(self):
        at._model_cooldown_until["old-model"] = 0.0
        assert not at._is_model_on_cooldown("old-model")
