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
