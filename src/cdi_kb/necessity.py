"""Medical-necessity detection: an order term documented without a nearby
ordering-language cue and a supporting indication anywhere in the note.

Detection reuses gapcheck's wrap-tolerant, word-boundary term matcher and its
pre-mention negation window rather than re-implementing matching (see
gapcheck.py module docstring for the negation window's documented
limitations: pre-mention only, fixed cue window).

A NecessityRule fires when, for some order term:
  1. the term matches note_text (wrap-tolerant, word-boundary), AND
  2. that match is not negated (gapcheck's negation window), AND
  3. a context cue occurs within +/-60 chars of the match span, AND
  4. no valid-indication term matches anywhere in the note.
"""

from cdi_kb.gapcheck import is_negated, term_pattern
from cdi_kb.requirements_model import NecessityRule

_CONTEXT_WINDOW_CHARS = 60


def _cue_nearby(note_text: str, rule: NecessityRule, start: int, end: int) -> bool:
    window = note_text[max(0, start - _CONTEXT_WINDOW_CHARS) : end + _CONTEXT_WINDOW_CHARS]
    return any(term_pattern(cue).search(window) for cue in rule.context_cues)


def find_necessity_gaps(note_text: str, rules: list[NecessityRule]) -> list[NecessityRule]:
    gaps: list[NecessityRule] = []
    for rule in rules:
        if any(term_pattern(term).search(note_text) for term in rule.valid_indication_terms):
            continue  # a valid indication is documented somewhere -- never a gap
        for order_term in rule.order_terms:
            fired = False
            for match in term_pattern(order_term).finditer(note_text):
                if is_negated(note_text, match.start()):
                    continue
                if _cue_nearby(note_text, rule, match.start(), match.end()):
                    fired = True
                    break
            if fired:
                gaps.append(rule)
                break
    return gaps
