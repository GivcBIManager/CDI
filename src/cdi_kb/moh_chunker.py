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
"""

import re

from cdi_kb.chi_chunker import _is_heading, chunk_chi
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


def _is_moh_heading(line: str, furniture: frozenset[str] = frozenset()) -> bool:
    """The CHI heading rule, minus the three MOH furniture genres."""
    if not _is_heading(line, furniture):
        return False
    return not (_is_bullet_item(line) or _is_abbreviation_gloss(line) or _is_datestamp(line))


def chunk_moh(pages: list[PageText], source: SourceDoc) -> list[Clause]:
    return chunk_chi(pages, source, is_heading=_is_moh_heading)
