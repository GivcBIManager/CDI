"""Audit orchestration: note text -> gaps -> citation-verified findings."""

from dataclasses import dataclass, field

from cdi_kb import config
from cdi_kb.clauses import ClauseStore
from cdi_kb.findings import Finding, compose_finding
from cdi_kb.gapcheck import ConditionMention, Gap, detect_conditions, find_gaps, scan_axes
from cdi_kb.requirements_model import DiagnosisRequirement, load_requirements


@dataclass
class AuditResult:
    findings: list[Finding] = field(default_factory=list)
    dropped_citations: list[str] = field(default_factory=list)


def _named_conditions(
    note_text: str,
    requirements: list[DiagnosisRequirement],
    result: AuditResult,
) -> set[str]:
    """Conditions already named in the note or already surfaced as findings/dropped
    citations. Structural (re-detects mentions in note_text), not just derived from
    findings/dropped keys, so a NAMED-BUT-NEGATED condition (e.g. "No sepsis.") is
    still excluded from LLM-inferred implicits -- which hardcode negated=False by
    design and would otherwise emit a clinically false finding for it."""
    return ({m.condition for m in detect_conditions(note_text, requirements)} |
            {f.dedupe_key.split("|")[0] for f in result.findings} |
            {d.split("|")[0] for d in result.dropped_citations})


def _inferred_findings(
    implicits: list[tuple[str, str]],
    note_text: str,
    by_condition: dict[str, DiagnosisRequirement],
    store: ClauseStore,
    already_named: set[str],
) -> tuple[list[Finding], list[str]]:
    """(condition, evidence) pairs from inference -> findings via the same firewall.
    Axis evidence is scanned against the ORIGINAL note only; detection is the
    inference itself, so find_gaps (and its negation window) is bypassed."""
    findings: list[Finding] = []
    dropped: list[str] = []
    processed: set[str] = set(already_named)
    for condition, evidence in implicits:
        if condition in processed or condition not in by_condition:
            continue
        processed.add(condition)
        req = by_condition[condition]
        present = scan_axes(note_text, req)
        mention = ConditionMention(condition=condition, matched_text=evidence[:120], start=0, end=0, negated=False)
        for rule in req.axes:
            if rule.axis in present:
                continue
            finding = compose_finding(Gap(condition=condition, axis=rule.axis, level=rule.level, mention=mention), req, store)
            if finding is None:
                dropped.append(f"{condition}|{rule.axis}")
            else:
                findings.append(finding)
    return findings, dropped


def run_audit(note_text: str, *, use_llm: bool = False) -> AuditResult:
    if not note_text.strip():
        return AuditResult()
    requirements = load_requirements(config.REQUIREMENTS_DIR)
    by_condition = {req.condition: req for req in requirements}
    store = ClauseStore(config.KB_DB)
    result = AuditResult()
    try:
        for gap in find_gaps(note_text, requirements):
            finding = compose_finding(gap, by_condition[gap.condition], store)
            if finding is None:
                result.dropped_citations.append(f"{gap.condition}|{gap.axis}")
            else:
                result.findings.append(finding)

        if use_llm:
            # inline import: keeps offline path free of the anthropic dependency
            from cdi_kb.llm_infer import infer_implicit_conditions
            already_named = _named_conditions(note_text, requirements, result)
            implicits = infer_implicit_conditions(note_text, tuple(by_condition))
            new_findings, new_dropped = _inferred_findings(
                [(f.condition, f.evidence) for f in implicits],
                note_text, by_condition, store, already_named,
            )
            result.findings.extend(new_findings)
            result.dropped_citations.extend(new_dropped)
    finally:
        store.close()
    return result
