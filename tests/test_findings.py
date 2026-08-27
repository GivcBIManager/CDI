from pathlib import Path

from cdi_kb.clauses import Clause, ClauseStore
from cdi_kb.findings import compose_finding
from cdi_kb.gapcheck import ConditionMention, Gap
from cdi_kb.requirements_model import AxisRule, Citation, DiagnosisRequirement

CLAUSE = Clause("CDI-2021/staging/p1", "Staging", 62,
                "A disease may be described as Stage 1 through to 5.")
MENTION = ConditionMention("chronic kidney disease", "CKD", 12, 15, negated=False)
GAP = Gap("chronic kidney disease", "stage", "required", MENTION)


def _store(tmp_path: Path, clauses: list[Clause]) -> ClauseStore:
    store = ClauseStore(tmp_path / "kb.sqlite")
    store.rebuild(clauses)
    return store


def _req(quote: str) -> DiagnosisRequirement:
    return DiagnosisRequirement(
        condition="chronic kidney disease", synonyms=["CKD"],
        axes=[AxisRule(axis="stage", level="required", evidence_terms=["stage 4"])],
        recommendation="Please document the stage, if known.",
        citations=[Citation(clause_id="CDI-2021/staging/p1", quote=quote)],
    )


def test_verified_citation_produces_finding(tmp_path) -> None:
    finding = compose_finding(GAP, _req("Stage 1 through to 5"), _store(tmp_path, [CLAUSE]))
    assert finding is not None
    assert finding.severity == "required"
    assert finding.citations[0].clause_id == "CDI-2021/staging/p1"
    assert finding.dedupe_key == "chronic kidney disease|stage"


def test_fabricated_quote_yields_no_finding(tmp_path) -> None:
    # The firewall: a quote not in the clause text must kill the finding entirely.
    finding = compose_finding(GAP, _req("clinicians must always record the stage"), _store(tmp_path, [CLAUSE]))
    assert finding is None


def test_unresolvable_clause_id_yields_no_finding(tmp_path) -> None:
    finding = compose_finding(GAP, _req("Stage 1 through to 5"), _store(tmp_path, []))
    assert finding is None
