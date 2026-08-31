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


# --- word fusion (step 4) ---------------------------------------------------
# pdfplumber's default x_tolerance=3 is too coarse for the two journal-typeset
# CHI guidelines: words ran together into single tokens
# ("TheclassificationforbaselineandsubsequentLVEFisshown"), which the FTS index
# then stored as ONE term matching no condition or axis word. 48% of the KB's
# clauses were affected and six requirement axes could not reach their own
# governing clause.

import json
import re

import pytest

_FUSED = re.compile(r"[A-Za-z][A-Za-z]{24,}")  # a 25+ character alphabetic run


def _fused_runs(pages) -> list[str]:
    return [run for page in pages for run in _FUSED.findall(page.text)]


# Measured over every page of each document, default setting vs the tuned one.
# CHI-CKD's residue is NOT fusion the tolerance can fix: those runs are rotated
# table headers in KDIGO's landscape tables, which pdfplumber emits character by
# character in reverse reading order -- "deyassaerewydutSDRDMmorfselpmaS" is
# "Samples from MDRD Study were reassayed" backwards. Table furniture, not prose;
# no requirement axis cites it. Fixing it means dropping non-upright characters,
# a separate change with its own blast radius.
_MAX_FUSED_RUNS = {
    "CHI-HF": 50,     # 5143 -> 10
    "CHI-CKD": 300,   # 3209 -> 238, all rotated-table artifacts
}


@pytest.mark.parametrize("source_id", sorted(_MAX_FUSED_RUNS))
def test_journal_typeset_guidelines_extract_without_fused_words(source_id) -> None:
    pages = extract_pages(config.SOURCES[source_id].path, config.RAW_TEXT_DIR)
    runs = _fused_runs(pages)
    assert len(runs) < _MAX_FUSED_RUNS[source_id], (
        f"{source_id}: {len(runs)} fused runs, e.g. {runs[:5]}"
    )


def test_heart_failure_classification_heading_has_word_spaces() -> None:
    pages = extract_pages(config.SOURCES["CHI-HF"].path, config.RAW_TEXT_DIR)
    full = " ".join(p.text for p in pages)
    assert "Classification of HF by LVEF" in full


@pytest.mark.parametrize("source_id", ["CDI-2021", "CHI-STROKE", "CHI-ANEMIA", "CHI-LRTI",
                                       "CHI-BARIATRIC", "CHI-NEC-B12"])
def test_already_clean_sources_gain_no_fused_words(source_id) -> None:
    """Regression guard. A finer tolerance can over-split words as easily as the
    coarse one fused them, so it must not degrade a source that was already
    extracting correctly.

    Measured full-document, default vs tuned: seven of the nine clean sources are
    byte-identical, and the two that differ do so on exactly one page each, both
    harmless -- CDI-2021 p.15 gains a MISSING space ("capability -need to" ->
    "capability - need to"), and CHI-STROKE p.19 is a rotated figure label that
    is unreadable under either setting ("R e h a b ilit a t io n" ->
    "R e h a b i l i t a t i o n"). No body prose changes anywhere.
    """
    pages = extract_pages(config.SOURCES[source_id].path, config.RAW_TEXT_DIR)
    runs = _fused_runs(pages)
    assert len(runs) <= 1, f"{source_id} gained fused runs: {runs[:5]}"


def test_booklet_page_15_gains_the_missing_space() -> None:
    # The one body-text change the new setting makes to an already-clean source,
    # pinned so it is a recorded improvement rather than an unexplained drift.
    pages = extract_pages(config.BOOKLET_PDF, config.RAW_TEXT_DIR)
    full = " ".join(p.text for p in pages)
    assert "capability - need to" in full


def test_cache_key_encodes_the_extraction_settings(tmp_path, monkeypatch) -> None:
    """A cached page dump written under different extraction settings must not
    be reused. The cache was keyed on the PDF stem alone, so changing the
    tolerance would have silently kept serving the fused text forever -- and
    var/ is gitignored, so nobody would have seen a stale file to delete."""
    from cdi_kb import extract as extract_module

    pdf = config.SOURCES["CHI-LRTI"].path
    extract_pages(pdf, tmp_path)
    before = {p.name for p in tmp_path.glob("*.json")}
    assert len(before) == 1

    monkeypatch.setattr(extract_module, "TEXT_EXTRACTION_KWARGS", {"x_tolerance_ratio": 0.99})
    extract_pages(pdf, tmp_path)
    after = {p.name for p in tmp_path.glob("*.json")}
    assert len(after) == 2, f"settings change reused the cache: {after}"


def test_cache_roundtrips_the_extracted_text(tmp_path) -> None:
    pdf = config.SOURCES["CHI-LRTI"].path
    first = extract_pages(pdf, tmp_path)
    cache_file = next(tmp_path.glob("*.json"))
    assert json.loads(cache_file.read_text(encoding="utf-8"))
    assert extract_pages(pdf, tmp_path) == first
