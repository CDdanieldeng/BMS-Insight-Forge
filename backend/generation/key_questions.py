"""Load key business questions from config file."""

from pathlib import Path

from shared.logging_config import setup_logging

logger = setup_logging("generation")

# Default path for Docker (/app is backend workdir, config mounted at /app/config)
DEFAULT_CONFIG_PATH = Path("/app/config/key_business_questions.md")
# Fallback for local dev: project_root/config
_project_root = Path(__file__).resolve().parent.parent.parent
FALLBACK_CONFIG_PATH = _project_root / "config" / "key_business_questions.md"

_cached: dict[str, list[str]] | None = None


def _find_config_path() -> Path:
    """Find the config file path."""
    candidates = [
        DEFAULT_CONFIG_PATH,
        Path("config/key_business_questions.md"),
        FALLBACK_CONFIG_PATH,
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(f"key_business_questions.md not found. Tried: {candidates}")


def load_key_questions() -> dict[str, list[str]]:
    """
    Parse key_business_questions.md and return {module_name: [questions]}.
    """
    global _cached
    if _cached is not None:
        return _cached

    path = _find_config_path()
    text = path.read_text(encoding="utf-8")

    result: dict[str, list[str]] = {}
    current_module: str | None = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith("## "):
            current_module = line[3:].strip()
            result[current_module] = []
            continue

        if current_module and line and line[0].isdigit() and ". " in line:
            parts = line.split(". ", 1)
            if len(parts) == 2:
                result[current_module].append(parts[1].strip())

    logger.info("Loaded key questions for modules: %s", list(result.keys()))
    _cached = result
    return result


def get_questions_for_module(module: str) -> list[str]:
    """Get key questions for a specific module."""
    all_questions = load_key_questions()
    return all_questions.get(module, [])
