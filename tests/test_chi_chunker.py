from cdi_kb import config
from cdi_kb.chi_chunker import chunk_chi
from cdi_kb.extract import PageText, extract_pages
from cdi_kb.normalize import normalize

NL = chr(10)


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


# --- letter-spaced running headers (step 4) --------------------------------
# De-fusing the journal-typeset CHI PDFs exposed their running headers, which
# these journals set with wide letter spacing: "J A C C V O L . 7 9 , N O . 1 7".
# _is_heading counted each single character as a capitalised word, so 142 CHI-HF
# clauses took a running header as their section_title -- and section_title is
# weighted 5x in the FTS index, so that junk actively displaced real clauses from
# retrieval. Reach fell from 31/37 axes to 29/37 on the rebuild.

def test_letter_spaced_running_header_is_not_a_heading():
    from cdi_kb.chi_chunker import _is_heading

    assert not _is_heading("J A C C V O L . 7 9 , N O . 1 7 , 2 0 2 2 Heidenreich et al")
    assert not _is_heading("M A Y 3 , 2 0 2 2 : e 2 6 3 – e 4 2 1")


def test_real_headings_are_still_detected():
    from cdi_kb.chi_chunker import _is_heading

    assert _is_heading("2.2. Classification of HF by Left Ventricular Ejection Fraction")
    assert _is_heading("STAGING OF CKD")
    assert _is_heading("Classification of HF by LVEF")
    # A genuine short acronym heading must survive the letter-spacing guard.
    assert _is_heading("CKD and Cardiovascular Disease")


def test_no_clause_takes_a_letter_spaced_header_as_its_section_title():
    import re

    spaced = re.compile(r"(?:\b[A-Za-z]\b[ .,]){4,}")
    offenders = [c.clause_id for c in _clauses("CHI-HF") if spaced.search(c.section_title)]
    assert not offenders, f"{len(offenders)} clauses titled by a running header, e.g. {offenders[:3]}"


# --- repeating page furniture (step 4) -------------------------------------
# The letter-spaced-header guard above only caught one FORM of page furniture.
# CHI-CKD's running footer ("Kidney International Supplements (2013) 3, 73-90")
# is ordinary spaced text that passes every heading test, so it became the
# section_title of dozens of clauses -- and section_title is weighted 5x in FTS,
# so those clauses outranked the real governing clause for "acute kidney injury
# onset". The general property: a line repeated across many pages is furniture,
# whatever its typography.

def test_repeating_lines_are_detected_as_page_furniture():
    from cdi_kb.chi_chunker import repeating_lines
    from cdi_kb.extract import PageText

    # The mid-page line must be genuinely mid-page: only the first and last two
    # non-empty lines of each page are candidates for furniture.
    pages = [PageText(page_number=n, text=f"Journal Footer 2013{NL}alpha {n}{NL}"
                                          f"Unique body line {n}{NL}beta {n}{NL}gamma {n}{NL}")
             for n in range(1, 31)]
    furniture = repeating_lines(pages)
    assert any("journal footer" in f for f in furniture)
    assert not any("unique body line" in f for f in furniture)


def test_a_heading_that_appears_on_one_page_only_is_not_furniture():
    from cdi_kb.chi_chunker import repeating_lines
    from cdi_kb.extract import PageText

    pages = [PageText(page_number=n, text=f"Head{NL}Body {n}{NL}More {n}{NL}Foot{NL}")
             for n in range(1, 31)]
    pages.append(PageText(page_number=31, text=f"Head{NL}STAGING OF CKD{NL}Body 31{NL}Foot{NL}"))
    assert not any("staging of ckd" in f for f in repeating_lines(pages))


def test_running_footer_is_almost_never_a_section_title():
    """300 -> 7 of 631 CHI-CKD clauses.

    The residual seven are front-matter footers whose page label is a ROMAN
    numeral ("Kidney International Supplements (2013) 3, xiii xiii"). _line_shape
    collapses digit runs, not roman numerals, so each variant appears on only one
    or two pages and repetition cannot see it. That is an inherent limit of a
    frequency-based filter, not a bug: collapsing roman numerals would mean
    treating standalone "i", "c", "d", "x" and "mix" as page labels, which risks
    flagging real headings. Seven front-matter clauses, still indexed at 1x on
    their body text, is the cheaper trade.
    """
    offenders = [c.clause_id for c in _clauses("CHI-CKD")
                 if "Kidney International Supplements" in c.section_title]
    assert len(offenders) <= 10, f"{len(offenders)} footer-titled clauses: {offenders[:5]}"


def test_real_ckd_headings_survive_the_furniture_filter():
    titles = {c.section_title for c in _clauses("CHI-CKD")}
    assert any("STAGING OF CKD" in t for t in titles), sorted(titles)[:10]
