from cdi_kb.normalize import QuoteMatch, find_quote, normalize


def test_normalize_collapses_whitespace_and_case() -> None:
    assert normalize("Chronic  Kidney\n Disease") == "chronic kidney disease"


def test_normalize_unifies_typographic_quotes_and_dashes() -> None:
    assert normalize("“stage” – 4") == '"stage" - 4'


def test_find_quote_exact_substring() -> None:
    match = find_quote("Stage 1 through to 5", "A disease may be described as Stage 1 through to 5.")
    assert match == QuoteMatch(found=True, score=1.0)


def test_find_quote_tolerates_small_ocr_noise() -> None:
    source = "results should be confirmed by repeat testing in the patient record"
    quote = "results should be confirmed by repeat testing in the patient records"
    match = find_quote(quote, source)
    assert match.found and match.score >= 0.95


def test_find_quote_rejects_fabrication() -> None:
    match = find_quote("document the CKD stage using eGFR", "the quick brown fox jumps over the lazy dog")
    assert not match.found


def test_find_quote_empty_quote_is_not_found() -> None:
    assert not find_quote("", "anything").found
