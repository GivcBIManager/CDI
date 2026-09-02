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
DOC_REQUIREMENTS_DIR = REPO_ROOT / "data" / "doc_requirements"
NECESSITY_DIR = REPO_ROOT / "data" / "necessity"
PROVIDER_RULES_DIR = REPO_ROOT / "data" / "provider_rules"
INTEGRITY_RULES_DIR = REPO_ROOT / "data" / "integrity_rules"
EVAL_DIR = REPO_ROOT / "data" / "eval"

ANTHROPIC_MODEL = "claude-sonnet-5"
QUOTE_MATCH_THRESHOLD = 0.95
SOURCE_ID = "CDI-2021"  # citation prefix for the booklet

_CHI_DIR = REPO_ROOT / "CHI_Guidelines"
_MOH_DIR = REPO_ROOT / "MOH_Protocols"

# MOH-KSA national clinical protocols: 31 of the 93 downloaded (see
# MOH_Protocols/manifest.csv and moh_download.py). Curated, not exhaustive --
# excluded are 4 image-only PDFs (0 extracted chars, need OCR), 2 pure inventory
# tables below MIN_SOURCE_CLAUSES, and the administrative/out-of-scope
# remainder. A (id, filename, title) table rather than 31 SourceDoc calls: the
# authority and genre are identical for every one, so repeating them 31 times
# would only invite one of them to drift.
_MOH_PROTOCOLS: tuple[tuple[str, str, str], ...] = (
    # Role A -- third authority for existing requirement entries
    ("MOH-DM", "Saudi-Diabetes-Clinical-Practice-Guidelines.pdf", "MOH Saudi Diabetes Clinical Practice Guidelines"),
    ("MOH-SEPSIS-MAT", "Maternal-Sepsis-Management.pdf", "MOH Maternal Sepsis Management"),
    ("MOH-PN-ADULT", "Adult-Parenteral-Nutrition-CPG.pdf", "MOH Adult Parenteral Nutrition CPG"),
    ("MOH-MENINGITIS", "Acute-CNS-Infections-Meningitis-Adults.pdf", "MOH Acute CNS Infections Meningitis Adults"),
    ("MOH-IAI", "Intra-abdominal-Infections-Treatment.pdf", "MOH Intra-abdominal Infections Treatment"),
    ("MOH-HD", "Home-Hemodialysis-Complications.pdf", "MOH Home Hemodialysis Complications"),
    ("MOH-LRTI", "Lower-Respiratory-Tract-Infections.pdf", "MOH Lower Respiratory Tract Infections"),
    ("MOH-SEPSIS-PED", "Pediatric-Sepsis-Management.pdf", "MOH Pediatric Sepsis Management"),
    ("MOH-UTI", "Urinary-Tract-Infection.pdf", "MOH Urinary Tract Infection"),
    ("MOH-SSI", "Surgical-Site-Infections-Guidelines.pdf", "MOH Surgical Site Infections Guidelines"),
    ("MOH-SSTI", "Skin-and-Soft-Tissue-Infection.pdf", "MOH Skin and Soft Tissue Infection"),
    # Role B -- candidates for new condition entries (slice 2)
    ("MOH-DKA", "DKA-HHS-Protocol.pdf", "MOH DKA/HHS Protocol"),
    ("MOH-DKA-PED", "Pediatric-DKA-HHS-Protocol.pdf", "MOH Pediatric DKA/HHS Protocol"),
    ("MOH-VTE", "VTE-Prevention-Adults-v1.7.pdf", "MOH VTE Prevention in Adults"),
    ("MOH-FH", "Familial-Hypercholesterolemia.pdf", "MOH Familial Hypercholesterolemia"),
    ("MOH-RA", "Rheumatoid-Arthritis-Adults.pdf", "MOH Rheumatoid Arthritis in Adults"),
    ("MOH-HIE", "Neonatal-Hypoxic-Ischemic-Encephalopathy.pdf", "MOH Neonatal Hypoxic Ischemic Encephalopathy"),
    ("MOH-MDD", "Major-Depressive-Disorder.pdf", "MOH Major Depressive Disorder"),
    ("MOH-HYPOGLYCEMIA", "Inpatient-Hypoglycemia-Management.pdf", "MOH Inpatient Hypoglycemia Management"),
    ("MOH-HEADACHE", "Headache-Disorder.pdf", "MOH Headache Disorder"),
    ("MOH-DVT", "DVT-Treatment-Adults-2024.pdf", "MOH DVT Treatment in Adults"),
    ("MOH-PE", "Pulmonary-Embolism-Adults.pdf", "MOH Pulmonary Embolism in Adults"),
    ("MOH-GAS", "Group-A-Streptococcal-Pharyngitis.pdf", "MOH Group A Streptococcal Pharyngitis"),
    ("MOH-ANAPHYLAXIS", "Anaphylaxis-Management-Adults-Pediatrics.pdf", "MOH Anaphylaxis Management"),
    # Role C -- candidates for necessity / order rules (slice 2)
    ("MOH-CONTRAST", "Safe-Use-of-Contrast-Media-Radiology.pdf", "MOH Safe Use of Contrast Media in Radiology"),
    ("MOH-WARFARIN", "Warfarin-Monitoring-Adults.pdf", "MOH Warfarin Monitoring in Adults"),
    ("MOH-TDM-VANCO", "Adult-TDM-Protocol-Vancomycin-and-Aminoglycosides.pdf",
     "MOH Adult TDM Protocol: Vancomycin and Aminoglycosides"),
    ("MOH-ANTICOAG-REV", "Anticoagulation-Reversal-Strategies.pdf", "MOH Anticoagulation Reversal Strategies"),
    ("MOH-ABX-PROPH", "Antibiotic-Surgical-Prophylaxis.pdf", "MOH Antibiotic Surgical Prophylaxis"),
    ("MOH-ALBUMIN", "Prescribing-Albumin-Protocol-Dec2024.pdf", "MOH Prescribing Albumin Protocol"),
    ("MOH-SUP", "Stress-Ulcer-Prophylaxis-ICU-and-non-ICU.pdf", "MOH Stress Ulcer Prophylaxis (ICU and non-ICU)"),
)


