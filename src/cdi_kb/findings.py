"""Finding composition with the runtime citation firewall (proposal 2.2):
a Finding without at least one verified citation is never created.

The one deliberate exception is the LLM-inference path (compose_inferred_finding).
There, the KB is the validation authority: the model's observation is checked
against retrieved clause text, and if no clause survives verification the finding
is still reported -- explicitly marked NO_KB_REFERENCE, with zero citations.
Reporting "no reference in the KB" is the honest answer; silently dropping the
observation, or falling back to a pre-authored citation the documents did not
actually support, are both worse.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cdi_kb.clauses import ClauseStore
from cdi_kb.config import QUOTE_MATCH_THRESHOLD, authority_of, authority_rank
from cdi_kb.gapcheck import Gap
from cdi_kb.necessity import NecessityGap
from cdi_kb.normalize import find_quote
from cdi_kb.requirements_model import (
    Citation, DiagnosisRequirement, Element, IntegrityRule, ProviderRule,
)

if TYPE_CHECKING:  # annotation-only: keeps the offline path free of llm_infer/anthropic
    from cdi_kb.llm_infer import KbSupport, NoteObservation

KB_SUPPORTED = "supported"
NO_KB_REFERENCE = "no reference in the KB"


@dataclass(frozen=True)
class VerifiedCitation:
    clause_id: str
    section_title: str
    page: int
    quote: str
    authority: str


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
    kb_status: str = KB_SUPPORTED


def _verified_citations(citations: list[Citation], store: ClauseStore) -> list[VerifiedCitation]:
    """THE only citation-verification code path: every Finding-producing
    composer (diagnosis-gap, doc-type-element-gap, and any future finding
    type) must route through this to keep a single audited firewall.

    Verified citations are returned ordered by publishing authority (MOH ->
    CHI -> CDI-2021). The sort is stable and keys on rank alone, so two
    citations from the same authority keep their input order -- for a
    deterministic composer that is the order the YAML author gave them; for
    an LLM-inferred finding (compose_inferred_finding in this module) the
    input is the model's own relevance ranking from Pass B, not an author's
    ordering, and that ranking is what the stable sort preserves within an
    authority tier."""
    verified: list[VerifiedCitation] = []
    for citation in citations:
        clause = store.get(citation.clause_id)
        if clause is None:
            continue
        if find_quote(citation.quote, clause.text, QUOTE_MATCH_THRESHOLD).found:
            verified.append(VerifiedCitation(
                clause_id=clause.clause_id, section_title=clause.section_title,
                page=clause.page, quote=citation.quote,
                authority=authority_of(clause.clause_id),
            ))
    verified.sort(key=lambda c: authority_rank(c.clause_id))
    return verified


def compose_finding(gap: Gap, requirement: DiagnosisRequirement, store: ClauseStore) -> Finding | None:
    verified = _verified_citations(requirement.citations, store)
    if not verified:
        return None
    return Finding(
        finding_type="specificity_gap",
        severity="required" if gap.level == "required" else "recommended",
        condition=gap.condition,
        axis=gap.axis,
        evidence_excerpt=gap.mention.matched_text,
        recommendation=_recommendation_for(requirement, gap.axis),
        citations=tuple(verified),
        dedupe_key=f"{gap.condition}|{gap.axis}",
    )


def compose_inferred_finding(
    observation: "NoteObservation",
    requirement: DiagnosisRequirement,
    supports: list["KbSupport"],
    store: ClauseStore,
) -> Finding:
    """Compose an LLM-inferred finding after KB validation.

    `supports` are the clause references the model selected from the RETRIEVED
    candidate set (already filtered by llm_infer.keep_candidate_supports); they
    are re-verified here through the same single audited firewall every other
    composer uses. Unlike the deterministic composers this never returns None:
    an observation the documents do not support is reported as NO_KB_REFERENCE
    rather than disappearing. No fallback to the requirement's own pre-authored
    citations -- those were not validated against this observation.
    """
    verified = _verified_citations(
        [Citation(clause_id=s.clause_id, quote=s.quote) for s in supports], store
    )
    return Finding(
        finding_type="inferred_gap",
        severity=_axis_level(requirement, observation.axis),
        condition=observation.condition,
        axis=observation.axis,
        evidence_excerpt=observation.note_quote,
        recommendation=_recommendation_for(requirement, observation.axis),
        citations=tuple(verified),
        dedupe_key=f"{observation.condition}|{observation.axis}",
        kb_status=KB_SUPPORTED if verified else NO_KB_REFERENCE,
    )


def _axis_level(requirement: DiagnosisRequirement, axis: str) -> str:
    for rule in requirement.axes:
        if rule.axis == axis:
            return "required" if rule.level == "required" else "recommended"
    return "recommended"


def _recommendation_for(requirement: DiagnosisRequirement, axis: str) -> str:
    """Axis-level query text when the requirement authors one, else the
    condition-level text. Without this a multi-axis condition prints the same
    sentence for every axis -- so a UTI "missing site" finding asked the
    clinician to document the causative organism the note already named."""
    for rule in requirement.axes:
        if rule.axis == axis and rule.recommendation:
            return rule.recommendation
    return requirement.recommendation


def compose_provider_finding(
    condition: str,
    evidence_excerpt: str,
    rule: "ProviderRule",
    store: ClauseStore,
) -> Finding | None:
    """A diagnosis recorded only by an author role whose documentation is not
    sufficient on its own. Routes through the same citation firewall as every
    other finding type -- no verified citation, no finding."""
    verified = _verified_citations(rule.citations, store)
    if not verified:
        return None
    return Finding(
        finding_type="provider_confirmation",
        severity="required" if rule.level == "required" else "recommended",
        condition=condition,
        axis="provider_confirmation",
        evidence_excerpt=evidence_excerpt,
        recommendation=rule.recommendation,
        citations=tuple(verified),
        dedupe_key=f"{condition}|provider_confirmation",
    )


def compose_integrity_finding(
    rule: "IntegrityRule",
    condition: str,
    axis: str,
    evidence_excerpt: str,
    store: ClauseStore,
) -> Finding | None:
    """A note-level or cross-statement integrity finding (copy-forward, conflicting
    documentation). Same citation firewall as every other composer: no verified
    citation, no finding."""
    verified = _verified_citations(rule.citations, store)
    if not verified:
        return None
    return Finding(
        finding_type=rule.kind,
        severity="required" if rule.level == "required" else "recommended",
        condition=condition,
        axis=axis,
        evidence_excerpt=evidence_excerpt,
        recommendation=rule.recommendation,
        citations=tuple(verified),
        dedupe_key=f"{condition}|{axis}",
    )


def compose_element_finding(doc_type: str, element: Element, store: ClauseStore) -> Finding | None:
    verified = _verified_citations(element.citations, store)
    if not verified:
        return None
    return Finding(
        finding_type="completeness_gap",
        severity="required" if element.level == "required" else "recommended",
        condition=doc_type,
        axis=element.name,
        evidence_excerpt=f"{doc_type} (element not found)",
        recommendation=element.recommendation,
        citations=tuple(verified),
        dedupe_key=f"{doc_type}|{element.name}",
    )


def compose_necessity_finding(gap: NecessityGap, store: ClauseStore) -> Finding | None:
    verified = _verified_citations(gap.rule.citations, store)
    if not verified:
        return None
    return Finding(
        finding_type="necessity_mismatch",
        severity=gap.rule.level,
        condition=gap.rule.order,
        axis="indication",
        evidence_excerpt=gap.evidence_excerpt,
        recommendation=gap.rule.recommendation,
        citations=tuple(verified),
        dedupe_key=f"necessity|{gap.rule.order}",
    )
