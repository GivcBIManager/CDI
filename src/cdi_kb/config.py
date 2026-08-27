"""Central paths and constants for the CDI KB demo."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BOOKLET_PDF = REPO_ROOT / "CDI Course Booklet - Clinicians.pdf"

VAR_DIR = REPO_ROOT / "var"
RAW_TEXT_DIR = VAR_DIR / "raw_text"
KB_DB = VAR_DIR / "kb.sqlite"

REQUIREMENTS_DIR = REPO_ROOT / "data" / "requirements"
EVAL_DIR = REPO_ROOT / "data" / "eval"

ANTHROPIC_MODEL = "claude-opus-5"
QUOTE_MATCH_THRESHOLD = 0.95
SOURCE_ID = "CDI-2021"  # citation prefix for the booklet
