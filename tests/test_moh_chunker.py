"""MOH heading rejectors: every string below is a real line from the corpus."""

from cdi_kb import config
from cdi_kb.extract import extract_pages
from cdi_kb.moh_chunker import (
    _is_abbreviation_gloss, _is_bullet_item, _is_colon_heading, _is_datestamp,
    _is_moh_heading, chunk_moh,
)

# Junk that the CHI predicate accepts as a heading and MOH must reject. Each is
# a verbatim line from MOH_Protocols/ (occurrence counts across the curated 31:
# bullet-led 110, abbreviation-gloss 49, datestamp 7).
MUST_REJECT = [
    "• Perform ECG",
    "• Enoxaparin 40mg SC once daily If CrCl < 30ml/min,",
    "TMP/SMZ SS: Trimethoprim-sulfamethoxazole single strength",
    "IV: Intravenous",
    "GI: Gastrointestinal",
    "MRSA: Methicillin-resistant Staphylococcus aureus",
    "SC, SQ: subcutaneous",
    "4.2 EN: Enteral nutrition",
    "ISSUED DATE: 30/12/2021 update date 23/11/2023 SN",
    "City -Riyadh 15 Feb 2026",
    "Accessed 1 November 2019. Available from",
    "18 September 2024",
]

# Wingdings/Symbol bullet glyphs, which decode into the Unicode Private Use
# Area (U+F000-U+F0FF). _BULLET originally covered only U+F0B7 (the one
# codepoint enumerated by name); these five are different PUA codepoints from
# the same font-private bullet block and were NOT rejected before this fix.
# Verbatim lines, confirmed against var/raw_text/*.json. Measured on the built
# KB: 26 MOH clauses (13 distinct titles) carried one of these as a
# section_title before the fix.
WINGDINGS_PUA_BULLETS = [
    " Physiologic Reactions:",
    " Safety Profile",
    " Perform ECG",
    " Input/Output Chart  Daily Weight",
    " AND EITHER OF A OR B:",
    " Meropenem 1g IV q8hr",
]

# Real headings that MUST survive. This half is the point: a bare
# "^[^:]{1,28}:\\s+\\S" glossary pattern rejects the first four of these, which
# would lose a real section title permanently. Requiring an abbreviation-shaped
# (>=60% uppercase) left-hand side is what keeps them.
MUST_ACCEPT = [
    "Table 10: Treatment of Hypertriglyceridemia",
    "Figure 1: Classification of DM",
    "Assessment: Patient’s Profiling",
    "Setup: Inpatient setting",
    "Level of Evidence:",
    "Aim and scope:",
    "Medication Related Information",
    "STAGING OF CKD",
    "Classification of HF by LVEF",
]


# Colon-terminated section labels the CHI capitalization gate drops (only 1 of
# 3 words capitalized in "Aim and scope:"), which the narrow colon acceptor
# admits. Verbatim corpus lines.
COLON_HEADINGS = [
    "Aim and scope:",
    "Targeted population:",
    "Targeted end users:",
    "Conflict of interest:",
    "When to suspect DKA:",
    "Vancomycin level:",
]

# Fragment-shaped colon-terminated lines the acceptor must keep dropping --
# mid-sentence continuations, not section labels. Verbatim corpus lines.
COLON_FRAGMENTS = [
    "the following:",
    "weight as the following:",
    "fluoroquinolone prophylaxis:",
]


def test_moh_heading_rejects_corpus_furniture():
    for line in MUST_REJECT:
        assert not _is_moh_heading(line, frozenset()), line


def test_moh_heading_rejects_wingdings_pua_bullets():
    for line in WINGDINGS_PUA_BULLETS:
        assert not _is_moh_heading(line, frozenset()), line


def test_moh_heading_accepts_real_headings():
    for line in MUST_ACCEPT:
        assert _is_moh_heading(line, frozenset()), line


def test_colon_heading_acceptor_admits_real_section_labels():
    for line in COLON_HEADINGS:
        assert _is_colon_heading(line), line


def test_colon_heading_acceptor_rejects_fragment_shaped_lines():
    for line in COLON_FRAGMENTS:
        assert not _is_colon_heading(line), line


def test_no_moh_clause_carries_furniture_as_its_section_title():
    # The guard for the whole chunker fix. index.py weights section_title 5x, so
    # a regression here degrades retrieval while every other test stays green.
    #
    # The metric is the three NAMED classes, not "no junk titles". Table-cell
    # fragments ("CV effects: ASCVD Neutral...") survive by design -- see the
    # module docstring -- and asserting an unachievable 0 would only invite this
    # assertion to be loosened later.
    moh = [s for s in config.SOURCES.values() if s.genre == "moh_protocol"]
    assert len(moh) == 31

    offenders = []
    for source in moh:
        pages = extract_pages(source.path, config.RAW_TEXT_DIR)
        for clause in chunk_moh(pages, source):
            title = clause.section_title
            if _is_bullet_item(title) or _is_abbreviation_gloss(title) or _is_datestamp(title):
                offenders.append((clause.clause_id, title))
    assert offenders == [], offenders[:10]
