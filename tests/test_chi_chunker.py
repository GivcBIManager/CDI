from cdi_kb import config
from cdi_kb.chi_chunker import chunk_chi
from cdi_kb.extract import PageText, extract_pages
from cdi_kb.normalize import normalize


def _clauses(source_id):
    source = config.SOURCES[source_id]
    return chunk_chi(extract_pages(source.path, config.RAW_TEXT_DIR), source)


def test_anemia_chunks_have_page_anchored_ids():
    clauses = _clauses("CHI-ANEMIA")
    assert len(clauses) > 10
    assert all(c.clause_id.startswith("CHI-ANEMIA/pg") for c in clauses)
    for c in clauses:
        parts = c.clause_id.split("/")
        assert parts[1].startswith("pg") and parts[2].startswith("p")
    first = clauses[0].clause_id
    assert first.split("/")[1].startswith("pg") and first.split("/")[2].startswith("p")


def test_ids_unique_and_stable():
    clauses = _clauses("CHI-ANEMIA")
    ids = [c.clause_id for c in clauses]
    assert len(ids) == len(set(ids))
    assert ids == [c.clause_id for c in _clauses("CHI-ANEMIA")]


def test_heading_becomes_section_title():
    clauses = _clauses("CHI-STROKE")
    titles = {c.section_title for c in clauses}
    assert len(titles) > 3  # heading heuristic found real sections, not one blob


def test_necessity_doc_extracts():
    clauses = _clauses("CHI-NEC-HBA1C")
    assert len(clauses) >= 3


def test_false_heading_line_splits_but_stays_contiguous():
    # A Title-Case line that trips the heading heuristic mid-sentence must not
    # splice the sentence across it: both halves are emitted as separate
    # clauses, and each clause text is still a contiguous substring of the raw
    # page text. The false heading here has NO period on the line before it
    # and NO capitalized word on the line after it, so the pre-fix chunker
    # (which only breaks a paragraph on a period followed by a capitalized
    # next line) does NOT split there either -- it merges the surrounding
    # lines into one spliced paragraph that skips the removed heading text
    # entirely, which is exactly the bug this test proves is fixed.
    before = (
        "Iron deficiency anaemia may result from chronic blood loss due to "
        "prolonged gastrointestinal bleeding that goes unrecognized for weeks"
    )
    heading = "Clinical Pathway Update"
    after_a = (
        "or malabsorption during long-term treatment with proton pump "
        "inhibitors or other acid-suppressing medications commonly prescribed"
    )
    after_b = (
        "that reduce gastric acid secretion and impair enteral iron "
        "absorption in affected patients over time."
    )
    page_text = before + "\n" + heading + "\n" + after_a + "\n" + after_b + "\n"
    page = PageText(page_number=1, text=page_text)
    source = config.SOURCES["CHI-ANEMIA"]
    fake_source = type(source)(
        source_id="TEST-SRC", path=source.path, title="Test Source",
        authority=source.authority, genre=source.genre,
    )

    clauses = chunk_chi([page], fake_source)

    assert len(clauses) == 2
    normalized_page = normalize(page_text)
    for clause in clauses:
        assert normalize(clause.text) in normalized_page
    assert clauses[0].section_title == "Test Source"
    assert clauses[1].section_title == "Clinical Pathway Update"
