"""Поблочный (map-reduce) анализ больших документов.

Алгоритм:
  Phase 1 (Map)   — документ разбивается на чанки по ~5 000 символов.
                    Каждый чанк анализируется отдельным прямым LLM-вызовом
                    (без агента/инструментов → минимальный overhead токенов).
  Phase 2 (Reduce)— краткие результаты чанков склеиваются в единое резюме.
                    Это резюме передаётся агенту вместо исходного документа.

Применяется когда документ слишком большой для контекстного окна модели.
"""
import logging
import math

import httpx

from config import LLM_BACKEND, OPENAI_API_BASE
from shared.llm import (
    _GITHUB_MODELS_BASE_URL,
    LOCAL_BACKENDS,
    estimate_tokens,
    probe_local_max_context,
    probe_max_input_tokens,
    resolve_local_base_url,
)

logger = logging.getLogger("chunked_analysis")

# ── Параметры чанкинга ───────────────────────────────────────────────────────

# Максимальный размер одного чанка в символах.
# ~5 000 симв. ≈ 1 250 токенов.  При overhead системного промпта ~200 токенов
# и ответе 250 токенов итого ~1 700 токенов << 8 000 — безопасно.
_CHUNK_MAX_CHARS = 5_000

# Перекрытие между соседними чанками — чтобы не потерять контекст на границах.
_CHUNK_OVERLAP_CHARS = 300

# Максимальное число чанков. Сверх этого объединяем соседние чанки.
# 14 чанков × 250 токенов ответа = 3 500 + ~400 header/footer + 3 000 overhead
# = 6 900 токенов < 8 000 — безопасный бюджет для любой Github-free модели.
_MAX_CHUNKS = 14

# Лимит токенов на один ответ анализа чанка.
# 18 чанков × 250 = 4 500 токенов резюме (+3 000 overhead агента = 7 500 < 8 000).
_CHUNK_RESPONSE_TOKENS = 250
_MIN_CHUNK_INPUT_TOKENS = 900
_CHUNK_SAFETY_MARGIN_TOKENS = 256
_SYSTEM_PROMPT_OVERHEAD_TOKENS = 120
_DEFAULT_MODEL_CONTEXT_TOKENS = 8_192

# ── Системные промпты для каждого типа агента ────────────────────────────────

_TZ_SYSTEM = """\
Ты анализируешь ФРАГМЕНТ технического задания (ТЗ) на закупку.
Стандартная структура ТЗ содержит 8 разделов:
  1. Цель закупки
  2. Требования к товару/работе/услуге
  3. Количество и единицы измерения
  4. Срок и условия поставки
  5. Место поставки
  6. Требования к исполнителю
  7. Критерии оценки заявок
  8. Приложения

Для каждого раздела, который ПРИСУТСТВУЕТ в данном фрагменте, выдай:
  • Номер и название раздела
  • Ключевое содержание (1-2 предложения)
  • Проблемы: расплывчатые требования, отсутствие цифр, субъективные формулировки

Не выдумывай то, чего нет в тексте. Отвечай ТОЛЬКО по присутствующим разделам.\
"""

_TZ_USER = """\
Фрагмент {num}/{total} ТЗ:

{chunk}\
"""

_DZO_SYSTEM = """\
Ты анализируешь ФРАГМЕНТ заявки ДЗО на закупку, поступившей по email.
Извлеки из данного фрагмента (только то, что явно присутствует):
  • Предмет закупки
  • Количество и единицы измерения
  • Желаемый срок поставки
  • Инициатор — ФИО и контакты
  • Место поставки
  • Бюджет (если указан)
  • Обоснование закупки
  • Упомянутые вложения/файлы
  • Любые несоответствия или проблемы

Не выдумывай то, чего нет в тексте. Отвечай кратко.\
"""

_DZO_USER = """\
Фрагмент {num}/{total} заявки ДЗО:

{chunk}\
"""

