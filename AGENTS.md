# AGENTS.md

## Cursor Cloud specific instructions

### Overview

DZO/TZ Agents is a Python 3.11+ LLM-powered email processing system using FastAPI (API) + Streamlit (UI) + LangChain (agents). The database layer falls back to in-memory storage when `DATABASE_URL` is not set, so PostgreSQL is **not required** for local development/testing.

### Running services

- **FastAPI API**: `make api` → http://localhost:8000 (Swagger at `/docs`, health at `/health`)
- **Streamlit UI**: `make ui` → http://localhost:8501
- **Both together**: `make api-ui`

### Key commands

| Task | Command |
|------|---------|
| Install deps | `pip install -e ".[ui,dev]"` |
| Lint | `make lint` |
| Format | `make fmt` |
| Test | `make test` (run **without** `.env` loaded, or ensure env vars don't conflict with test expectations) |
| API | `make api` |
| UI | `make ui` |

### Gotchas

- The `Makefile` uses `python` (not `python3`). If `python` is not on PATH, create a symlink: `ln -sf $(which python3) /usr/local/bin/python`.
- **Tests and `.env` conflict**: 5 tests (`test_llm.py`, `test_ui_config.py`) fail when a `.env` file is present because `conftest.py` sets `OPENAI_API_KEY=sk-test` and `API_KEY=test-secret`, but `python-dotenv` loads `.env` values that override these. To run tests cleanly, either temporarily rename `.env` or run without it. This is expected behavior, not a code bug.
- The application works without real LLM API keys for API CRUD operations (health, jobs, stats, agents list). Background agent processing (actual LLM calls) requires a valid `OPENAI_API_KEY` or `GITHUB_TOKEN`.
- `.env.example` should be copied to `.env` and configured. Minimum required for API startup: `API_KEY` (any string for REST API auth).
