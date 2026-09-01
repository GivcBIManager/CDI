"""Chunker for MOH-KSA national protocols (genre "moh_protocol").

Same page-anchored segment loop as the CHI prose chunker -- only the heading
predicate differs. MOH protocols carry three furniture genres the CHI heuristic
accepts as headings, and a bad heading is not cosmetic: index.py weights
section_title 5x body in BM25, so junk titles displace real clauses from
retrieval. Measured over the curated 31 MOH sources, 270 of 1,616 clauses
(16.7%) carried a bullet-, glossary-, or date-shaped title before this fix,
concentrated in the highest-value protocols (SSTI 60%, surgical prophylaxis
53%, GAS 47%, SSI 47%, LRTI 37%, UTI 35%).

Each rejector was tuned against the corpus and verified to reject ONLY junk.
Residual, accepted: 88 colon-bearing heading occurrences survive, a minority of
them table-cell or form-field fragments ("CV effects: ASCVD Neutral Potential
benefit: Neutral", "Vital Signs: STAT Then every__________"). Separating those
from real headings needs layout geometry the text layer does not carry. They
are left in deliberately: an over-broad rejector loses a real section title
permanently, while a surviving table fragment only adds noise to one clause's
title. V1 fidelity and citation stability are unaffected either way, because
clause_id is page-anchored.

A fourth rule, `_is_colon_heading`, sits alongside the three rejectors above:
narrow-enough-to-be-additive, not a wholesale replacement for the CHI
capitalization gate. MOH protocols favor short colon-terminated section labels
("Aim and scope:", "Targeted population:", "Conflict of interest:") that are
mostly lowercase words, so the CHI `_is_heading` rule (>=60% of words
capitalized) drops them -- "Aim and scope:" is 1 of 3. Measured over the
curated 31, 313 occurrences / 265 distinct colon-terminated section-label
candidates were dropped this way before the acceptor; it now admits 179
occurrences / 143 distinct ("Aim and scope:", "Targeted population:",
"Targeted end users:", "Conflict of interest:", "Fluid management:", "When to
suspect DKA:", "Vancomycin level:") and still drops 134, almost all
fragment-shaped: mid-sentence continuations ("the following:", "weight as the
following:"), a lowercase-led clause ("fluoroquinolone prophylaxis:"), or a
bullet/dash-led line ("- Or increase the total daily dose:"). Accepting every
colon-terminated line was rejected: the still-dropped set is dominated by
reference-list citations and dosing-table fragments that happen to end in
":", and admitting those would put their fragment text where a real section
title belongs, weighted 5x by FTS. The length cap, 2-word-minimum, and
Title-Case-opening checks are what keep the acceptor narrow -- each one
tuned against a concrete still-dropped example above, not a guess.
"""

import re

from cdi_kb.chi_chunker import _is_heading, _is_letter_spaced, _line_shape, chunk_chi
from cdi_kb.clauses import Clause
from cdi_kb.config import SourceDoc
from cdi_kb.extract import PageText

# Bullet list items. Includes U+FFFD and U+F0B7 because the Wingdings bullets
# these PDFs use decode to those, not to U+2022.
_BULLET = re.compile("^[•●▪◦�]")

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
_COLON_HEADING_MAX_LEN = 60
_COLON_HEADING_MIN_WORDS = 2


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
