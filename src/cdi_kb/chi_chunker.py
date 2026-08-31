"""Heading-heuristic chunker for CHI prose guidelines (no dot-leader TOC).

clause_id is page-anchored ({SRC}/pg<page>/p<n>) so citation stability does not
depend on heading-detection quality; V1 guarantees verbatim fidelity either way.

Per-page lines are split into (heading, lines) SEGMENTS at each detected
heading line: a heading line closes the current segment (attributed to the
heading that was active while its lines accumulated), then starts a new one
under the new heading. This makes V1 contiguity independent of heading-
heuristic quality — a false-positive heading line still just becomes a
segment boundary, so both halves of an interrupted paragraph remain
contiguous substrings of the source page text; a false-positive can only
ever over-split a paragraph, never splice text across the removed line.
"""

import re
from collections import Counter

from cdi_kb.clauses import Clause, split_paragraphs
from cdi_kb.config import SourceDoc
from cdi_kb.extract import PageText
from cdi_kb.normalize import normalize

_NUMBERED_HEADING = re.compile(r"^\d+(\.\d+)*\s+\S")
# Four or more consecutive single-character tokens: the letter-spaced running
# headers these journals use ("J A C C V O L . 7 9 , N O . 1 7"). Invisible while
# the PDFs extracted fused, but once de-fused every single character counted as a
# capitalised word, so the header scored as a heading and became the section_title
# of 142 CHI-HF clauses -- junk that FTS then weighted 5x and which displaced real
# clauses from retrieval.
# Page furniture -- running headers and footers -- must never become a
# section_title: FTS weights the title 5x, so furniture-titled clauses outranked
# the real governing clause for a condition's own query (CHI-CKD's
# "Kidney International Supplements (2013) 3, 73-90" beat
# CDI-2021/renal-failure-impairment/p1 for "acute kidney injury onset").
#
# Two signals together, because neither alone is safe:
#   POSITION -- only the first and last two non-empty lines of a page count. A
#     genuine repeated heading ("References", once per chapter) sits mid-page.
#   SHAPE -- digit runs collapse to '#', because the page number inside a footer
#     changes every page, so exact-line counting never sees the repetition.
#
# Measured edge-line frequencies leave a wide margin: furniture runs 45-100% of
# pages (CHI-CKD 55.8/44.8/44.8/14.7, CHI-HF 47.8 x4, CHI-STROKE 101.8) while the
# highest real heading is "References" at 8.6%. The 10% threshold sits in the gap.
_FURNITURE_MIN_PAGES = 4
_FURNITURE_PAGE_RATIO = 0.10
_EDGE_LINES = 2
_DIGIT_RUN = re.compile(r"\d+")


def _line_shape(line: str) -> str:
    """Normalized line with digit runs collapsed, so a footer whose only variable
    part is its page number counts as one recurring line."""
    return _DIGIT_RUN.sub("#", normalize(line))


def repeating_lines(pages: list[PageText]) -> frozenset[str]:
    """Line shapes recurring at the page edge often enough to be page furniture.

    Counted once per page, so a line repeated within a single page (a table
    label) is not mistaken for a running header."""
    threshold = max(_FURNITURE_MIN_PAGES, int(len(pages) * _FURNITURE_PAGE_RATIO))
    counts: Counter[str] = Counter()
    for page in pages:
        present = [line for line in page.text.splitlines() if line.strip()]
        edges = present[:_EDGE_LINES] + present[-_EDGE_LINES:]
        counts.update({_line_shape(line) for line in edges})
    return frozenset(shape for shape, n in counts.items() if shape and n >= threshold)


_MIN_SPACED_TOKENS = 6
_SPACED_SINGLE_RATIO = 0.5


def _is_letter_spaced(text: str) -> bool:
    """Whether a line is letter-spaced typography rather than words.

    Real headings are short, so the token-count floor keeps "STAGING OF CKD"
    and "Classification of HF by LVEF" safely out of scope.
    """
    tokens = text.split()
    if len(tokens) < _MIN_SPACED_TOKENS:
        return False
    singles = sum(1 for token in tokens if len(token) == 1)
    return singles / len(tokens) >= _SPACED_SINGLE_RATIO


def _is_heading(line: str, furniture: frozenset[str] = frozenset()) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) >= 70 or stripped.endswith("."):
        return False
    if _line_shape(stripped) in furniture:
        return False
    if _is_letter_spaced(stripped):
        return False
    if _NUMBERED_HEADING.match(stripped):
        return True
    words = [w for w in stripped.split() if w[0].isalpha()]
    if len(words) >= 2:
        capitalized = sum(1 for w in words if w[0].isupper())
        return capitalized / len(words) >= 0.6
    return False


def chunk_chi(pages: list[PageText], source: SourceDoc) -> list[Clause]:
    furniture = repeating_lines(pages)
    clauses: list[Clause] = []
    current_heading = source.title
    for page in pages:
        segments: list[tuple[str, list[str]]] = []
        segment_lines: list[str] = []
        for line in page.text.splitlines():
            if _is_heading(line, furniture):
                segments.append((current_heading, segment_lines))
                current_heading = line.strip()
                segment_lines = []
            else:
                segment_lines.append(line)
        segments.append((current_heading, segment_lines))  # flush the final segment

        ordinal = 0
        for heading, lines in segments:
            for paragraph in split_paragraphs("\n".join(lines)):
                ordinal += 1
                clauses.append(Clause(
                    clause_id=f"{source.source_id}/pg{page.page_number}/p{ordinal}",
                    section_title=heading,
                    page=page.page_number,
                    text=paragraph,
                ))
    return clauses
