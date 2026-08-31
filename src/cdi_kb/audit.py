"""Audit orchestration: note text -> gaps -> citation-verified findings."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from cdi_kb import config
from cdi_kb.clauses import ClauseStore
from cdi_kb.doc_gaps import find_element_gaps
from cdi_kb.doctype import detect_doc_type
from cdi_kb.findings import (
    Finding, compose_element_finding, compose_finding, compose_inferred_finding, compose_necessity_finding,
)
from cdi_kb.gapcheck import detect_conditions, find_gaps, rule_applies
from cdi_kb.index import SearchIndex
from cdi_kb.necessity import find_necessity_gaps
from cdi_kb.requirements_model import (
    DOC_TYPES, DiagnosisRequirement, DocType, load_doc_requirements, load_necessity_rules, load_requirements,
)

if TYPE_CHECKING:  # annotation-only: keeps the offline path free of anthropic
    from cdi_kb.llm_infer import ValidatedObservation

# Injection seam for the LLM stage: (note_text, requirements, index) -> validated
# observations. Tests supply a deterministic stage; production defaults to
# llm_infer.run_llm_stage.
LlmStage = Callable[[str, list[DiagnosisRequirement], SearchIndex], list["ValidatedObservation"]]


@dataclass
class AuditResult:
    findings: list[Finding] = field(default_factory=list)
    dropped_citations: list[str] = field(default_factory=list)
    active_doc_type: str = "any"
    # Set when the optional LLM stage failed. The deterministic findings are
    # still returned: an inference failure must never discard work already in
    # hand, and must never take the audit down (it did, on 6 of 9 runs against
    # a long real note, before this was wrapped).
    llm_error: str | None = None


def _fully_negated_conditions(
    note_text: str,
    requirements: list[DiagnosisRequirement],
) -> set[str]:
    """Conditions EVERY mention of which is negated (e.g. a note whose only
    reference is "No evidence of sepsis").

    This replaces the former blanket already-named gate. That gate excluded the
    LLM from every condition the note mentioned at all, which is where the string
    scanner's worst misses live: gapcheck.scan_axes searches the whole note, so an
    organism named in a culture result marks a named condition's `agent` axis
    satisfied even though the note never draws the link the booklet asks for. Only
    the model can see that, and it was forbidden from looking.

    What the gate genuinely protected is narrower and kept here: observations carry
    no negation flag (compose_inferred_finding has nothing to set one from), so a
    condition the note explicitly rules out must be filtered by the audit rather
    than trusted to the model. "Every mention negated", not "any mention negated" --
    "No sepsis on admission. Day 3: now in septic shock" is ordinary progress-note
    narrative, and suppressing it would lose a real finding.
    """
    mentions: dict[str, list[bool]] = {}
    for mention in detect_conditions(note_text, requirements):
        mentions.setdefault(mention.condition, []).append(mention.negated)
    return {condition for condition, flags in mentions.items() if all(flags)}


def _validated_findings(
    validated: list["ValidatedObservation"],
    note_text: str,
    by_condition: dict[str, DiagnosisRequirement],
    store: ClauseStore,
    negated_conditions: set[str],
    existing_keys: set[str],
    doc_type: str = "any",
) -> list[Finding]:
    """KB-validated observations -> findings.

    The axis decision is the MODEL's, not scan_axes': the deterministic scanner
    searches the whole note, so a term belonging to a different problem silently
    satisfies an axis it has nothing to do with (an organism named in a culture
    result marked sepsis's `agent` axis satisfied, suppressing the query). The
    model judges the axis against the statement that actually concerns the
    condition, which is the whole point of paying for this stage.

    keep_grounded is re-applied here, not just inside the stage, so the note-side
    firewall holds for ANY injected stage -- it cannot be bypassed by swapping
    the inference implementation.
    """
    from cdi_kb.llm_infer import keep_grounded

    findings: list[Finding] = []
    seen: set[str] = set()
    grounded = {
        (o.condition, o.axis, o.note_quote)
        for o in keep_grounded([v.observation for v in validated], note_text, by_condition)
    }
    seen |= set(existing_keys)
    for entry in validated:
        observation = entry.observation
        if observation.condition in negated_conditions:
            continue
        if (observation.condition, observation.axis, observation.note_quote) not in grounded:
            continue
        requirement = by_condition[observation.condition]
        rule = next((r for r in requirement.axes if r.axis == observation.axis), None)
        if rule is None or not rule_applies(rule, doc_type):
            continue
        key = f"{observation.condition}|{observation.axis}"
        if key in seen:
            continue
        seen.add(key)
        findings.append(compose_inferred_finding(observation, requirement, entry.supports, store))
    return findings


def run_audit(
    note_text: str,
    *,
    doc_type: DocType | None = None,
    use_llm: bool = False,
    llm_stage: "LlmStage | None" = None,
) -> AuditResult:
    # Defense in depth: doc_type must be a concrete DOC_TYPES value or None
    # (auto-detect), even for callers that bypass the FastAPI/CLI validated
    # entry points (e.g. reflected-XSS-style arbitrary strings). "any" is the
    # internal auto-detect fallback value, never a valid explicit override.
    if doc_type is not None and doc_type not in DOC_TYPES:
        raise ValueError(
            f"doc_type must be one of {DOC_TYPES} or None (auto-detect), got {doc_type!r}"
        )
    # Requirements are loaded BEFORE doc-type resolution (and passed into it) so
    # the diagnosis-list shape heuristic's known-condition-term check is active;
    # doc_type itself is still resolved BEFORE the empty-note early return: an
    # explicit caller override must always win, even over an empty note (whose
    # auto-detected value would otherwise be "any").
    requirements = load_requirements(config.REQUIREMENTS_DIR)
    resolved_doc_type: str = doc_type if doc_type is not None else detect_doc_type(note_text, requirements)
    if not note_text.strip():
        return AuditResult(active_doc_type=resolved_doc_type)
    by_condition = {req.condition: req for req in requirements}
    doc_requirements = load_doc_requirements(config.DOC_REQUIREMENTS_DIR)
    necessity_rules = load_necessity_rules(config.NECESSITY_DIR)
    store = ClauseStore(config.KB_DB)
    result = AuditResult(active_doc_type=resolved_doc_type)
    try:
        for gap in find_gaps(note_text, requirements, doc_type=resolved_doc_type):
            finding = compose_finding(gap, by_condition[gap.condition], store)
            if finding is None:
                result.dropped_citations.append(f"{gap.condition}|{gap.axis}")
            else:
                result.findings.append(finding)

        for gap in find_necessity_gaps(note_text, necessity_rules):
            finding = compose_necessity_finding(gap, store)
            if finding is None:
                result.dropped_citations.append(f"necessity|{gap.rule.order}")
            else:
                result.findings.append(finding)

        doc_req = doc_requirements.get(resolved_doc_type)
        if resolved_doc_type != "any" and doc_req is not None:
            for element in find_element_gaps(note_text, doc_req):
                finding = compose_element_finding(resolved_doc_type, element, store)
                if finding is None:
                    result.dropped_citations.append(f"{resolved_doc_type}|{element.name}")
                else:
                    result.findings.append(finding)

        if use_llm:
            negated = _fully_negated_conditions(note_text, requirements)
            # Only keys the deterministic pass actually EMITTED. A dropped
            # citation raised nothing, so the LLM path re-reaching that axis by
            # retrieval is new authority, not a duplicate.
            existing_keys = {f.dedupe_key for f in result.findings}
            index = SearchIndex(config.KB_DB)
            try:
                stage = llm_stage
                if stage is None:
                    # inline import: keeps the offline path free of the anthropic dependency
                    from cdi_kb.llm_infer import run_llm_stage
                    stage = run_llm_stage
                result.findings.extend(_validated_findings(
                    stage(note_text, requirements, index),
                    note_text, by_condition, store, negated, existing_keys,
                    doc_type=resolved_doc_type,
                ))
            except Exception as error:  # noqa: BLE001 - the stage must never take the audit down
                result.llm_error = f"{type(error).__name__}: {error}"
            finally:
                index.close()
    finally:
        store.close()
    return result
