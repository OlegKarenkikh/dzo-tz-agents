"""
Оркестрация обработки документов агентами.

Перенесено из api/app.py (TD-01).
"""
import base64
import concurrent.futures
import json
import logging
import threading
import time
from datetime import UTC, datetime

from fastapi import HTTPException
from openai import APIStatusError, AuthenticationError
from openai import RateLimitError as _RLE

from api.metrics import DECISIONS_TOTAL, JobTimer
from api.schemas import ProcessRequest
from api.services.decision import (
    apply_email_artifact,
    attachment_meta,
    enrich_email_with_tz_summary,
    has_tz_agent_analysis_observation,
    is_result_usable_for_agent,
    is_token_limit_error_text,
    looks_like_tz_content,
    normalize_decision,
)
from config import (
    AGENT_JOB_TIMEOUT_SEC,
    AGENT_MAX_RETRIES,
    AGENT_RATE_LIMIT_BACKOFF,
    GITHUB_TOKEN,
    LLM_BACKEND,
    MODEL_NAME,
)
from shared.database import (
    create_job,
    find_duplicate_job,
    get_job as db_get_job,
    update_job,
)
from shared.insurance_domain import (
    is_insurance_tender,
    validate_insurance_tender_requirements,
)

logger = logging.getLogger("api")

_run_log_lock = threading.Lock()


def format_created_at(created_at: object) -> str:
    if created_at is None:
        return "N/A"
    if hasattr(created_at, "date"):
        return created_at.date().isoformat()
    return str(created_at)[:10]


def check_and_process(
    agent_type: str,
    request: ProcessRequest,
    background_tasks,
    run_log,
    agent_registry: dict,
) -> dict:
    if agent_type not in agent_registry:
        raise HTTPException(status_code=400, detail="Неизвестный агент: " + repr(agent_type))
    if not request.force:
        dup = find_duplicate_job(agent_type, request.sender_email, request.subject)
        if dup:
            logger.info(
                "[dedup] Дубликат для %s/%r/%r -> %s",
                agent_type, request.sender_email, request.subject, dup["job_id"],
            )
            return {
                "duplicate": True,
                "existing_job_id": dup["job_id"],
                "job": dup,
                "message": (
                    "Письмо уже было обработано ("
                    + format_created_at(dup["created_at"])
                    + "). Добавьте force=true чтобы переобработать."
                ),
            }
    job_id = create_job(agent_type, sender=request.sender_email, subject=request.subject)
    background_tasks.add_task(process_with_agent, job_id, agent_type, request, run_log)
    job = db_get_job(job_id)
    return {"duplicate": False, "existing_job_id": None, "job": job, "message": ""}