_TENDER_SYSTEM = """\
Ты анализируешь ФРАГМЕНТ тендерной документации на закупку.
Извлеки из данного фрагмента (только то, что явно присутствует):

ПРЯМЫЕ ТРЕБОВАНИЯ к документам участника:
  • Перечни документов в составе заявки (с указанием раздела/пункта)
  • Требования к оформлению и содержанию каждого документа

КОСВЕННЫЕ ТРЕБОВАНИЯ (вытекающие из условий):
  • Квалификационные требования → какие документы подтверждают квалификацию
  • Лицензионные требования → копии лицензий, допусков, свидетельств
  • Требования СРО → свидетельства о членстве в саморегулируемых организациях
  • Финансовые требования → банковские гарантии, выписки, балансы
  • Технические требования → сертификаты, разрешения, технические регламенты
  • Опыт и репутация → договоры, акты выполненных работ, рекомендации

Для каждого найденного документа укажи:
  - Название документа
  - Тип (лицензия / свидетельство / копия / оригинал / форма / декларация / гарантия / выписка / справка / сертификат / договор / протокол / приказ / устав / иное)
  - Обязательность (обязательный / условный)
  - Раздел/пункт документации
  - Требования к содержанию
  - Основание требования (прямое / из квалификации / из предмета закупки)

Не выдумывай то, чего нет в тексте. Если фрагмент не содержит требований к документам, скажи об этом кратко.\
"""

_TENDER_USER = """\
Фрагмент {num}/{total} тендерной документации:

{chunk}\
"""


# ── Функции ──────────────────────────────────────────────────────────────────

