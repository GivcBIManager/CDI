"""Central paths and constants for the CDI KB demo."""

import os
from dataclasses import dataclass
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

ANTHROPIC_MODEL = "claude-sonnet-5"
QUOTE_MATCH_THRESHOLD = 0.95
SOURCE_ID = "CDI-2021"  # citation prefix for the booklet

_CHI_DIR = REPO_ROOT / "CHI_Guidelines"


@dataclass(frozen=True)
class SourceDoc:
    source_id: str
    path: Path
    title: str
    authority: str
    genre: str  # "booklet" | "chi_prose" | "necessity"


SOURCES: dict[str, SourceDoc] = {
    source.source_id: source
    for source in (
        SourceDoc("CDI-2021", BOOKLET_PDF, "CDI Course Booklet – Clinicians (2021)", "TCC", "booklet"),
        SourceDoc("CHI-HF", _CHI_DIR / "Heart Failure.pdf", "CHI Heart Failure Guideline", "CHI", "chi_prose"),
        SourceDoc(
            "CHI-CKD", _CHI_DIR / "Chronic Kidney Disease.pdf", "CHI Chronic Kidney Disease Guideline", "CHI", "chi_prose"
        ),
        SourceDoc("CHI-ANEMIA", _CHI_DIR / "Anemia.pdf", "CHI Anemia Guideline", "CHI", "chi_prose"),
        SourceDoc(
            "CHI-STROKE", _CHI_DIR / "Saudi Stroke Standards.pdf", "Saudi Stroke Standards", "CHI", "chi_prose"
        ),
        SourceDoc(
            "CHI-NEC-HBA1C",
            _CHI_DIR / "Medical Necessity Criteria for HgA1c Testing.pdf",
            "CHI Necessity Criteria: HbA1c",
            "CHI",
            "necessity",
        ),
        SourceDoc(
            "CHI-NEC-FBG",
            _CHI_DIR / "Medical Necessity Criteria for Fasting Blood Glucose Testing.pdf",
            "CHI Necessity Criteria: Fasting Blood Glucose",
            "CHI",
            "necessity",
        ),
        SourceDoc(
            "CHI-NEC-UCULT",
            _CHI_DIR / "Medical Necessity Criteria for Urine Culture Testing in Pediatrics.pdf",
            "CHI Necessity Criteria: Urine Culture (Pediatrics)",
            "CHI",
            "necessity",
        ),
        SourceDoc(
            "CHI-NEC-B12",
            _CHI_DIR / "Medical Necessity Criteria for Vitamin B12 Testing.pdf",
            "CHI Necessity Criteria: Vitamin B12",
            "CHI",
            "necessity",
        ),
        # CHI-NEC-LBPMRI (Low Back Pain MRI.pdf): flowchart genre — excluded until VLM
        # linearization; see task-1-report
    )
}
