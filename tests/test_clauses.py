from cdi_kb import config
from cdi_kb.clauses import ClauseStore, chunk_booklet, parse_toc, slugify
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
