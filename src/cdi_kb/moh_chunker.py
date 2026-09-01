"""Chunker for MOH-KSA national protocols (genre "moh_protocol").

Same page-anchored segment loop as the CHI prose chunker -- only the heading
predicate differs. MOH protocols carry three furniture genres the CHI heuristic
accepts as headings, and a bad heading is not cosmetic: index.py weights
section_title 5x body in BM25, so junk titles displace real clauses from
retrieval. Measured over the curated 31 MOH sources (applying vanilla chunk_chi,
no MOH rules at all): 161 of 1,616 clauses (10.0%) carried a bullet-, glossary-,
or date-shaped title before this fix, concentrated unevenly across protocols --
topped by MOH-SSI (46.7%), MOH-ANAPHYLAXIS (37.5%), MOH-LRTI (31.6%), MOH-IAI
(28.6%) and MOH-DKA (28.0%). (An earlier survey reported 270/16.7% with a
different per-protocol breakdown; that measurement does not reproduce against
the current extraction cache and curated-31 registration -- the numbers above
are the current authoritative measurement.)

Each rejector was tuned against the corpus and verified to reject ONLY junk.
Residual, accepted: on the shipped chunk_moh output, 209 colon-terminated
section_titles are admitted via the base CHI _is_heading gate (a separate,
older admission stream from the colon acceptor described below), and a
minority of those are table-cell or form-field fragments rather than headings
-- e.g. "Patient: MRN:" (2 occurrences, still reproduces verbatim). Separating
those from real headings needs layout geometry the text layer does not carry.
They are left in deliberately: an over-broad rejector loses a real section
title permanently, while a surviving table fragment only adds noise to one
clause's title. V1 fidelity and citation stability are unaffected either way,
because clause_id is page-anchored.

Second residual, accepted: measured on the built KB, the count of clauses
carrying a short-left-hand-side gloss title that _GLOSS_MIN_UPPER (>=0.6
uppercase left-hand side) does not catch depends on how narrowly "short
gloss-shaped title" is defined, because the LHS shape ranges from a genuine
single-word label ("Cm:", "Setup:", "Dosing:") to a multi-field form/table line
that happens to share the same regex shape. Broadest reading -- any
_GLOSS-shaped title whose LHS falls below the uppercase-ratio gate: 95
occurrences / 52 distinct. Tightest reading -- LHS is a single all-alphabetic
word and the title carries exactly one colon (excludes multi-colon form/table
fragments like "Diagnosis: ... Time of admission: ... BMI:"): 9 occurrences / 7
distinct, e.g. "Cm: Centimeter" (3x, a glossary entry that should have been
rejected) alongside "Assessment: Patient’s Profiling" and "Administration:
Adult" (real section headings the design deliberately protects -- see the
comment on _GLOSS above: "Assessment:" and "Setup:"-shaped headings are
exactly what the uppercase-ratio gate exists to keep). Tightening
_GLOSS_MIN_UPPER to catch "Cm:" would also reject real headings shaped the
same way, so it is left as-is: a handful of glossary-entry titles surviving as
noise is preferred over losing real section headings.

A fourth rule, `_is_colon_heading`, sits alongside the three rejectors above:
narrow-enough-to-be-additive, not a wholesale replacement for the CHI
capitalization gate. MOH protocols favor short colon-terminated section labels
("Aim and scope:", "Targeted population:", "References:") that are mostly
lowercase words or a single word, so the CHI `_is_heading` rule (>=60% of words
capitalized) drops them -- "Aim and scope:" is 1 of 3, and a single-word label
like "References:" never even entered the old candidate measurement (see
_COLON_HEADING_MIN_WORDS above for why the minimum moved from 2 to 1). Measured
over the curated 31 (colon-terminated, <=60-char lines not already accepted by
_is_heading): population 500 occurrences / 367 distinct; the acceptor admits
328 / 214 ("Aim and scope:", "Targeted population:", "Targeted end users:",
"Conflict of interest:", "References:", "Methodology:", "Investigations:") and
still drops 172 / 153, almost all fragment-shaped: mid-sentence continuations
("the following:", "weight as the following:"), a lowercase-led clause
("fluoroquinolone prophylaxis:"), a digit-led fragment ("1st line:"), or a
bullet/dash-led line ("- Pediatric:"). Accepting every colon-terminated line
was rejected: the still-dropped set is dominated by reference-list citations
and dosing-table fragments that happen to end in ":", and admitting those would
put their fragment text where a real section title belongs, weighted 5x by
FTS. The length cap and Title-Case-opening (stripped[0].isupper()) checks are
what keep the acceptor narrow -- the word-count minimum, now 1, does almost
none of that work; see _COLON_HEADING_MIN_WORDS above for its own corrected
measurement (the 4-occurrence cost of admitting "Patient:"/"MRN:" alongside the
real single-word labels).
"""

import re

from cdi_kb.chi_chunker import _is_heading, _is_letter_spaced, _line_shape, chunk_chi
from cdi_kb.clauses import Clause
from cdi_kb.config import SourceDoc
from cdi_kb.extract import PageText

