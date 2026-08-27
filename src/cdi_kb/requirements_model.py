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


class Citation(BaseModel):
    clause_id: str
    quote: str


class AxisRule(BaseModel):
    axis: Axis
    level: Literal["required", "recommended"]
    evidence_terms: list[str] = Field(min_length=1)


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
