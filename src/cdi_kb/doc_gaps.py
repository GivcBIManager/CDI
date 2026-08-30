"""Doc-type completeness gap detection: which required/recommended elements
of a doc type's expected content (data/doc_requirements/*.yaml) are missing
from a note, via the same wrap-tolerant, word-boundary term matching
gapcheck uses for condition and axis detection (reused, not reimplemented).
"""

from cdi_kb.gapcheck import term_pattern
from cdi_kb.requirements_model import DocTypeRequirement, Element


def find_element_gaps(note_text: str, doc_req: DocTypeRequirement) -> list[Element]:
    """Elements of `doc_req` whose evidence_terms find no match anywhere in
    `note_text` -- i.e. the element appears not to be documented."""
    return [
        element for element in doc_req.elements
        if not any(term_pattern(term).search(note_text) for term in element.evidence_terms)
    ]
