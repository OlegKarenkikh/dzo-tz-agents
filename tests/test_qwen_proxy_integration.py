"""
Интеграционные тесты LLM через собственный Qwen прокси.

Сервис: https://qwen-proxy-bdt6.onrender.com
Модель по умолчанию: qwen3-32b

Запуск (unit, без API):
  pytest tests/test_qwen_proxy_integration.py -v

Запуск (интеграционные — реальные вызовы):
  OPENAI_API_KEY=<your_key> OPENAI_API_BASE=https://qwen-proxy-bdt6.onrender.com \
  LLM_BACKEND=qwen_proxy MODEL_NAME=qwen3-32b \
  pytest tests/test_qwen_proxy_integration.py -v -m integration
"""
import importlib
import json
import os
from unittest.mock import MagicMock, patch

import httpx
import pytest

QWEN_PROXY_BASE = "https://qwen-proxy-bdt6.onrender.com"
QWEN_DEFAULT_MODEL = "qwen3-32b"
QWEN_MODEL = os.environ.get("QWEN_PROXY_MODEL", QWEN_DEFAULT_MODEL)

# Источники правды (ground truth) для DZO/ТЗ кейсов
GROUND_TRUTH = {
    "tz_brand_violation": {
        "input": (
            "Техническое задание: Поставка ноутбуков Apple MacBook Pro 16 дюймов. "
            "Количество: 50 штук. НМЦ: 150 000 руб./шт."
        ),
        "expected_keywords": ["apple", "бренд", "торговый", "нарушение", "конкуренци", "44-фз", "эквивалент"],
        "violation_present": True,
        "rule": "44-ФЗ ст.33 ч.3 — запрет указания товарных знаков без «или эквивалент»",
    },
    "tz_clean": {
        "input": (
            "Техническое задание: Поставка ноутбуков с процессором Intel Core i7 или эквивалент, "
            "ОЗУ не менее 16 ГБ, SSD не менее 512 ГБ. Количество: 50 штук. НМЦ: 90 000 руб./шт."
        ),
        "violation_keywords": ["нарушен", "незаконн", "недопустим"],
        "ok_keywords": ["нарушений нет", "не обнаружено", "соответствует", "корректн", "допустим", "нет нарушений"],
        "violation_present": False,
    },
    "dzo_sole_supplier": {
        "input": (
            "ДЗО проводит закупку ИТ-аутсорсинга у единственного поставщика на сумму 12 млн руб. "
            "без обоснования и согласования с материнской компанией."
        ),
        "expected_keywords": ["единственный", "обоснование", "нарушение", "223", "конкурент"],
        "violation_present": True,
        "rule": "223-ФЗ — ЕП свыше порога требует обоснования",
    },
    "purchase_number_extract": {
        "input": "Закупка №0173100001424000123 от 15.03.2024 на сумму 5 500 000 руб.",
        "expected": {"purchase_number": "0173100001424000123", "amount_rub": 5500000},
    },
}


@pytest.fixture
def qwen_cfg(request):
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key or api_key.startswith("sk-test"):
        pytest.skip("OPENAI_API_KEY not set — skipping integration test (pass a real key via env)")
    raw_base = os.environ.get("OPENAI_API_BASE", QWEN_PROXY_BASE)
    # Нормализуем: убираем /v1 — _chat добавит сам
    base = raw_base.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return {
        "api_key": api_key,
        "base_url": base,
        "model": os.environ.get("MODEL_NAME", QWEN_DEFAULT_MODEL),
    }