@dataclass(frozen=True)
class SourceDoc:
    source_id: str
    path: Path
    title: str
    authority: str
    genre: str  # "booklet" | "chi_prose" | "necessity" | "moh_protocol"


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
            "CHI-BARIATRIC",
            _CHI_DIR / "Bariatric and Metabolic Surgery.pdf",
            "CHI Bariatric and Metabolic Surgery Guidelines",
            "CHI",
            "chi_prose",
        ),
        # Prose-extractable despite the table-heavy layout: page 3 (scope/population) is
        # clean paragraphs and pg6/p1 opens with clean HAP/VAP bullets before degrading
        # into a dosing table; the dosing tables (pages 4-5, 7 and the tail of pg6/p1)
        # extract garbled-but-verbatim (V1 still holds; only clean sentences are quoted).
        SourceDoc(
            "CHI-LRTI",
            _CHI_DIR / "Lower Respiratory Tract Infection.pdf",
            "CHI Lower Respiratory Tract Infections Management Protocol",
            "CHI",
            "chi_prose",
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
        *(
            SourceDoc(source_id, _MOH_DIR / filename, title, "MOH", "moh_protocol")
            for source_id, filename, title in _MOH_PROTOCOLS
        ),
    )
}

# Citation display order. MOH-KSA is the national health ministry, CHI the
# insurance/quality authority, TCC the coding-education booklet publisher; a
# clinician reading a finding should meet the strongest authority first. An
# authority absent from this map sorts last rather than raising -- a new source
# family must never be able to break finding composition.
AUTHORITY_RANK: dict[str, int] = {"MOH": 0, "CHI": 1, "TCC": 2}
_UNRANKED_AUTHORITY = len(AUTHORITY_RANK)


def authority_of(clause_id: str) -> str:
    """The authority that published the clause, from its source-id prefix."""
    source = SOURCES.get(clause_id.split("/", 1)[0])
    return source.authority if source else ""


def authority_rank(clause_id: str) -> int:
    return AUTHORITY_RANK.get(authority_of(clause_id), _UNRANKED_AUTHORITY)
