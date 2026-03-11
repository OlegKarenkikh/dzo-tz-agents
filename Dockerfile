# syntax=docker/dockerfile:1
# ─── Base: пиним по digest — защита от supply-chain атак ──────────────────
FROM python:3.11-slim@sha256:d6e4d224f70f9e0172a06a3a2eba2f768eb146811a349278b38fff3a36463b47 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPYCACHEPREFIX=/tmp/pycache

RUN apt-get update && apt-get install -y --no-install-recommends \
        poppler-utils \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get purge -y --auto-remove

WORKDIR /app

# ─── Зависимости (кэшируются отдельно) ─────────────────────────────
FROM base AS deps
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && find /usr/local/lib -name '*.pyc' -delete \
    && find /usr/local/lib -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; true

# ─── Production образ ───────────────────────────────────────────
FROM deps AS production

RUN groupadd -r -g 1001 appuser \
    && useradd -r -u 1001 -g appuser --no-create-home --shell /sbin/nologin appuser

COPY --chown=appuser:appuser . .

RUN mkdir -p /app/logs /tmp/pycache \
    && chown -R appuser:appuser /app/logs /tmp/pycache

RUN find /app -perm /6000 -type f 2>/dev/null | xargs -r chmod a-s

USER appuser

RUN python -c "import shared, api, agent1_dzo_inspector, agent2_tz_inspector; print('Import check OK')"

EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "main.py"]