def process_with_agent(job_id: str, agent_type: str, request: ProcessRequest, run_log: list | None = None) -> None:
    """Фоновая задача: запускает агента и сохраняет результат в БД."""
    from shared.llm import (
        LOCAL_BACKENDS, build_fallback_chain, effective_openai_key,
        estimate_tokens, llm_circuit_breaker,
        probe_local_max_context, probe_max_input_tokens, resolve_local_base_url,
    )

    job = db_get_job(job_id)
    if not job:
        return

    processing_log: dict = {
        "started_at": datetime.now(UTC).isoformat(),
        "agent": agent_type,
        "events": [],
    }

    def _log_event(stage: str, message: str, **details) -> None:
        processing_log["events"].append({
            "ts": datetime.now(UTC).isoformat(),
            "stage": stage,
            "message": message,
            "details": details,
        })

    _last_flush_ts: list[float] = [0.0]
    _flush_min_interval = 1.0

    def _flush_running_log() -> None:
        now = time.monotonic()
        if now - _last_flush_ts[0] < _flush_min_interval:
            return
        _last_flush_ts[0] = now
        update_job(
            job_id,
            status="running",
            result={
                "processing_log": processing_log,
                "request_preview": {
                    "sender_email": request.sender_email,
                    "subject": request.subject,
                    "text_chars": len(request.text or ""),
                    "attachments_count": len(request.attachments or []),
                },
            },
        )

    update_job(job_id, status="running")
    ts = datetime.now(UTC).isoformat()
    logger.info("[%s] Запуск агента %s", job_id, agent_type.upper())

    _log_event(
        "received", "Получен запрос на обработку",
        sender=request.sender_email, subject=request.subject,
        text_chars=len(request.text or ""),
        attachments_count=len(request.attachments or []),
        attachment_names=[a.filename for a in (request.attachments or [])],
    )
    _flush_running_log()

    _has_tz_signal = looks_like_tz_content(
        text=request.text or "",
        subject=request.subject or "",
        attachment_names=[a.filename for a in (request.attachments or [])],
    )

    with JobTimer(agent_type):
        try:
            from shared.file_extractor import extract_text_from_attachment
            attachment_texts: list[str] = []
            for att in request.attachments:
                try:
                    raw = base64.b64decode(att.content_base64)
                    ext = att.filename.rsplit(".", 1)[-1].lower() if "." in att.filename else ""
                    text = extract_text_from_attachment({
                        "filename": att.filename, "ext": ext,
                        "data": raw, "b64": att.content_base64, "mime": att.mime_type,
                    })
                    attachment_texts.append("---- " + att.filename + " ----\n" + text)
                except Exception as e:
                    logger.warning("[%s] Ошибка извлечения %s: %s", job_id, att.filename, e)
                    _log_event("extract_attachment_error", "Ошибка извлечения текста вложения",
                               filename=att.filename, error=str(e))

            _log_event("extract_attachments_done", "Извлечение текста завершено",
                       extracted_count=len(attachment_texts))
            _flush_running_log()

            parts: list[str] = []
            if request.sender_email:
                parts.append("От: " + request.sender_email)
            if request.subject:
                parts.append("Тема: " + request.subject)
            if request.text:
                parts.append("\n-- ТЕКСТ --\n" + request.text)
            if attachment_texts:
                parts.append("\n-- ВЛОЖЕНИЯ --\n" + "\n\n".join(attachment_texts))
            chat_input = "\n".join(parts) if parts else "(пустой запрос)"

            _log_event("prepare_input", "Сформирован input для агента",
                       input_chars=len(chat_input))
            _flush_running_log()

            fallback_chain = build_fallback_chain(MODEL_NAME)
            if LLM_BACKEND == "github_models":
                _api_key = GITHUB_TOKEN or effective_openai_key() or "not-needed"
            else:
                _api_key = effective_openai_key() or GITHUB_TOKEN or "not-needed"

            if LLM_BACKEND == "github_models":
                _preferred_tool_models = {"gpt-4o", "gpt-4o-mini"}
                def _norm(m: str) -> str:
                    return m.split("/")[-1] if "/" in m else m
                _preferred = [m for m in fallback_chain if _norm(m) in _preferred_tool_models]
                if _preferred:
                    fallback_chain = _preferred

            _TOOLS_OVERHEAD = 0
            _est_input = 0
            _ctx_map: dict = {}
            _chunking_threshold_tok = 0

            if LLM_BACKEND == "github_models" or LLM_BACKEND in LOCAL_BACKENDS:
                _TOOLS_OVERHEAD = 6000 if LLM_BACKEND == "github_models" else 3000
                _est_input = estimate_tokens(chat_input)

                def _get_ctx(m: str) -> int:
                    if LLM_BACKEND == "github_models":
                        return probe_max_input_tokens(_api_key, m)
                    return probe_local_max_context(resolve_local_base_url(), m)

                _best_model = max(fallback_chain, key=lambda m: _get_ctx(m) or 0)
                _best_ctx = _get_ctx(_best_model) or 0
                _chunking_threshold_tok = max(1, (_best_ctx - _TOOLS_OVERHEAD) // 2)
                _ctx_map = {m: (_get_ctx(m) or 0) for m in fallback_chain}

                if _est_input > _chunking_threshold_tok:
                    from shared.chunked_analysis import analyze_document_in_chunks
                    try:
                        _summary = analyze_document_in_chunks(chat_input, _api_key, _best_model, agent_type)
                        if _summary:
                            _log_event("chunking_applied", "Включён поблочный анализ",
                                       before_chars=len(chat_input), after_chars=len(_summary),
                                       model=_best_model)
                            chat_input = _summary
                            _flush_running_log()
                    except Exception as _e:
                        logger.warning("[%s] Chunking упал: %s", job_id, _e)

                _est_input = estimate_tokens(chat_input)
                _filtered = [m for m in fallback_chain
                             if (_get_ctx(m) or 0) > _est_input + _TOOLS_OVERHEAD]
                if _filtered:
                    fallback_chain = _filtered
                else:
                    _best2 = max(fallback_chain, key=lambda m: _get_ctx(m) or 0)
                    _max_chars = max(1, (_get_ctx(_best2) or 0) - _TOOLS_OVERHEAD) * 4
                    if len(chat_input) > _max_chars:
                        chat_input = chat_input[:_max_chars]
                    fallback_chain = [_best2] + [m for m in fallback_chain if m != _best2]

            _healthy = llm_circuit_breaker.filter_healthy(fallback_chain)
            if _healthy:
                fallback_chain = _healthy

            logger.info("[%s] Fallback-цепочка: %s", job_id, " → ".join(fallback_chain))
            _log_event("routing", "Цепочка моделей", fallback_chain=fallback_chain,
                       llm_backend=LLM_BACKEND)
            _flush_running_log()

            result: dict = {}
            last_exc: BaseException | None = None
            no_tool_calls_exhausted = False
            token_limit_exhausted = False
            rate_limit_exhausted = False

            for model_idx, model_name in enumerate(fallback_chain):
                soft_tz_retry_used = False
                token_limit_compaction_used = False
                model_input = chat_input
                logger.info("[%s] Попытка с %s (%d/%d)", job_id, model_name,
                            model_idx + 1, len(fallback_chain))
                _log_event("model_attempt", "Запуск на модели",
                           model=model_name, attempt=model_idx + 1, total=len(fallback_chain))
                _flush_running_log()

                max_retries = max(1, AGENT_MAX_RETRIES)
                retry = 0
                compaction_bonus = False

                while True:
                    if retry >= max_retries:
                        if compaction_bonus:
                            compaction_bonus = False
                        else:
                            break
                    try:
                        if agent_type == "dzo":
                            from agent1_dzo_inspector.agent import create_dzo_agent
                            agent = create_dzo_agent(model_name=model_name)
                        elif agent_type == "tz":
                            from agent2_tz_inspector.agent import create_tz_agent
                            agent = create_tz_agent(model_name=model_name)
                        elif agent_type == "tender":
                            from agent21_tender_inspector.agent import create_tender_agent
                            agent = create_tender_agent(model_name=model_name)
                        elif agent_type == "collector":
                            from agent3_collector_inspector.agent import create_collector_agent
                            agent = create_collector_agent(model_name=model_name)
                        else:
                            import importlib
                            mod = importlib.import_module("agent_" + agent_type + ".agent")
                            agent = mod.create_agent(model_name=model_name)

                        if AGENT_JOB_TIMEOUT_SEC > 0:
                            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                                future = ex.submit(agent.invoke, {"input": model_input})
                                try:
                                    result = future.result(timeout=AGENT_JOB_TIMEOUT_SEC)
                                except concurrent.futures.TimeoutError:
                                    raise TimeoutError(f"Агент не завершился за {AGENT_JOB_TIMEOUT_SEC}с")
                        else:
                            result = agent.invoke({"input": model_input})

                        usable, reason = is_result_usable_for_agent(agent_type, result)
                        if not usable:
                            last_exc = RuntimeError(reason)
                            _log_event("model_retry", "Невалидный результат", model=model_name,
                                       reason=reason, retry=retry + 1)
                            _flush_running_log()
                            break

                        if (agent_type == "dzo" and _has_tz_signal
                                and not has_tz_agent_analysis_observation(result)
                                and not soft_tz_retry_used):
                            soft_tz_retry_used = True
                            model_input = (
                                f"{chat_input}\n\n[СЛУЖЕБНОЕ УТОЧНЕНИЕ]\n"
                                "В заявке обнаружено ТЗ. Перед финальным решением вызови "
                                "analyze_tz_with_agent, затем продолжи шаги ДЗО."
                            )
                            _log_event("model_retry", "Мягкий повтор для analyze_tz_with_agent",
                                       model=model_name, retry=retry + 1)
                            _flush_running_log()
                            retry += 1
                            continue

                        _log_event("model_result", "Модель вернула ответ", model=model_name,
                                   intermediate_steps=len(result.get("intermediate_steps", []) or []))
                        llm_circuit_breaker.record_success(model_name)
                        last_exc = None
                        break

                    except TimeoutError:
                        raise
                    except Exception as exc:
                        _es = str(exc)
                        is_rate = isinstance(exc, _RLE) or ("429" in _es and "rate" in _es.lower())
                        is_tok = (
                            (isinstance(exc, APIStatusError) and getattr(exc, "status_code", 0) == 413)
                            or is_token_limit_error_text(_es)
                        )
                        is_auth = isinstance(exc, AuthenticationError) or (
                            isinstance(exc, APIStatusError) and getattr(exc, "status_code", 0) == 401)
                        is_mnf = (isinstance(exc, APIStatusError)
                                  and getattr(exc, "status_code", 0) == 400
                                  and "model_not_found" in _es.lower())
                        is_up = (isinstance(exc, APIStatusError)
                                 and getattr(exc, "status_code", 0) in (502, 503))

                        if is_auth:
                            logger.error("[%s] Auth error %s: %s", job_id, model_name, exc)
                            raise
                        if is_mnf or is_up:
                            llm_circuit_breaker.record_failure(model_name)
                            last_exc = exc
                            break
                        if not is_rate and not is_tok:
                            _log_event("model_error", "Критическая ошибка", model=model_name, error=str(exc))
                            raise

                        last_exc = exc
                        reason = "429 RateLimit" if is_rate else "413 TokenLimit"
                        llm_circuit_breaker.record_failure(model_name)
                        _log_event("model_retry", "Повтор", model=model_name,
                                   reason=reason, retry=retry + 1)
                        _flush_running_log()

                        if is_tok and not token_limit_compaction_used:
                            token_limit_compaction_used = True
                            try:
                                from shared.chunked_analysis import analyze_document_in_chunks
                                _s = analyze_document_in_chunks(model_input, _api_key, model_name, agent_type)
                                if _s and len(_s) < len(model_input):
                                    model_input = _s
                                    compaction_bonus = True
                                    retry += 1
                                    continue
                            except Exception:
                                pass
                            break

                        if retry + 1 < max_retries or compaction_bonus:
                            backoff = min(30, 5 * (2 ** retry))
                            time.sleep(backoff)
                        retry += 1

                if last_exc is None:
                    break

                _AS = APIStatusError
                _RL = _RLE
                _es2 = str(last_exc)
                _sw = (
                    isinstance(last_exc, (_RL, _AS))
                    or any(x in _es2 for x in
                           ["tokens_limit_reached", "429", "413", "502", "503", "NoToolCalls"])
                    or "model_not_found" in _es2.lower()
                )
                if _sw and model_idx + 1 < len(fallback_chain):
                    time.sleep(AGENT_RATE_LIMIT_BACKOFF)
                    continue

            if last_exc is not None:
                _es3 = str(last_exc)
                if "NoToolCalls" in _es3:
                    no_tool_calls_exhausted = True
                elif is_token_limit_error_text(_es3):
                    token_limit_exhausted = True
                elif "429" in _es3 and "rate" in _es3.lower():
                    rate_limit_exhausted = True
                else:
                    raise last_exc

            # ── Разбор intermediate_steps ──────────────────────────
            decision = ""
            artifacts: dict = {}
            for step_idx, step in enumerate(result.get("intermediate_steps", []), start=1):
                try:
                    tool_name = "tool"
                    if isinstance(step, (list, tuple)) and step:
                        raw = step[0]
                        tool_name = raw if isinstance(raw, str) else getattr(raw, "name", type(raw).__name__)
                    obs = json.loads(step[1]) if isinstance(step[1], str) else step[1]
                    if not isinstance(obs, dict):
                        continue
                    _log_event("tool_result", "Результат tool", step=step_idx,
                               tool=tool_name, keys=sorted(obs.keys())[:20])
                    if obs.get("decision"):
                        decision = obs["decision"]
                    if obs.get("emailHtml"):
                        apply_email_artifact(artifacts, tool_name, obs["emailHtml"])
                    if obs.get("tezisFormHtml"):
                        artifacts["tezis_form_html"] = obs["tezisFormHtml"]
                    if obs.get("correctedHtml"):
                        artifacts["corrected_html"] = obs["correctedHtml"]
                    if obs.get("escalationHtml"):
                        artifacts["escalation_html"] = obs["escalationHtml"]
                    if "checklist_required" in obs or "checklist_attachments" in obs:
                        artifacts["validation_report"] = obs
                    if "sections" in obs and isinstance(obs.get("sections"), list):
                        artifacts["json_report"] = obs
                    if "html" in obs and "title" in obs:
                        artifacts["corrected_tz_html"] = obs["html"]
                    if obs.get("tzAgentAnalysis") and isinstance(obs.get("tzAgentAnalysis"), dict):
                        artifacts["tz_agent_analysis"] = obs["tzAgentAnalysis"]
                    if obs.get("peerAgentResult") and isinstance(obs.get("peerAgentResult"), dict):
                        artifacts.setdefault("peer_agent_results", []).append(obs["peerAgentResult"])
                    if (agent_type == "tender" and isinstance(step, (list, tuple))
                            and len(step) >= 2 and step[0] == "generate_document_list"):
                        if "documents" in obs and isinstance(obs.get("documents"), list):
                            summary = obs.get("summary") or {}
                            if not isinstance(summary, dict):
                                summary = {}
                            total = summary.get("total", len(obs["documents"]))
                            artifacts["document_list"] = {**obs, "total": total}
                            artifacts["tender_tool_status"] = "documents_found"
                            if not decision:
                                decision = "documents_found"
                        elif "error" in obs and not artifacts.get("document_list"):
                            artifacts["document_list_error"] = obs
                            artifacts["tender_tool_status"] = "tool_error"
                            if not decision:
                                decision = "tool_error"
                except Exception as _se:
                    logger.warning("[%s] step parse error: %s", job_id, _se)

            enrich_email_with_tz_summary(artifacts)

            if not decision:
                if no_tool_calls_exhausted:
                    decision = "tool_calls_missing"
                    artifacts["model_error"] = {"code": "NoToolCalls",
                                                "message": "Модель не выполнила tool-вызовы"}
                elif token_limit_exhausted:
                    decision = "token_limit_exhausted"
                    artifacts["model_error"] = {"code": "TokenLimitExhausted",
                                                "message": "Все попытки завершились ошибкой 413"}
                elif rate_limit_exhausted:
                    decision = "rate_limit_exhausted"
                    artifacts["model_error"] = {"code": "RateLimitExhausted",
                                                "message": "Все попытки завершились ошибкой 429"}
                else:
                    decision = "Неизвестно"

            technical_status: str | None = None
            agent_output = result.get("output", "")
            decision, technical_status = normalize_decision(decision, agent_output)
            if technical_status:
                artifacts["decision_technical"] = technical_status

            if agent_type == "dzo" and _has_tz_signal and not artifacts.get("tz_agent_analysis"):
                artifacts["missing_recommended_tool"] = {
                    "code": "MissingRecommendedTool",
                    "tool": "analyze_tz_with_agent",
                    "message": "ТЗ-контент обнаружен, но делегированный анализ не вызван.",
                }

            if agent_type == "tender":
                try:
                    _ft = " ".join(att.filename or "" for att in (request.attachments or []))
                    if not _ft:
                        _ft = result.get("output", "")
                    if _ft and is_insurance_tender(_ft):
                        _cbr = validate_insurance_tender_requirements(_ft)
                        artifacts["insurance_cbr_check"] = _cbr
                        if not _cbr["has_cbr_license"] and decision not in (
                            "ВЕРНУТЬ НА ДОРАБОТКУ", "tool_calls_missing",
                            "token_limit_exhausted", "rate_limit_exhausted",
                        ):
                            artifacts["decision_override"] = {
                                "previous_decision": decision,
                                "override_reason": "Отсутствует требование лицензии ЦБ РФ (Закон 4015-1)",
                                "missing_requirements": _cbr["missing_requirements"],
                            }
                            decision = "ВЕРНУТЬ НА ДОРАБОТКУ"
                except Exception as _cbr_err:
                    logger.warning("[%s] CBR post-check error: %s", job_id, _cbr_err)

            if artifacts:
                logger.info("[%s] Артефакты: %s", job_id, ", ".join(artifacts.keys()))
            if decision:
                DECISIONS_TOTAL.labels(agent=agent_type, decision=decision).inc()

            processing_log["completed_at"] = datetime.now(UTC).isoformat()
            _log_event("completed", "Обработка завершена",
                       decision=decision, artifacts=sorted(artifacts.keys()))

            update_job(
                job_id, status="done", decision=decision,
                result={
                    "output": result.get("output", ""),
                    "decision": decision,
                    "request_payload": {
                        **{k: v for k, v in request.model_dump().items() if k != "attachments"},
                        "attachments": attachment_meta(request.attachments or []),
                    },
                    "processing_log": processing_log,
                    **artifacts,
                },
            )
            with _run_log_lock:
                if run_log is not None:
                    run_log.append({"agent": agent_type, "ts": ts, "status": "ok", "job_id": job_id})
            logger.info("[%s] Завершено. Решение: %s", job_id, decision)

        except Exception as e:
            _log_event("failed", "Обработка завершилась ошибкой", error=str(e))
            processing_log["failed_at"] = datetime.now(UTC).isoformat()
            update_job(
                job_id, status="error", error=str(e),
                result={
                    "request_payload": {
                        **{k: v for k, v in request.model_dump().items() if k != "attachments"},
                        "attachments": attachment_meta(request.attachments or []),
                    },
                    "processing_log": processing_log,
                },
            )
            with _run_log_lock:
                if run_log is not None:
                    run_log.append({"agent": agent_type, "ts": ts, "status": "error",
                                "job_id": job_id, "error": str(e)})
            logger.error("[%s] Ошибка: %s", job_id, e)
            return

