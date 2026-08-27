"""Audit orchestration: note text -> gaps -> citation-verified findings."""

from dataclasses import dataclass, field

from cdi_kb import config
from cdi_kb.clauses import ClauseStore
from cdi_kb.findings import Finding, compose_finding
from cdi_kb.gapcheck import find_gaps
from cdi_kb.requirements_model import load_requirements


@dataclass
class AuditResult:
    findings: list[Finding] = field(default_factory=list)
    dropped_citations: list[str] = field(default_factory=list)


def run_audit(note_text: str) -> AuditResult:
    if not note_text.strip():
        return AuditResult()
    requirements = load_requirements(config.REQUIREMENTS_DIR)
    by_condition = {req.condition: req for req in requirements}
    store = ClauseStore(config.KB_DB)
    result = AuditResult()
    for gap in find_gaps(note_text, requirements):
        finding = compose_finding(gap, by_condition[gap.condition], store)
        if finding is None:
            result.dropped_citations.append(f"{gap.condition}|{gap.axis}")
        else:
            result.findings.append(finding)
    store.close()
    return result
