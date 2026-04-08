"""Бегун агента «Парсер тендерной документации».

Обрабатывает пакет тендерных документов:
  - принимает пути к файлам (PDF / DOCX / XLSX) или HTTP(S)-ссылки;
  - для каждого документа вызывает агент, который извлекает перечень требуемых
    от участника закупки документов;
  - сохраняет результат в JSON-файл с тем же именем, но расширением .json.
"""
import hashlib
import json
import os
import pathlib
import threading
import urllib.parse
from datetime import UTC, datetime

from dotenv import load_dotenv

load_dotenv()

import shared.database as db  # noqa: E402
from agent21_tender_inspector.agent import create_tender_agent  # noqa: E402
from api.metrics import EMAILS_ERRORS, EMAILS_PROCESSED, JobTimer, POLL_CYCLES  # noqa: E402
from config import FORCE_REPROCESS, GITHUB_TOKEN, LLM_BACKEND, MODEL_NAME, OPENAI_API_KEY  # noqa: E402
from shared.chunked_analysis import analyze_document_in_chunks  # noqa: E402
from shared.file_extractor import extract_text_from_attachment  # noqa: E402
from shared.llm import build_github_fallback_chain, estimate_tokens, probe_max_input_tokens  # noqa: E402
from shared.logger import setup_logger  # noqa: E402
from shared.telegram_notify import notify  # noqa: E402
from shared.tracing import get_langfuse_callback, log_agent_steps  # noqa: E402

logger = setup_logger("agent_tender")

TENDER_DOCS_DIR = os.getenv("TENDER_DOCS_DIR", "tender_docs")
TENDER_OUTPUT_DIR = os.getenv("TENDER_OUTPUT_DIR", "")
SUPPORTED_EXTS = {".pdf", ".docx", ".xlsx", ".xls"}

_TOOLS_TOKEN_OVERHEAD = 3000

# FIX RC-05: double-checked locking для _fallback_chain_cache
_fallback_chain_cache: dict[tuple[str, str], tuple[list[str], int]] = {}
_fallback_chain_cache_lock = threading.Lock()


def _is_url(path: str) -> bool:
    parsed = urllib.parse.urlparse(path)
    return parsed.scheme in ("http", "https")


def _download_document(url: str) -> tuple[bytes, str]:
    import httpx
    _MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
    logger.info("⬇️ Загрузка документа: %s", url)
    chunks: list[bytes] = []
    total = 0
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as resp:
        resp.raise_for_status()
        for chunk in resp.iter_bytes(chunk_size=65536):
            total += len(chunk)
            if total > _MAX_DOWNLOAD_BYTES:
                raise ValueError(
                    f"Документ превышает максимально допустимый размер "
                    f"({_MAX_DOWNLOAD_BYTES // (1024 * 1024)} МБ): {url}"
                )
            chunks.append(chunk)
        content_disp = resp.headers.get("content-disposition", "")
        content_type = resp.headers.get("content-type", "")
    raw = b"".join(chunks)
    filename = ""
    if "filename=" in content_disp:
        filename = content_disp.split("filename=")[-1].strip().strip('"\'')
    if not filename:
        filename = pathlib.Path(urllib.parse.urlparse(url).path).name or "document"
    filename = pathlib.PurePath(filename).name or "document"
    if not pathlib.Path(filename).suffix:
        if "pdf" in content_type:
            filename += ".pdf"
        elif "wordprocessingml" in content_type:
            filename += ".docx"
        elif "spreadsheetml" in content_type:
            filename += ".xlsx"
        elif "msword" in content_type:
            filename += ".doc"
        elif "ms-excel" in content_type:
            filename += ".xls"
        elif "officedocument" in content_type:
            filename += ".docx"
        else:
            filename += ".bin"
    logger.info("✅ Загружено: %s (%d байт)", filename, len(raw))
    return raw, filename


def _extract_text(file_data: bytes, filename: str) -> str:
    import base64
    import mimetypes
    ext = pathlib.Path(filename).suffix.lstrip(".").lower()
    _B64_EXTS = {"docx", "jpg", "jpeg", "png", "gif", "bmp", "tiff", "tif", "webp"}
    b64 = base64.b64encode(file_data).decode() if ext in _B64_EXTS else ""
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    att = {"filename": filename, "ext": ext, "data": file_data, "b64": b64, "mime": mime}
    return extract_text_from_attachment(att)


def _build_output_path(
    source_path: str,
    output_dir: str,
    *,
    hash_source: str | None = None,
) -> pathlib.Path:
    source = pathlib.Path(source_path)
    ext = source.suffix.lstrip(".")
    hash_input = hash_source if hash_source is not None else source_path
    hash_suffix = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:8]
    parts = [source.stem]
    if ext:
        parts.append(ext)
    parts.append(hash_suffix)
    out_filename = "_".join(parts) + ".json"
    if output_dir:
        out = pathlib.Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        return out / out_filename
    return source.parent / out_filename


