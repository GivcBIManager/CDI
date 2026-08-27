from cdi_kb import config
from cdi_kb.clauses import ClauseStore, _split_paragraphs, chunk_booklet, parse_toc, slugify
from cdi_kb.extract import extract_pages
from cdi_kb.normalize import normalize


def _pages():
    return extract_pages(config.BOOKLET_PDF, config.RAW_TEXT_DIR)


def test_slugify() -> None:
    assert slugify("Chronic Kidney Disease (CKD)") == "chronic-kidney-disease-ckd"


def test_toc_finds_known_sections() -> None:
    titles = [entry.title for entry in parse_toc(_pages())]
    assert any("Documenting for Specificity" in t for t in titles)
    assert any("Chronic Kidney Disease" in t for t in titles)
    assert any("Sepsis" in t for t in titles)
    assert len(titles) > 100


def test_chunks_have_ids_and_specificity_text() -> None:
    clauses = chunk_booklet(_pages())
    assert len(clauses) > 200
    spec = [c for c in clauses if c.clause_id.startswith("CDI-2021/documenting-for-specificity/")]
    assert spec, "Documenting for Specificity section produced no clauses"
    joined = normalize(" ".join(c.text for c in spec))
    assert "type, stage, agent, onset" in joined


def test_store_roundtrip(tmp_path) -> None:
    clauses = chunk_booklet(_pages())
    store = ClauseStore(tmp_path / "kb.sqlite")
    store.rebuild(clauses)
    assert store.count() == len(clauses)
    first = clauses[0]
    fetched = store.get(first.clause_id)
    assert fetched is not None and fetched.text == first.text
    assert store.get("CDI-2021/no-such-section/p1") is None
    store.close()


def test_split_paragraphs_blank_line_separated() -> None:
    # (a) blank-line separation is preserved when the extractor happens to emit it.
    para_one = (
        "Paragraph one describes the purpose of clinical documentation improvement across the "
        "entire patient journey from admission to discharge today."
    )
    para_two = (
        "Paragraph two describes how coders rely on that documentation to assign accurate codes "
        "and capture case complexity for funding purposes."
    )
    text = f"{para_one}\n\n{para_two}"
    assert _split_paragraphs(text) == [para_one, para_two]


def test_split_paragraphs_sentence_boundary_fallback() -> None:
    # (b) no blank lines: a line ending in "." followed by a line starting with a
    # capital letter is treated as a genuine paragraph break.
    line0 = (
        "The clinical documentation improvement program aims to improve completeness and "
        "specificity across every patient encounter and medical record."
    )
    line1 = (
        "Coders rely on this specificity to assign accurate ICD-10 codes and capture case "
        "complexity appropriately for funding purposes today."
    )
    text = f"{line0}\n{line1}"
    assert _split_paragraphs(text) == [line0, line1]


def test_split_paragraphs_abbreviation_false_positive_documented() -> None:
    # (c) documents CURRENT (imperfect) behavior: the heuristic cannot distinguish a
    # real sentence end from an abbreviation like "Dr." that happens to end a line, so
    # it splits here even though this is a single sentence. This test locks down that
    # known limitation rather than pretending it doesn't exist.
    line0 = "In terms of clinical documentation, specificity refers to describing a range of condition"
    line1 = "attributes that help paint a complete picture of the patient's condition, particularly when"
    line2 = "consulting with Dr."
    line3 = "Nguyen who specializes in nephrology and chronic kidney disease management across the entire"
    line4 = "unit for post-operative review and long term monitoring of renal function today."
    text = "\n".join([line0, line1, line2, line3, line4])
    result = _split_paragraphs(text)
    assert len(result) == 2
    assert result[0] == "\n".join([line0, line1, line2])
    assert result[0].endswith("Dr.")  # wrongly treated as a sentence end
    assert result[1] == "\n".join([line3, line4])
    assert result[1].startswith("Nguyen")


def test_split_paragraphs_empty_and_whitespace_only() -> None:
    # (d) empty or whitespace-only sections produce no clauses, not a crash.
    assert _split_paragraphs("") == []
    assert _split_paragraphs("   \n\t  \n  ") == []
