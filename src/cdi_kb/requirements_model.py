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
    # Optional per-axis query text. Without it a multi-axis condition prints the
    # same condition-level `recommendation` for every axis, so a "missing site"
    # finding could tell the clinician to document the causative organism the
    # note already documents. Falls back to DiagnosisRequirement.recommendation.
    recommendation: str | None = None
    # Opt-in: whether two different evidence terms for this axis, written by two
    # different authors, should be reported as conflicting documentation. Off by
    # default because most axis term lists are not mutually exclusive -- an onset
    # axis lists acute / chronic / acute on chronic, and "acute" appears in ordinary
    # prose like "no acute infiltrate".
    conflict_check: bool = False


class AmbiguousSynonym(BaseModel):
    """A term that legitimately names more than one condition (e.g. "ARF" is
    both acute renal failure and acute respiratory failure). It is only claimed
    for this condition when one of `requires_nearby` appears near the mention;
    with no cue either way, no condition claims it. Assigning an ambiguous
    abbreviation to the wrong organ system sends the clinician a query about a
    condition the patient may not have, which is worse than raising nothing."""
    term: str
    requires_nearby: list[str] = Field(min_length=1)


class DiagnosisRequirement(BaseModel):
    condition: str
    synonyms: list[str] = Field(min_length=1)
    axes: list[AxisRule] = Field(min_length=1)
    recommendation: str
    citations: list[Citation] = Field(min_length=1)
    ambiguous_synonyms: list[AmbiguousSynonym] = []


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


class ProviderRule(BaseModel):
    """Who must have recorded a diagnosis for it to count as documented.

    `role` names the author role whose documentation is NOT sufficient on its
    own; a condition every mention of which falls inside a segment of that role
    raises a provider-confirmation finding.
    """
    role: str
    level: Literal["required", "recommended"]
    recommendation: str
    citations: list[Citation] = Field(min_length=1)


def load_provider_rules(directory: Path) -> list[ProviderRule]:
    rules: list[ProviderRule] = []
    if not directory.exists():
        return rules
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        try:
            rules.append(ProviderRule.model_validate(raw))
        except ValidationError as error:
            raise ValueError(f"invalid provider rule file {path.name}: {error}") from error
    return rules


class IntegrityRule(BaseModel):
    """A documentation-integrity rule that is not about one diagnosis: it is about
    the note itself (copy-forward) or about two statements contradicting each other.

    `cue_terms` is used only by cue-detected kinds (copy_forward); structurally
    detected kinds (conflicting_documentation) leave it empty."""
    kind: Literal["copy_forward", "conflicting_documentation"]
    level: Literal["required", "recommended"]
    cue_terms: list[str] = []
    recommendation: str
    citations: list[Citation] = Field(min_length=1)


def load_integrity_rules(directory: Path) -> list[IntegrityRule]:
    rules: list[IntegrityRule] = []
    if not directory.exists():
        return rules
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        try:
            rules.append(IntegrityRule.model_validate(raw))
        except ValidationError as error:
            raise ValueError(f"invalid integrity rule file {path.name}: {error}") from error
    return rules


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


class NecessityRule(BaseModel):
    order: str
    display_name: str
    order_terms: list[str] = Field(min_length=1)
    context_cues: list[str] = Field(min_length=1)
    valid_indication_terms: list[str] = Field(min_length=1)
    level: Literal["required", "recommended"] = "required"
    recommendation: str
    citations: list[Citation] = Field(min_length=1)


def load_necessity_rules(directory: Path) -> list[NecessityRule]:
    entries: list[NecessityRule] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        try:
            entries.append(NecessityRule.model_validate(raw))
        except ValidationError as error:
            raise ValueError(f"invalid necessity rule file {path.name}: {error}") from error
    return entries


EXPECTED_CONDITIONS: tuple[str, ...] = (
    "sepsis", "pneumonia", "diabetes mellitus", "chronic kidney disease",
    "acute kidney injury", "anemia", "acute respiratory failure", "heart failure",
    "malnutrition", "fracture", "urinary tract infection", "delirium",
    "copd exacerbation", "pressure injury", "stroke", "surgical wound infection",
    "obesity", "myocardial ischemia", "deconditioning", "adverse medication event",
)