def _save_json_result(result: dict, output_path: pathlib.Path) -> None:
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("💾 Результат сохранён: %s", output_path)


def _extract_document_list_from_steps(steps: list) -> dict:
    for step in steps:
        try:
            if not isinstance(step, (list, tuple)) or len(step) < 2:
                continue
            tool_name, raw_obs = step[0], step[1]
            if tool_name != "generate_document_list":
                continue
            obs = json.loads(raw_obs) if isinstance(raw_obs, str) else raw_obs
            if not isinstance(obs, dict):
                continue
            if "documents" in obs or "error" in obs:
                return obs
        except Exception as exc:
            logger.warning(
                "Не удалось разобрать шаг generate_document_list: %r (%s)",
                step, exc,
            )
    return {}


def process_single_document(
    source: str,
    output_dir: str = "",
    save_to_file: bool = True,
) -> dict:
    logger.info("📄 Обрабатываю документ: %s", source)

    if _is_url(source):
        if not FORCE_REPROCESS:
            dup = db.find_duplicate_job("tender", "", source)
            if dup:
                logger.info("[dedup] Пропускаем дубль: '%s' (ранее обработано %s)",
                            source, str(dup["created_at"])[:10])
                return dup.get("result") or {}
        file_data, filename = _download_document(source)
        eff_url_dir = output_dir or TENDER_OUTPUT_DIR or os.getcwd()
        file_path = os.path.join(eff_url_dir, filename)
        suffix = pathlib.Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTS:
            logger.warning("Неподдерживаемое расширение '%s' для '%s'.", suffix, filename)
            return {"status": "error",
                    "error": f"Unsupported file extension '{suffix}' for '{filename}'.",
                    "filename": filename, "source": source}
    else:
        file_path = source
        filename = pathlib.Path(source).name
        suffix = pathlib.Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTS:
            logger.warning("Неподдерживаемое расширение '%s' для '%s'.", suffix, filename)
            return {"status": "error",
                    "error": f"Unsupported file extension '{suffix}' for '{filename}'.",
                    "filename": filename, "source": source}
        _MAX_LOCAL_BYTES = 50 * 1024 * 1024
        file_size = pathlib.Path(source).stat().st_size
        if file_size > _MAX_LOCAL_BYTES:
            logger.warning("Файл '%s' превышает максимум (%d МБ)", filename, _MAX_LOCAL_BYTES // (1024 * 1024))
            return {"status": "error",
                    "error": f"File '{filename}' exceeds max size ({_MAX_LOCAL_BYTES // (1024 * 1024)} MB).",
                    "filename": filename, "source": source}
        file_data = pathlib.Path(source).read_bytes()

    if _is_url(source):
        dedup_subject = source
    else:
        try:
            dedup_subject = str(pathlib.Path(source).resolve())
        except Exception:
            dedup_subject = filename
        if not FORCE_REPROCESS:
            dup = db.find_duplicate_job("tender", "", dedup_subject)
            if dup:
                logger.info("[dedup] Пропускаем дубль: '%s' (ранее обработано %s)",
                            dedup_subject, str(dup["created_at"])[:10])
                return dup.get("result") or {}

    job_id = db.create_job("tender", sender="", subject=dedup_subject)

    try:
        text = _extract_text(file_data, filename)
        logger.info("📖 Текст извлечён: %s (%d символов)", filename, len(text))

        chat_input = (
            "ТЕНДЕРНЫЙ ДОКУМЕНТ ДЛЯ АНАЛИЗА\n"
            "===========================================\n"
            f"Файл: {filename}\n"
            f"Дата: {datetime.now(UTC).isoformat()}\n\n"
            f"-- СОДЕРЖИМОЕ ДОКУМЕНТА --\n{text}"
        )

        if LLM_BACKEND == "github_models":
            _api_key = OPENAI_API_KEY or GITHUB_TOKEN or ""
            if not _api_key:
                raise ValueError(
                    "GitHub Models backend requires OPENAI_API_KEY or GITHUB_TOKEN to be set"
                )
            _est = estimate_tokens(chat_input)

            # FIX RC-05: double-checked locking для _fallback_chain_cache
            _key_hash = hashlib.sha256(_api_key.encode()).hexdigest()[:16]
            _cache_key = (_key_hash, MODEL_NAME or "")

            with _fallback_chain_cache_lock:
                cached = _fallback_chain_cache.get(_cache_key)

            if cached is None:
                _chain = build_github_fallback_chain(_api_key, MODEL_NAME)
                _model_ctx = probe_max_input_tokens(_api_key, MODEL_NAME)
                with _fallback_chain_cache_lock:
                    # double-check: другой поток мог уже записать
                    if _cache_key not in _fallback_chain_cache:
                        _fallback_chain_cache[_cache_key] = (_chain, _model_ctx)
                    else:
                        _chain, _model_ctx = _fallback_chain_cache[_cache_key]
            else:
                _chain, _model_ctx = cached

            _best_model = max(
                _chain,
                key=lambda m: probe_max_input_tokens(_api_key, m),
            )
            _best_ctx = probe_max_input_tokens(_api_key, _best_model)
            _threshold_ctx = min(_best_ctx, _model_ctx)
            _threshold = max(1, (_threshold_ctx - _TOOLS_TOKEN_OVERHEAD) // 2)

            if _est > _threshold:
                logger.info(
                    "📦 %s: ~%d токенов > порог %d — поблочный анализ "
                    "(chunk_model=%s, chunk_ctx=%d, agent_model=%s, agent_ctx=%d)",
                    filename, _est, _threshold, _best_model, _best_ctx, MODEL_NAME, _model_ctx,
                )
                try:
                    _summary = analyze_document_in_chunks(chat_input, _api_key, _best_model, "tender")
                    if _summary:
                        logger.info("📦 Поблочный анализ: %d → %d символов резюме (~%d токенов)",
                                    len(chat_input), len(_summary), estimate_tokens(_summary))
                        chat_input = _summary
                    else:
                        logger.warning("⚠️ Поблочный анализ не дал результата — используем исходный текст")
                except Exception as _chunk_err:
                    logger.warning("⚠️ Поблочный анализ упал: %s — используем исходный текст", _chunk_err)

        agent = create_tender_agent()
        lf_cb = get_langfuse_callback()
        callbacks = [lf_cb] if lf_cb is not None else []

        with JobTimer("tender"):
            result = agent.invoke(
                {"input": chat_input},
                config={
                    "callbacks": callbacks,
                    "metadata": {"session_id": job_id},
                } if callbacks else {},
            )

        steps = result.get("intermediate_steps", [])
        trace = log_agent_steps(job_id=job_id, agent="tender", steps=steps)

        document_list = _extract_document_list_from_steps(steps)
        if not document_list:
            logger.warning("⚠️ Агент не вызвал generate_document_list, используем текстовый output")
            document_list = {
                "timestamp": datetime.now(UTC).isoformat(),
                "procurement_subject": "Не определён (агент не вызвал инструмент)",
                "documents": [],
                "summary": {"total": 0, "mandatory": 0, "conditional": 0},
                "raw_output": result.get("output", ""),
            }

        document_list["source_document"] = filename
        if "timestamp" not in document_list:
            document_list["timestamp"] = datetime.now(UTC).isoformat()

        if save_to_file:
            eff_output_dir = output_dir or TENDER_OUTPUT_DIR
            output_path = _build_output_path(
                file_path, eff_output_dir,
                hash_source=source if _is_url(source) else None,
            )
            _save_json_result(document_list, output_path)

        tool_error = document_list.get("error")
        if tool_error:
            db.update_job(job_id, status="error",
                          decision=f"Ошибка инструмента: {tool_error}",
                          result=document_list, trace=trace)
            EMAILS_ERRORS.labels(agent="tender", error_type="tool_error").inc()
            logger.warning("⚠️ generate_document_list вернул ошибку: %s", tool_error)
        else:
            db.update_job(
                job_id, status="done",
                decision=f"Найдено документов: {document_list.get('summary', {}).get('total', 0)}",
                result=document_list, trace=trace,
            )
            EMAILS_PROCESSED.labels(agent="tender").inc()
            logger.info("✅ Документ обработан: %s (всего документов: %d)",
                        filename, document_list.get("summary", {}).get("total", 0))
        return document_list

    except Exception as e:
        EMAILS_ERRORS.labels(agent="tender", error_type=type(e).__name__).inc()
        db.update_job(job_id, status="error", error=str(e))
        logger.error("❌ Критическая ошибка при обработке %s: %s", filename, e)
        notify("Ошибка Агент-Тендер. Файл: " + filename + ". " + str(e), level="error")
        raise


def process_tender_documents(
    sources: list[str] | None = None,
    output_dir: str = "",
    save_to_file: bool = True,
) -> list[dict]:
    POLL_CYCLES.labels(agent="tender").inc()
    logger.info("🗂️ Запуск пакетной обработки тендерных документов...")

    if sources is None:
        docs_dir = pathlib.Path(TENDER_DOCS_DIR)
        if not docs_dir.exists():
            logger.warning("Директория '%s' не найдена — создаю пустую.", TENDER_DOCS_DIR)
            docs_dir.mkdir(parents=True, exist_ok=True)
            return []
        sources = [
            str(p)
            for p in sorted(docs_dir.iterdir())
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
        ]
        logger.info("Найдено %d документов в '%s'", len(sources), TENDER_DOCS_DIR)

    if not sources:
        logger.info("Нет документов для обработки.")
        return []

    results = []
    for source in sources:
        try:
            res = process_single_document(source, output_dir=output_dir, save_to_file=save_to_file)
            results.append(res)
        except Exception as e:
            logger.error("❌ Пропуск '%s' из-за ошибки: %s", source, e)
            results.append({"source_document": source, "error": str(e)})

    logger.info("✅ Пакетная обработка завершена: %d документов", len(results))
    return results


if __name__ == "__main__":
    process_tender_documents()
