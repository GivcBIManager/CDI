from cdi_kb import config
from cdi_kb.extract import extract_pages
from cdi_kb.normalize import normalize


def test_booklet_extracts_substantial_text() -> None:
    pages = extract_pages(config.BOOKLET_PDF, config.RAW_TEXT_DIR)
    assert len(pages) > 100
    total = sum(len(p.text) for p in pages)
    assert total > 300_000, f"expected >300K chars (corpus analysis measured ~368K), got {total}"


def test_known_sentence_present() -> None:
    # Verbatim from the Documenting for Specificity chapter (verified during corpus analysis).
    pages = extract_pages(config.BOOKLET_PDF, config.RAW_TEXT_DIR)
    full = normalize(" ".join(p.text for p in pages))
    assert "type, stage, agent, onset or causative factors and site" in full


def test_cache_is_used_on_second_call(tmp_path) -> None:
    first = extract_pages(config.BOOKLET_PDF, tmp_path)
    cache_files = list(tmp_path.glob("*.json"))
    assert len(cache_files) == 1
    second = extract_pages(config.BOOKLET_PDF, tmp_path)
    assert first == second