# Bullet list items. Includes U+FFFD because some Wingdings/Symbol bullets
# these PDFs use decode to that instead of U+2022. U+F000-U+F0FF covers the
# whole Wingdings/Symbol Private Use Area block rather than an enumerated
# list of glyphs: PDF font-private glyph codepoints have no fixed meaning
# outside the embedding font, so any character in this range at line start
# is always a bullet or list marker rendered by a symbol font, never real
# section-heading text. Enumerating individual codepoints (originally just
# U+F0B7) missed other glyphs from the same block and let list items
# become junk section_titles, weighted 5x in FTS (see module docstring).
_BULLET = re.compile("^[•●▪◦\ufffd\uf000-\uf0ff]")

# "<abbrev>: <expansion>" from the abbreviation table every MOH protocol opens
# with. The uppercase-ratio test below is load-bearing: this pattern ALONE also
# matches "Table 10: Treatment of Hypertriglyceridemia", "Figure 1:
# Classification of DM", "Assessment: Patient's Profiling" and "Setup: Inpatient
# setting", which are real headings. Requiring an abbreviation-shaped left-hand
# side separates "IV:" and "MRSA:" from "Assessment:" and "Table 10:" with no
# false rejection observed across the curated 31.
_GLOSS = re.compile(r"^(?P<lhs>[^:]{1,28}):\s+\S")
_GLOSS_MIN_UPPER = 0.6

# Publication/revision stamps and reference-list access dates.
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*"
_DATESTAMP = re.compile(
    rf"\b\d{{1,2}}\s+{_MONTH}\s+(?:19|20)\d{{2}}\b"
    rf"|\b{_MONTH}\s+\d{{1,2}},?\s+(?:19|20)\d{{2}}\b"
    rf"|\b\d{{1,2}}/\d{{1,2}}/(?:19|20)\d{{2}}\b",
    re.IGNORECASE,
)


def _upper_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    return sum(1 for c in letters if c.isupper()) / len(letters) if letters else 0.0


def _is_bullet_item(line: str) -> bool:
    return bool(_BULLET.match(line.strip()))


def _is_abbreviation_gloss(line: str) -> bool:
    match = _GLOSS.match(line.strip())
    return bool(match) and _upper_ratio(match.group("lhs")) >= _GLOSS_MIN_UPPER


def _is_datestamp(line: str) -> bool:
    return bool(_DATESTAMP.search(line))


# Short, Title-Case-opening, colon-terminated section labels ("Aim and scope:",
# "Targeted population:") that the CHI capitalization gate (>=60% of words
# capitalized) drops -- a 2-of-3-words label like "Aim and scope:" never
# clears that bar. Deliberately narrow: accepting every colon-terminated line
# would also admit mid-sentence fragments ("the following:", "weight as the
# following:", "fluoroquinolone prophylaxis:" -- lowercase first character,
# not a section label). The length cap and upper-case-first-letter test
# together are what keep those out.
#
# _COLON_HEADING_MIN_WORDS is 1, not 2. The original 2-word minimum was set
# from a flawed measurement: its candidate population required >=2 alpha-led
# words by construction, so it could not see the single-word labels it was
# discarding. Re-measured on the curated 31, a minimum of 2 drops 149
# occurrences / 71 distinct real single-word section headings --
# "References:" (21), "Methodology:" (13), "Introduction:" (7), "Funding:"
# (7), "Investigations:" (6), "Purpose:" (6), "Updating:" (6), "Monitoring:"
# (6), "Setup:" (4), "Management:" (3), plus "Appendix 1:", "Section 1:"
# through "Section 12:", "Indication:", "Disclaimer:", "Contributors:". At a
# minimum of 1, the cost is 4 occurrences of form-field junk ("Patient:" x2,
# "MRN:" x2). `stripped[0].isupper()` is the check actually doing the
# discriminating work here, not the word count: it is what rejects the
# lowercase and numbered fragments ("method:", "1st line:", "- Pediatric:",
# "2.Monitoring:") that a bare word-count minimum would otherwise admit.
_COLON_HEADING_MAX_LEN = 60
_COLON_HEADING_MIN_WORDS = 1


def _is_colon_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped.endswith(":") or len(stripped) > _COLON_HEADING_MAX_LEN:
        return False
    words = [w for w in stripped.split() if w[0].isalpha()]
    if len(words) < _COLON_HEADING_MIN_WORDS:
        return False
    return stripped[0].isupper()


def _is_moh_heading(line: str, furniture: frozenset[str] = frozenset()) -> bool:
    """The CHI heading rule, minus the three MOH furniture genres, plus a
    narrow colon-heading acceptor (see _is_colon_heading) for section labels
    the CHI capitalization gate misses."""
    if _is_bullet_item(line) or _is_abbreviation_gloss(line) or _is_datestamp(line):
        return False
    if _is_heading(line, furniture):
        return True
    stripped = line.strip()
    if _line_shape(stripped) in furniture or _is_letter_spaced(stripped):
        return False
    return _is_colon_heading(line)


def chunk_moh(pages: list[PageText], source: SourceDoc) -> list[Clause]:
    return chunk_chi(pages, source, is_heading=_is_moh_heading)
