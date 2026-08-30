from cdi_kb import config
from cdi_kb.chi_chunker import chunk_chi
from cdi_kb.extract import extract_pages


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
    """A Title-Case line that trips the heading heuristic mid-paragraph must not
    splice the paragraph across it: both halves are emitted as separate clauses,
    and each clause's text is still a contiguous substring of the raw page text.
    """
    from cdi_kb.extract import PageText
    from cdi_kb.normalize import normalize

    page_text = (
        "Correct anemia and monitor the patient closely for signs of continued blood loss "
        "or malabsorption during\n"
        "the treatment course before considering additional intervention options for this "
        "clinical presentation.\n"
        "Clinical Pathway Update\n"
        "Iron studies including serum ferritin and transferrin saturation should be checked "
        "at baseline and repeated\n"
        "after eight weeks of oral iron therapy to confirm an adequate hematologic response "
        "to treatment given.\n"
    )
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
