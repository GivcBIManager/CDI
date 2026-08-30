"""Central paths and constants for the CDI KB demo."""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, comments ignored.

    Never overrides variables already present in the environment, so a real
    exported ANTHROPIC_API_KEY always wins over the file.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


_load_dotenv(REPO_ROOT / ".env")
BOOKLET_PDF = REPO_ROOT / "CDI Course Booklet - Clinicians.pdf"

VAR_DIR = REPO_ROOT / "var"
RAW_TEXT_DIR = VAR_DIR / "raw_text"
KB_DB = VAR_DIR / "kb.sqlite"

REQUIREMENTS_DIR = REPO_ROOT / "data" / "requirements"
EVAL_DIR = REPO_ROOT / "data" / "eval"

ANTHROPIC_MODEL = "claude-opus-5"
QUOTE_MATCH_THRESHOLD = 0.95
SOURCE_ID = "CDI-2021"  # citation prefix for the booklet
