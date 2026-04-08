from unittest.mock import patch

import shared.chunked_analysis as ca


def test_plan_chunking_scales_with_context_window():
    text = "A" * 120_000
    system = "system prompt"

    with patch.object(ca, "_resolve_model_context_tokens", return_value=8_192):
        small_chars, small_overlap, small_max_chunks, small_ctx = ca._plan_chunking(text, "k", "m", system)

    with patch.object(ca, "_resolve_model_context_tokens", return_value=128_000):
        large_chars, large_overlap, large_max_chunks, large_ctx = ca._plan_chunking(text, "k", "m", system)

    assert small_ctx == 8_192
    assert large_ctx == 128_000
    assert large_chars > small_chars
    assert large_overlap >= small_overlap
    assert small_max_chunks >= ca._MAX_CHUNKS
    assert large_max_chunks >= ca._MAX_CHUNKS


def test_plan_chunking_has_minimum_safe_budget():
    text = "B" * 10_000
    system = "sys"

    with patch.object(ca, "_resolve_model_context_tokens", return_value=2_048):
        max_chars, overlap, max_chunks, model_ctx = ca._plan_chunking(text, "k", "m", system)

    assert model_ctx == 2_048
    # Минимум 900 токенов * 4 символа
    assert max_chars >= 3_600
    assert overlap >= 200
    assert max_chunks >= ca._MAX_CHUNKS