def _chat(cfg: dict, messages: list, tools: list = None, max_tokens: int = 600) -> dict:
    payload = {"model": cfg["model"], "messages": messages, "max_tokens": max_tokens, "stream": False}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    r = httpx.post(
        f"{cfg['base_url']}/v1/chat/completions",
        headers={"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _text(result: dict) -> str:
    """Извлекает текст ответа (content или reasoning) — Qwen3 может использовать оба."""
    msg = result["choices"][0]["message"]
    return (msg.get("content") or msg.get("reasoning") or "").lower()


# ── Unit тесты ────────────────────────────────────────────────────────────────
class TestQwenProxyConfig:
    def _build(self, monkeypatch, env: dict) -> dict:
        for k, v in env.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        with patch("dotenv.load_dotenv"):
            import config
            import shared.llm as llm_mod
            importlib.reload(config)
            importlib.reload(llm_mod)
            captured = {}
            def fake(**kwargs):
                captured.update(kwargs)
                return MagicMock()
            with patch.object(llm_mod, "ChatOpenAI", side_effect=fake):
                llm_mod.build_llm()
        return captured

    def test_qwen_proxy_valid_backend(self, monkeypatch):
        kwargs = self._build(monkeypatch, {
            "LLM_BACKEND": "qwen_proxy",
            "OPENAI_API_KEY": "test-api-key",
            "OPENAI_API_BASE": None,
        })
        assert kwargs.get("base_url") == "https://qwen-proxy-bdt6.onrender.com/v1"
        assert kwargs.get("api_key") == "test-api-key"

    def test_qwen_proxy_custom_base_url(self, monkeypatch):
        kwargs = self._build(monkeypatch, {
            "LLM_BACKEND": "qwen_proxy",
            "OPENAI_API_KEY": "test-api-key",
            "OPENAI_API_BASE": "https://custom.local/v1",
        })
        assert kwargs.get("base_url") == "https://custom.local/v1"

    def test_qwen_proxy_no_key_raises(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "qwen_proxy")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with patch("dotenv.load_dotenv"):
            import config
            import shared.llm as llm_mod
            importlib.reload(config)
            importlib.reload(llm_mod)
            with pytest.raises(ValueError, match="qwen_proxy"):
                llm_mod.build_llm()

    def test_qwen_proxy_zero_retries(self, monkeypatch):
        kwargs = self._build(monkeypatch, {
            "LLM_BACKEND": "qwen_proxy",
            "OPENAI_API_KEY": "test-api-key",
            "OPENAI_API_BASE": None,
        })
        assert kwargs.get("max_retries") == 0

    def test_qwen_coder_model(self, monkeypatch):
        kwargs = self._build(monkeypatch, {
            "LLM_BACKEND": "qwen_proxy",
            "OPENAI_API_KEY": "test-api-key",
            "OPENAI_API_BASE": None,
            "MODEL_NAME": "qwen3-32b",
        })
        assert kwargs.get("model") == "qwen3-32b"

    def test_other_backends_unaffected(self, monkeypatch):
        for backend, key in [("openai", "sk-regular"), ("deepseek", "ds-key")]:
            kwargs = self._build(monkeypatch, {
                "LLM_BACKEND": backend,
                "OPENAI_API_KEY": key,
                "OPENAI_API_BASE": None,
            })
            assert kwargs.get("api_key") == key


# ── Интеграционные тесты ──────────────────────────────────────────────────────
@pytest.mark.integration
class TestQwenProxyConnectivity:
    def test_models_endpoint(self, qwen_cfg):
        r = httpx.get(
            f"{qwen_cfg['base_url']}/v1/models",
            headers={"Authorization": f"Bearer {qwen_cfg['api_key']}"},
            timeout=15,
        )
        assert r.status_code == 200
        models = [m["id"] for m in r.json().get("data", [])]
        assert "qwen3-32b" in models

    def test_basic_chat_russian(self, qwen_cfg):
        result = _chat(qwen_cfg, [{"role": "user", "content": "Ответь: тест прошёл"}], max_tokens=80)
        text = _text(result)
        assert text  # непустой ответ

    def test_usage_tracking(self, qwen_cfg):
        result = _chat(qwen_cfg, [{"role": "user", "content": "1+1"}], max_tokens=10)
        assert result["usage"]["prompt_tokens"] > 0

    def test_qwen_coder_responds(self, qwen_cfg):
        result = _chat({**qwen_cfg, "model": QWEN_MODEL},
                       [{"role": "user", "content": "print('hello')"}], max_tokens=50)
        assert "choices" in result


@pytest.mark.integration
class TestQwenProxyTZInspection:
    def test_detects_brand_violation(self, qwen_cfg):
        gt = GROUND_TRUTH["tz_brand_violation"]
        result = _chat(qwen_cfg, [
            {"role": "system", "content": "Ты эксперт по 44-ФЗ. Укажи нарушения в ТЗ."},
            {"role": "user", "content": gt["input"]},
        ], max_tokens=800)
        text = _text(result)
        found = any(kw in text for kw in gt["expected_keywords"])
        assert found, f"Нарушение '{gt['rule']}' не обнаружено:\n{text[:400]}"

    def test_clean_tz_no_false_positive(self, qwen_cfg):
        gt = GROUND_TRUTH["tz_clean"]
        result = _chat(qwen_cfg, [
            {"role": "system", "content": "Найди нарушения по 44-ФЗ. Если нет — напиши 'нарушений нет'."},
            {"role": "user", "content": gt["input"]},
        ], max_tokens=600)
        text = _text(result)
        has_fp = any(k in text for k in gt["violation_keywords"])
        has_ok = any(k in text for k in gt["ok_keywords"])
        # Либо нет нарушений, либо явно написано OK
        assert not has_fp or has_ok, f"Ложный позитив:\n{text[:400]}"

    def test_dzo_sole_supplier(self, qwen_cfg):
        gt = GROUND_TRUTH["dzo_sole_supplier"]
        result = _chat(qwen_cfg, [
            {"role": "system", "content": "Ты аудитор закупок ДЗО. Найди нарушения по 223-ФЗ."},
            {"role": "user", "content": gt["input"]},
        ], max_tokens=800)
        text = _text(result)
        found = any(kw in text for kw in gt["expected_keywords"])
        assert found, f"Нарушение '{gt['rule']}' не обнаружено:\n{text[:400]}"


@pytest.mark.integration
class TestQwenProxyToolCalling:
    def test_purchase_check_tool_call(self, qwen_cfg):
        """Модель вызывает tool при запросе по номеру закупки."""
        result = _chat(qwen_cfg, [
            {"role": "user", "content": "Проверь статус закупки №0173100001424000123"}
        ], tools=[{
            "type": "function",
            "function": {
                "name": "check_purchase_status",
                "description": "Проверяет статус закупки по номеру",
                "parameters": {
                    "type": "object",
                    "properties": {"purchase_number": {"type": "string"}},
                    "required": ["purchase_number"],
                },
            },
        }], max_tokens=200)
        choice = result["choices"][0]
        if choice["finish_reason"] == "tool_calls":
            args = json.loads(choice["message"]["tool_calls"][0]["function"]["arguments"])
            assert "0173100001424000123" in str(args.get("purchase_number", ""))
        else:
            # Qwen3 может инлайнить XML tool call в content/reasoning
            raw = (choice["message"].get("content") or choice["message"].get("reasoning") or "")
            assert "0173100001424000123" in raw, f"Номер не найден: {raw[:300]}"

    def test_extract_purchase_data(self, qwen_cfg):
        gt = GROUND_TRUTH["purchase_number_extract"]
        result = _chat(qwen_cfg, [{"role": "user", "content": gt["input"]}], tools=[{
            "type": "function",
            "function": {
                "name": "save_purchase",
                "description": "Сохраняет данные закупки",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "purchase_number": {"type": "string"},
                        "amount_rub": {"type": "number"},
                    },
                    "required": ["purchase_number", "amount_rub"],
                },
            },
        }], max_tokens=300)
        choice = result["choices"][0]
        if choice["finish_reason"] == "tool_calls":
            args = json.loads(choice["message"]["tool_calls"][0]["function"]["arguments"])
            assert gt["expected"]["purchase_number"] in str(args.get("purchase_number", ""))
        else:
            raw = choice["message"].get("content") or choice["message"].get("reasoning") or ""
            assert gt["expected"]["purchase_number"] in raw

    def test_multi_turn_tool_flow(self, qwen_cfg):
        """Мультитёрн: tool call → результат → финальный ответ."""
        tools = [{
            "type": "function",
            "function": {
                "name": "check_tz_compliance",
                "description": "Проверяет ТЗ на соответствие 44-ФЗ",
                "parameters": {
                    "type": "object",
                    "properties": {"tz_text": {"type": "string"}},
                    "required": ["tz_text"],
                },
            },
        }]
        tz = GROUND_TRUTH["tz_brand_violation"]["input"]
        messages = [{"role": "user", "content": f"Проверь ТЗ на 44-ФЗ:\n{tz}"}]
        r1 = _chat(qwen_cfg, messages, tools=tools, max_tokens=200)
        choice = r1["choices"][0]
        if choice["finish_reason"] == "tool_calls":
            tc = choice["message"]["tool_calls"][0]
            messages += [choice["message"], {
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": json.dumps({"violations": ["бренд Apple без эквивалента"]}),
            }]
            r2 = _chat(qwen_cfg, messages, max_tokens=400)
            text = _text(r2)
            assert any(k in text for k in ["apple", "нарушение", "торговый", "эквивалент"])
        else:
            text = _text(r1)
            assert any(k in text for k in ["apple", "нарушение", "бренд"])


@pytest.mark.integration
class TestQwenProxyLangChain:
    def test_langchain_chat(self, qwen_cfg):
        import sys

        # Remove the conftest stub so the real langchain_openai package is imported.
        sys.modules.pop("langchain_openai", None)
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage, SystemMessage
        except ImportError:
            pytest.skip("langchain-openai package not installed")
        llm = ChatOpenAI(
            model=qwen_cfg["model"],
            api_key=qwen_cfg["api_key"],
            base_url=f"{qwen_cfg['base_url']}/v1",
            max_tokens=100,
            temperature=0,
        )
        response = llm.invoke([
            SystemMessage(content="Ты помощник по госзакупкам."),
            HumanMessage(content="Что такое НМЦ контракта? Одно предложение."),
        ])
        assert response.content or hasattr(response, 'additional_kwargs')
