"""Layer 3: the requirement model — what must be documented per diagnosis.

Entries are YAML files under data/requirements/, human-reviewable, each
carrying at least one citation whose quote the verification suite
string-matches against Layer 1 (V2). Never hand-edit a quote: copy it from
`cli.py quote` output so it is verbatim source text.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

Axis = Literal["type", "stage", "agent", "onset", "site"]

DocType = Literal[
    "discharge_summary", "admission_note", "progress_note",
    "emergency_note", "diagnosis_list", "any",
]

DOC_TYPES: tuple[str, ...] = (
    "discharge_summary", "admission_note", "progress_note",
    "emergency_note", "diagnosis_list",
)


class Citation(BaseModel):
    clause_id: str
    quote: str


class AxisRule(BaseModel):
    axis: Axis
    level: Literal["required", "recommended"]
    evidence_terms: list[str] = Field(min_length=1)
    applies_to: list[DocType] = ["any"]


class DiagnosisRequirement(BaseModel):
    condition: str
    synonyms: list[str] = Field(min_length=1)
    axes: list[AxisRule] = Field(min_length=1)
    recommendation: str
    citations: list[Citation] = Field(min_length=1)


def load_requirements(directory: Path) -> list[DiagnosisRequirement]:
    entries: list[DiagnosisRequirement] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        try:
            entries.append(DiagnosisRequirement.model_validate(raw))
        except ValidationError as error:
            raise ValueError(f"invalid requirement file {path.name}: {error}") from error
    return entries


class Element(BaseModel):
    name: str
    evidence_terms: list[str] = Field(min_length=1)
    level: Literal["required", "recommended"]
    recommendation: str
    citations: list[Citation] = Field(min_length=1)


class DocTypeRequirement(BaseModel):
    doc_type: DocType
    elements: list[Element] = Field(min_length=1)


def load_doc_requirements(directory: Path) -> dict[str, DocTypeRequirement]:
    entries: dict[str, DocTypeRequirement] = {}
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        try:
            entry = DocTypeRequirement.model_validate(raw)
        except ValidationError as error:
            raise ValueError(f"invalid doc requirement file {path.name}: {error}") from error
        entries[entry.doc_type] = entry
    return entries


EXPECTED_CONDITIONS: tuple[str, ...] = (
    "sepsis", "pneumonia", "diabetes mellitus", "chronic kidney disease",
    "acute kidney injury", "anemia", "acute respiratory failure", "heart failure",
    "malnutrition", "fracture", "urinary tract infection", "delirium",
    "copd exacerbation", "pressure injury", "stroke", "surgical wound infection",
    "obesity", "myocardial ischemia", "deconditioning", "adverse medication event",
)
