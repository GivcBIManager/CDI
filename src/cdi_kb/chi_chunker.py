"""Heading-heuristic chunker for CHI prose guidelines (no dot-leader TOC).

clause_id is page-anchored ({SRC}/pg<page>/p<n>) so citation stability does not
depend on heading-detection quality; V1 guarantees verbatim fidelity either way.
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
        body_lines: list[str] = []
        for line in page.text.splitlines():
            if _is_heading(line):
                current_heading = line.strip()
            else:
                body_lines.append(line)
        ordinal = 0
        for paragraph in split_paragraphs("\n".join(body_lines)):
            ordinal += 1
            clauses.append(Clause(
                clause_id=f"{source.source_id}/pg{page.page_number}/p{ordinal}",
                section_title=current_heading,
                page=page.page_number,
                text=paragraph,
            ))
    return clauses
