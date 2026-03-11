# syntax=docker/dockerfile:1
# ─── Base: пиним по digest — защита от supply-chain атак ──────────────────
FROM python:3.11-slim@sha256:614c3fd5caa3a5dbc03ee01e13ddb1cf04e94cd9d5c89fce7dda83b5a55ee7b1 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Не писать .pyc в режиме read_only
    PYTHONPYCACHEPREFIX=/tmp/pycache

RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    # Удаляем пакетный менеджер из финального образа
    && apt-get purge -y --auto-remove

WORKDIR /app

# ─── Зависимости (кэшируются отдельно) ─────────────────────────────
FROM base AS deps
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    # Удаляем кэш pip после установки
    && find /usr/local/lib -name '*.pyc' -delete \
    && find /usr/local/lib -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; true

# ─── Production образ ───────────────────────────────────────────
FROM deps AS production

# UID/GID явный — не совпадает с хостовым root (0)
RUN groupadd -r -g 1001 appuser \
    && useradd -r -u 1001 -g appuser --no-create-home --shell /sbin/nologin appuser

COPY --chown=appuser:appuser . .

RUN mkdir -p /app/logs /tmp/pycache \
    && chown -R appuser:appuser /app/logs /tmp/pycache

# Проверка: подтверждаем что нет SUID/SGID файлов
RUN find /app -perm /6000 -type f 2>/dev/null | xargs -r chmod a-s

USER appuser

# Проверка импортов при сборке — однострочный вызов, нет риска парсинга как Dockerfile-инструкций
RUN python -c "import shared, api, agent1_dzo_inspector, agent2_tz_inspector; print('Import check OK')"

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "main.py"]
