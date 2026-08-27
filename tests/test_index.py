from cdi_kb.clauses import Clause
from cdi_kb.index import SearchIndex

CLAUSES = [
    Clause("CDI-2021/chronic-kidney-disease-ckd/p1", "Chronic Kidney Disease (CKD)", 119,
           "Chronic kidney disease must be documented with its stage, based on eGFR."),
    Clause("CDI-2021/sepsis/p1", "Sepsis", 118,
           "Sepsis documentation requires the causative organism and any organ dysfunction."),
    Clause("CDI-2021/fractures/p1", "Fractures", 120,
           "Fracture documentation requires site, open or closed type, and mechanism."),
]


def _index(tmp_path) -> SearchIndex:
    index = SearchIndex(tmp_path / "kb.sqlite")
    index.rebuild(CLAUSES)
    return index


def test_search_ranks_matching_section_first(tmp_path) -> None:
    hits = _index(tmp_path).search("chronic kidney disease stage")
    assert hits and hits[0].clause_id == "CDI-2021/chronic-kidney-disease-ckd/p1"


def test_synonym_expansion_finds_full_name(tmp_path) -> None:
    hits = _index(tmp_path).search("CKD", expansions=["chronic kidney disease"])
    assert any(h.clause_id.startswith("CDI-2021/chronic-kidney-disease") for h in hits)


def test_query_with_fts_special_chars_does_not_raise(tmp_path) -> None:
    hits = _index(tmp_path).search('sepsis "organism" (severe) - shock?')
    assert isinstance(hits, list)


def test_limit_respected(tmp_path) -> None:
    assert len(_index(tmp_path).search("documentation", limit=2)) <= 2


def test_title_boost_weighting_discriminates(tmp_path) -> None:
    """Verify that 5x title weight actually ranks title-matches above body-heavy matches.

    Two clauses both contain "guideline": one only in title (body about implementation),
    one only in body with multiple mentions (title about procedures). Without title boost,
    the body-heavy clause would likely rank higher due to term frequency. With 5x boost,
    title-match must rank first.
    """
    clauses = [
        Clause("CDI-2021/guidelines/p1", "Clinical Documentation Guideline", 50,
               "Implementation procedures must follow best practices in coding and specificity."),
        Clause("CDI-2021/procedures/p1", "Procedures", 51,
               "Guideline documentation for guideline compliance requires guideline adherence and guideline updates."),
    ]
    index = SearchIndex(tmp_path / "kb.sqlite")
    index.rebuild(clauses)
    hits = index.search("guideline")
    assert hits and hits[0].clause_id == "CDI-2021/guidelines/p1", \
        f"Expected title-match to rank first, got {[h.clause_id for h in hits]}"