def chunk_document(
    text: str,
    max_chars: int = _CHUNK_MAX_CHARS,
    overlap: int = _CHUNK_OVERLAP_CHARS,
    max_chunks: int = _MAX_CHUNKS,
) -> list[str]:
    """Разбить текст на перекрывающиеся чанки, разбивая по абзацам.

    Если чанков получается больше ``max_chunks``, автоматически увеличивает
    размер чанка пропорционально.
    """
    if len(text) <= max_chars:
        return [text]

    # Подбираем размер чанка так чтобы чанков было не больше max_chunks
    effective_max = max(max_chars, len(text) // max_chunks + 1)

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + effective_max
        if end >= len(text):
            chunks.append(text[start:])
            break

        # Предпочитаем разбивать по двойному переносу строки (между абзацами)
        break_pos = text.rfind("\n\n", start + effective_max // 2, end)
        if break_pos == -1:
            # Одинарный перенос
            break_pos = text.rfind("\n", start + effective_max // 2, end)
        if break_pos == -1:
            # Крайний случай — разбиваем по ближайшему пробелу
            break_pos = text.rfind(" ", end - 200, end)
        if break_pos <= start:
            break_pos = end

        chunks.append(text[start:break_pos])
        start = max(start + 1, break_pos - overlap)

    return chunks


def _resolve_model_context_tokens(api_key: str, model_name: str) -> int:
    """Определяет контекстное окно модели для текущего backend."""
    try:
        if LLM_BACKEND == "github_models":
            return probe_max_input_tokens(api_key, model_name)
        if LLM_BACKEND in LOCAL_BACKENDS:
            return probe_local_max_context(resolve_local_base_url(), model_name)
    except Exception as exc:
        logger.warning(
            "⚠️ Не удалось определить context window для %s: %s. Используется %d.",
            model_name,
            exc,
            _DEFAULT_MODEL_CONTEXT_TOKENS,
        )
    return _DEFAULT_MODEL_CONTEXT_TOKENS


def _plan_chunking(text: str, api_key: str, model_name: str, system_prompt: str) -> tuple[int, int, int, int]:
    """Возвращает параметры чанкинга: (max_chars, overlap_chars, max_chunks, model_ctx_tokens)."""
    model_ctx = max(2_048, _resolve_model_context_tokens(api_key, model_name))
    system_tokens = estimate_tokens(system_prompt) + _SYSTEM_PROMPT_OVERHEAD_TOKENS
    available_input_tokens = max(
        _MIN_CHUNK_INPUT_TOKENS,
        model_ctx - system_tokens - _CHUNK_RESPONSE_TOKENS - _CHUNK_SAFETY_MARGIN_TOKENS,
    )

    # Держим запас на фактическое расхождение tokenizers разных провайдеров.
    target_chunk_tokens = max(_MIN_CHUNK_INPUT_TOKENS, int(available_input_tokens * 0.8))
    max_chars = target_chunk_tokens * 4

    overlap_chars = max(200, min(2_000, int(max_chars * 0.08)))

    doc_tokens = estimate_tokens(text)
    approx_needed_chunks = max(1, math.ceil(doc_tokens / max(1, target_chunk_tokens)))
    # Не ограничиваем чанки слишком агрессивно, чтобы не увеличивать их сверх budget.
    max_chunks = max(_MAX_CHUNKS, approx_needed_chunks + 2)

    return max_chars, overlap_chars, max_chunks, model_ctx


def _resolve_completions_url() -> str:
    """Return the chat/completions URL for the current backend."""
    if LLM_BACKEND == "github_models":
        return f"{_GITHUB_MODELS_BASE_URL}/chat/completions"
    if LLM_BACKEND in LOCAL_BACKENDS:
        base = resolve_local_base_url().rstrip("/")
        return f"{base}/chat/completions"
    if OPENAI_API_BASE:
        base = OPENAI_API_BASE.rstrip("/")
        return f"{base}/chat/completions"
    return "https://api.openai.com/v1/chat/completions"


def _call_llm_direct(
    api_key: str,
    model_name: str,
    system: str,
    user: str,
    max_tokens: int = _CHUNK_RESPONSE_TOKENS,
) -> str:
    """Прямой HTTP-вызов LLM API (без LangChain) для анализа чанка.

    Работает с любым бэкендом: GitHub Models, OpenAI, Ollama, vLLM, LM Studio, DeepSeek.
    """
    url = _resolve_completions_url()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key and api_key != "not-needed":
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = httpx.post(
            url,
            headers=headers,
            json={
                "model": model_name,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.1,
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.warning("⚠️ Ошибка анализа чанка (model=%s): %s", model_name, exc)
        return ""


def analyze_document_in_chunks(
    text: str,
    api_key: str,
    model_name: str,
    agent_type: str,
) -> str | None:
    """Поблочный (map-reduce) анализ документа.

    Phase 1: каждый чанк анализируется отдельным прямым LLM-вызовом.
    Phase 2: все частичные анализы склеиваются в резюме для агента.

    Args:
        text:       Полный текст документа.
        api_key:    API-ключ (Bearer-токен) для LLM API.
        model_name: Модель для анализа (та же, что в fallback-цепочке).
        agent_type: ``"tz"``, ``"dzo"`` или ``"tender"``.

    Returns:
        Строка-резюме для передачи агенту вместо исходного документа.
        ``None`` если все чанки завершились ошибкой.
    """
    if agent_type == "tz":
        sys_prompt  = _TZ_SYSTEM
        user_tmpl   = _TZ_USER
        result_header = (
            "╔══════════════════════════════════════════════════════════════╗\n"
            "║      ПРЕДВАРИТЕЛЬНЫЙ ПОБЛОЧНЫЙ АНАЛИЗ ТЕХНИЧЕСКОГО ЗАДАНИЯ  ║\n"
            "╚══════════════════════════════════════════════════════════════╝\n"
            f"Исходный документ: {len(text):,} символов → обработан {{chunk_count}} фрагментами.\n\n"
        )
        result_footer = (
            "\n\n══════════════════════════════════════════════════════════════\n"
            "📋 ЗАДАЧА ДЛЯ АГЕНТА:\n"
            "На основе поблочного анализа выше выполни ПОЛНУЮ проверку ТЗ:\n"
            "  1. Вызови generate_json_report — укажи статус всех 8 разделов\n"
            "  2. Вызови generate_corrected_tz — предложи исправленную версию\n"
            "  3. Вызови generate_email_to_dzo — составь письмо в ДЗО\n"
            "Опирайся на результаты анализа фрагментов выше.\n"
            "══════════════════════════════════════════════════════════════"
        )
    elif agent_type == "tender":
        sys_prompt  = _TENDER_SYSTEM
        user_tmpl   = _TENDER_USER
        result_header = (
            "╔══════════════════════════════════════════════════════════════╗\n"
            "║   ПРЕДВАРИТЕЛЬНЫЙ ПОБЛОЧНЫЙ АНАЛИЗ ТЕНДЕРНОЙ ДОКУМЕНТАЦИИ   ║\n"
            "╚══════════════════════════════════════════════════════════════╝\n"
            f"Исходный документ: {len(text):,} символов → обработан {{chunk_count}} фрагментами.\n\n"
        )
        result_footer = (
            "\n\n══════════════════════════════════════════════════════════════\n"
            "📋 ЗАДАЧА ДЛЯ АГЕНТА:\n"
            "На основе поблочного анализа выше составь ПОЛНЫЙ список документов:\n"
            "  1. Вызови generate_document_list — укажи все найденные документы\n"
            "     (прямые требования + косвенные из квалификации и предмета закупки)\n"
            "Опирайся на результаты анализа фрагментов выше.\n"
            "══════════════════════════════════════════════════════════════"
        )
    else:
        sys_prompt  = _DZO_SYSTEM
        user_tmpl   = _DZO_USER
        result_header = (
            "╔══════════════════════════════════════════════════════════════╗\n"
            "║      ПРЕДВАРИТЕЛЬНЫЙ ПОБЛОЧНЫЙ АНАЛИЗ ЗАЯВКИ ДЗО            ║\n"
            "╚══════════════════════════════════════════════════════════════╝\n"
            f"Исходный документ: {len(text):,} символов → обработан {{chunk_count}} фрагментами.\n\n"
        )
        result_footer = (
            "\n\n══════════════════════════════════════════════════════════════\n"
            "📋 ЗАДАЧА ДЛЯ АГЕНТА:\n"
            "На основе поблочного анализа выше проверь заявку по чек-листу:\n"
            "  1. Вызови generate_validation_report — отчёт по чек-листам\n"
            "  2. Вызови generate_tezis_form (если заявка полная)\n"
            "  3. Вызови generate_response_email — итоговое письмо ДЗО\n"
            "Опирайся на результаты анализа фрагментов выше.\n"
            "══════════════════════════════════════════════════════════════"
        )

    chunk_max_chars, chunk_overlap_chars, chunk_max_count, model_ctx_tokens = _plan_chunking(
        text,
        api_key,
        model_name,
        sys_prompt,
    )
    chunks = chunk_document(
        text,
        max_chars=chunk_max_chars,
        overlap=chunk_overlap_chars,
        max_chunks=chunk_max_count,
    )
    n = len(chunks)
    result_header = result_header.format(chunk_count=n)
    logger.info(
        "📦 Поблочный анализ (%s): %d символов (~%d ток.) → %d чанков (model=%s, ctx=%d, chunk=%d симв, overlap=%d)",
        agent_type,
        len(text),
        estimate_tokens(text),
        n,
        model_name,
        model_ctx_tokens,
        chunk_max_chars,
        chunk_overlap_chars,
    )

    analyses: list[str] = []
    for i, chunk in enumerate(chunks):
        user_msg = user_tmpl.format(num=i + 1, total=n, chunk=chunk)
        analysis = _call_llm_direct(api_key, model_name, sys_prompt, user_msg)
        if analysis:
            analyses.append(f"── Фрагмент {i + 1}/{n} ({'начало' if i == 0 else 'конец' if i == n - 1 else 'середина'}) ──\n{analysis}")
            logger.debug(
                "  ✅ Чанк %d/%d: %d симв. → %d симв. анализа",
                i + 1, n, len(chunk), len(analysis),
            )
        else:
            analyses.append(f"── Фрагмент {i + 1}/{n} ── [анализ не удался]")
            logger.warning("  ⚠️ Чанк %d/%d: анализ не удался", i + 1, n)

    if not any(a for a in analyses if "анализ не удался" not in a):
        logger.error("❌ Поблочный анализ: все чанки завершились ошибкой")
        return None

    summary = result_header + "\n\n".join(analyses) + result_footer
    logger.info(
        "✅ Поблочный анализ завершён: %d фрагм. → резюме %d символов (~%d токенов)",
        n, len(summary), len(summary) // 4,
    )
    return summary
