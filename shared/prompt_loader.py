"""
Prompt loader — загрузка системных промптов из файлов.

Промпты хранятся в директории prompts/ в корне проекта.
Версионирование: dzo_v1.md, dzo_v2.md и т.д.
Текущая версия указывается в каждом агенте.
"""
import pathlib
import functools
import logging

logger = logging.getLogger("prompt_loader")

_PROMPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "prompts"

_LATEST_VERSIONS = {
    "tz": "v2",
    "tender": "v2",
    "dzo": "v1",
    "collector": "v1",
}


@functools.lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    """Load and cache a prompt from prompts/ directory.

    Args:
        name: filename in prompts/ dir, e.g. "dzo_v1.md"

    Returns:
        Prompt text (stripped).

    Raises:
        FileNotFoundError: if the prompt file doesn't exist.
    """
    path = _PROMPTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Промпт {name} не найден в {_PROMPTS_DIR}")
    text = path.read_text(encoding="utf-8").strip()
    logger.info("Загружен промпт %s (%d символов)", name, len(text))
    return text


def list_prompts() -> list[dict]:
    """List available prompts with metadata."""
    result = []
    for p in sorted(_PROMPTS_DIR.glob("*.md")):
        result.append({
            "name": p.name,
            "agent": p.stem.rsplit("_", 1)[0],
            "version": p.stem.rsplit("_", 1)[-1] if "_" in p.stem else "v1",
            "size": p.stat().st_size,
        })
    return result
