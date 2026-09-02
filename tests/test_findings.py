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


def test_recommended_severity_branch(tmp_path) -> None:
    # Exercise the recommended-severity branch (level != "required")
    gap = Gap("chronic kidney disease", "stage", "recommended", MENTION)
    finding = compose_finding(gap, _req("Stage 1 through to 5"), _store(tmp_path, [CLAUSE]))
    assert finding is not None
    assert finding.severity == "recommended"


def test_citations_are_ordered_moh_then_chi_then_booklet(tmp_path) -> None:
    # MOH is the national regulator, CHI the insurance/quality authority, and
    # CDI-2021 the coding-education booklet. A clinician reading a finding
    # should meet the strongest authority first.
    clauses = [
        Clause("CDI-2021/staging/p1", "Staging", 62, "A disease may be described as Stage 1 through to 5."),
        Clause("CHI-CKD/pg9/p2", "Staging of CKD", 9, "CKD is staged by GFR category G1 to G5."),
        Clause("MOH-HD/pg4/p1", "Staging", 4, "Document the CKD stage at every dialysis review."),
    ]
    requirement = DiagnosisRequirement(
        condition="chronic kidney disease", synonyms=["CKD"],
        axes=[AxisRule(axis="stage", level="required", evidence_terms=["stage 4"])],
        recommendation="Please document the stage, if known.",
        citations=[
            Citation(clause_id="CDI-2021/staging/p1", quote="Stage 1 through to 5"),
            Citation(clause_id="CHI-CKD/pg9/p2", quote="staged by GFR category"),
            Citation(clause_id="MOH-HD/pg4/p1", quote="Document the CKD stage"),
        ],
    )
    finding = compose_finding(GAP, requirement, _store(tmp_path, clauses))
    assert finding is not None
    assert [c.authority for c in finding.citations] == ["MOH", "CHI", "TCC"]
    assert [c.clause_id for c in finding.citations] == [
        "MOH-HD/pg4/p1", "CHI-CKD/pg9/p2", "CDI-2021/staging/p1",
    ]


def test_same_authority_citations_keep_their_authored_order(tmp_path) -> None:
    # Stable sort on rank alone: an author who lists a primary quote first must
    # see it stay first.
    clauses = [
        Clause("CHI-CKD/pg9/p2", "Staging of CKD", 9, "CKD is staged by GFR category G1 to G5."),
        Clause("CHI-CKD/pg9/p3", "Staging of CKD", 9, "Albuminuria categories A1 to A3 refine the stage."),
    ]
    requirement = DiagnosisRequirement(
        condition="chronic kidney disease", synonyms=["CKD"],
        axes=[AxisRule(axis="stage", level="required", evidence_terms=["stage 4"])],
        recommendation="Please document the stage, if known.",
        citations=[
            Citation(clause_id="CHI-CKD/pg9/p3", quote="Albuminuria categories A1 to A3"),
            Citation(clause_id="CHI-CKD/pg9/p2", quote="staged by GFR category"),
        ],
    )
    finding = compose_finding(GAP, requirement, _store(tmp_path, clauses))
    assert finding is not None
    assert [c.clause_id for c in finding.citations] == ["CHI-CKD/pg9/p3", "CHI-CKD/pg9/p2"]
