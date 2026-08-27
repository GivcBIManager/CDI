"""Finding composition with the runtime citation firewall (proposal 2.2):
a Finding without at least one verified citation is never created."""

from dataclasses import dataclass

from cdi_kb.clauses import ClauseStore
from cdi_kb.config import QUOTE_MATCH_THRESHOLD
from cdi_kb.gapcheck import Gap
from cdi_kb.normalize import find_quote
from cdi_kb.requirements_model import DiagnosisRequirement


@dataclass(frozen=True)
class VerifiedCitation:
    clause_id: str
    section_title: str
    page: int
    quote: str


@dataclass(frozen=True)
class Finding:
    finding_type: str
    severity: str
    condition: str
    axis: str
    evidence_excerpt: str
    recommendation: str
    citations: tuple[VerifiedCitation, ...]
    dedupe_key: str


def compose_finding(gap: Gap, requirement: DiagnosisRequirement, store: ClauseStore) -> Finding | None:
    verified: list[VerifiedCitation] = []
    for citation in requirement.citations:
        clause = store.get(citation.clause_id)
        if clause is None:
            continue
        if find_quote(citation.quote, clause.text, QUOTE_MATCH_THRESHOLD).found:
            verified.append(VerifiedCitation(
                clause_id=clause.clause_id, section_title=clause.section_title,
                page=clause.page, quote=citation.quote,
            ))
    if not verified:
        return None
    return Finding(
        finding_type="specificity_gap",
        severity="required" if gap.level == "required" else "recommended",
        condition=gap.condition,
        axis=gap.axis,
        evidence_excerpt=gap.mention.matched_text,
        recommendation=requirement.recommendation,
        citations=tuple(verified),
        dedupe_key=f"{gap.condition}|{gap.axis}",
    )
