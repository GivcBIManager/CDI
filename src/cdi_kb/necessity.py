"""Medical-necessity detection: an order term documented with order-specific
language nearby and no supporting indication anywhere in the note.

Detection reuses gapcheck's wrap-tolerant, word-boundary term matcher and its
pre-mention negation window rather than re-implementing matching (see
gapcheck.py module docstring for the negation window's documented
limitations: pre-mention only, fixed cue window).

A NecessityGap fires for a rule when, for some order term match:
  1. the term matches note_text (wrap-tolerant, word-boundary), AND
  2. that match is not negated (gapcheck's negation window), AND
  3. that match does not look like a RESULT mention rather than an order
     (heuristic, documented limitation -- see _looks_like_result): a
     numeric/percent value immediately following the match (e.g. "HbA1c
     8.1%", "glucose 126", "B12 250"), or a result word ("result",
     "resulted", "level", "levels", "negative", "positive", "showed")
     shortly BEFORE the match (e.g. "Labs showed HbA1c ..."), reads as a
     value being reported, not a test being ordered, and is excluded, AND
  4. an order-specific cue occurs within +/-60 chars of the match span (a
     verb phrase that cannot plausibly describe a result, e.g. "ordered",
     "requested", "arrange", "will obtain" -- bare, ambiguous verbs like
     "check"/"obtain"/"send"/"draw"/"collect"/"sent" are deliberately
     excluded, see data/necessity/*.yaml), OR "plan:" appears on the SAME
     LINE as the match (tighter than the +/-60 window, since a bare "plan:"
     within 60 chars is also common around result summaries), AND
  5. no valid-indication term matches anywhere in the note.

Two further matching-precision guards (both apply to cue matches only):
  - a cue match immediately followed by "-" is rejected (hyphen counts as a
    word boundary for cues -- "check-up"/"order-set" must not satisfy a
    bare "check"/"order" cue);
  - the bare "order" cue specifically excludes "in order to" (a common
    non-clinical idiom), via a negative lookahead.

Known limitation (urine-culture specifically): the CHI source's scope is
healthy children 3 months-14 years with a first UTI, excluding hospitalized
patients -- population/setting cannot be verified from note text, so that
rule is authored at level "recommended" rather than "required" (see the
population_note comment in data/necessity/urine-culture.yaml).
"""

import re
from dataclasses import dataclass

from cdi_kb.gapcheck import is_negated, term_pattern
from cdi_kb.requirements_model import NecessityRule

_CONTEXT_WINDOW_CHARS = 60
_EXCERPT_PAD_CHARS = 40

# Result-exclusion guard (fix: bare cues were false-firing on result-reporting
# text, e.g. "HbA1c 8.1% today. Plan: continue home meds."). Heuristic, not a
# clinical NLP model -- documented limitation.
_RESULT_NUMERIC_LOOKAHEAD_CHARS = 20  # raw window scanned before stripping
_RESULT_NUMERIC_SIGNIFICANT_CHARS = 12  # "within 12 chars, ignoring spaces/colon"
_RESULT_WORD_WINDOW_CHARS = 20
_RESULT_WORDS = ("result", "resulted", "level", "levels", "negative", "positive", "showed")
_RESULT_WORD_PATTERNS = [term_pattern(word) for word in _RESULT_WORDS]
_RESULT_NUMERIC_PATTERN = re.compile(r"^[<>≤≥]?\d")
_SPACE_OR_COLON = re.compile(r"[\s:]")

# "plan:" is intentionally NOT matched via the +/-60 window: it must appear on
# the same line as the order-term match (see module docstring point 4).
_SAME_LINE_CUES = {"plan:"}


@dataclass(frozen=True)
class NecessityGap:
    rule: NecessityRule
    evidence_excerpt: str


def _cue_pattern(cue: str) -> re.Pattern[str]:
    base = term_pattern(cue)
    if cue.strip().lower() == "order":
        # "in order to" is a common non-clinical idiom that would otherwise
        # false-trigger the bare "order" cue.
        return re.compile(base.pattern + r"(?!\s+to\b)", re.IGNORECASE)
    return base


def _numeric_follows(note_text: str, end: int) -> bool:
    after = note_text[end : end + _RESULT_NUMERIC_LOOKAHEAD_CHARS]
    stripped = _SPACE_OR_COLON.sub("", after)[:_RESULT_NUMERIC_SIGNIFICANT_CHARS]
    return bool(_RESULT_NUMERIC_PATTERN.match(stripped))


def _result_word_precedes(note_text: str, start: int) -> bool:
    before = note_text[max(0, start - _RESULT_WORD_WINDOW_CHARS) : start]
    return any(pattern.search(before) for pattern in _RESULT_WORD_PATTERNS)


def _looks_like_result(note_text: str, start: int, end: int) -> bool:
    return _numeric_follows(note_text, end) or _result_word_precedes(note_text, start)


def _plan_same_line(note_text: str, pos: int) -> bool:
    line_start = note_text.rfind("\n", 0, pos) + 1
    line_end = note_text.find("\n", pos)
    if line_end == -1:
        line_end = len(note_text)
    return term_pattern("plan:").search(note_text[line_start:line_end]) is not None


def _cue_nearby(note_text: str, rule: NecessityRule, start: int, end: int) -> bool:
    window_cues = [c for c in rule.context_cues if c.strip().lower() not in _SAME_LINE_CUES]
    same_line_cues = [c for c in rule.context_cues if c.strip().lower() in _SAME_LINE_CUES]
    window = note_text[max(0, start - _CONTEXT_WINDOW_CHARS) : end + _CONTEXT_WINDOW_CHARS]
    for cue in window_cues:
        for match in _cue_pattern(cue).finditer(window):
            if match.end() < len(window) and window[match.end()] == "-":
                continue  # "check-up"/"order-set" must not match a bare cue word
            return True
    return bool(same_line_cues) and _plan_same_line(note_text, start)


def find_necessity_gaps(note_text: str, rules: list[NecessityRule]) -> list[NecessityGap]:
    gaps: list[NecessityGap] = []
    for rule in rules:
        if any(term_pattern(term).search(note_text) for term in rule.valid_indication_terms):
            continue  # a valid indication is documented somewhere -- never a gap
        for order_term in rule.order_terms:
            fired_match: re.Match[str] | None = None
            for match in term_pattern(order_term).finditer(note_text):
                if is_negated(note_text, match.start()):
                    continue
                if _looks_like_result(note_text, match.start(), match.end()):
                    continue
                if _cue_nearby(note_text, rule, match.start(), match.end()):
                    fired_match = match
                    break
            if fired_match is not None:
                start, end = fired_match.start(), fired_match.end()
                excerpt = note_text[max(0, start - _EXCERPT_PAD_CHARS) : end + _EXCERPT_PAD_CHARS].strip()
                gaps.append(NecessityGap(rule=rule, evidence_excerpt=excerpt))
                break
    return gaps
