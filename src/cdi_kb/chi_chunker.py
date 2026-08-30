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

from cdi_kb.clauses import Clause, split_paragraphs
from cdi_kb.config import SourceDoc
from cdi_kb.extract import PageText

_NUMBERED_HEADING = re.compile(r"^\d+(\.\d+)*\s+\S")


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) >= 70 or stripped.endswith("."):
        return False
    if _NUMBERED_HEADING.match(stripped):
        return True
    words = [w for w in stripped.split() if w[0].isalpha()]
    if len(words) >= 2:
        capitalized = sum(1 for w in words if w[0].isupper())
        return capitalized / len(words) >= 0.6
    return False


def chunk_chi(pages: list[PageText], source: SourceDoc) -> list[Clause]:
    clauses: list[Clause] = []
    current_heading = source.title
    for page in pages:
        segments: list[tuple[str, list[str]]] = []
        segment_lines: list[str] = []
        for line in page.text.splitlines():
            if _is_heading(line):
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
