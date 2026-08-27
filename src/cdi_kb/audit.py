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
            named = {gap_key.split("|")[0] for gap_key in
                     {f.dedupe_key for f in result.findings} | set(result.dropped_citations)}
            for implicit in infer_implicit_conditions(note_text, tuple(by_condition)):
                req = by_condition[implicit.condition]
                if implicit.condition in named:
                    continue
                synthetic_note = f"{note_text}\n[assessment: {implicit.condition}]"
                for gap in find_gaps(synthetic_note, [req]):
                    finding = compose_finding(gap, req, store)
                    if finding is not None:
                        result.findings.append(finding)
    finally:
        store.close()
    return result
