"""Medical-necessity detection: an order term documented with order-specific
language nearby and no supporting indication anywhere in the note.

Detection reuses gapcheck's wrap-tolerant, word-boundary term matcher and its
pre-mention negation window rather than re-implementing matching (see
gapcheck.py module docstring for the negation window's documented
limitations: pre-mention only, fixed cue window).

A NecessityGap fires for a rule when, for some order term match:
  1. the term matches note_text (wrap-tolerant, word-boundary), AND
  2. that match is not negated (gapcheck's negation window), AND
  3. that match does not look like a RESULT mention rather than an order --
     two UNCONDITIONAL guards (heuristic, documented limitation, apply
     regardless of which cue justifies the match -- see _looks_like_result):
       - a numeric/percent value immediately following the match (e.g.
         "HbA1c 8.1%", "glucose 126", "B12 250"), OR
       - a result/abnormal-value word shortly BEFORE the match, within 20
         chars (result, resulted, level, levels, negative, positive,
         showed, elevated, low, high, normal, abnormal, raised, reduced --
         e.g. "the elevated HbA1c", "Labs showed HbA1c ..."), AND
  4. an order-specific cue occurs within +/-60 chars of the match span (a
     verb phrase that cannot plausibly describe a result, e.g. "ordered",
     "requested", "arrange", "will obtain" -- bare, ambiguous verbs like
     "check"/"obtain"/"send"/"draw"/"collect"/"sent" are deliberately
     excluded, see data/necessity/*.yaml), OR the SAME-LINE "plan:" rule is
     satisfied (see below), AND
  5. no valid-indication term matches anywhere in the note.

Same-line "plan:" rule (fix: "Plan: discuss HbA1c results with patient" and
"Plan: review B12 result" were false-firing purely off a bare "plan:" on the
line). "plan:" is NOT matched via the +/-60 window like the other cues; it is
satisfied for a match only when, on the line containing "plan:":
  - an order verb (order, ordered, request, requested, arrange, repeat,
    obtain, check -- whole words, hyphen-safe) appears ANYWHERE on the line,
    e.g. "Plan: repeat fasting glucose next visit."; OR
  - NO verb precedes the order term on that line at all, i.e. the term is
    the very first token after "plan:" -- a bare listed test under "Plan:"
    (e.g. "Plan: HbA1c, lipids.") is itself an order. True part-of-speech
    detection isn't available in this deterministic matcher, so "no verb
    precedes" is operationalized as "nothing but whitespace/punctuation sits
    between 'plan:' and the term" -- ANY token there (a verb like "discuss"/
    "review", or even an article) disqualifies the exception. This can
    occasionally under-fire on a genuine bare order phrased with a
    determiner ("Plan: the HbA1c today"), but that is the safe failure
    direction (silent-but-logged beats a false finding).

Then, ONLY when "plan:" is the SOLE reason the cue check passed (no other
window cue also matched -- see _cue_reason), a further AFTER-word guard
applies: a result/finding word within 25 chars AFTER the match (result,
results, finding, findings, level, levels, value, values, reading,
readings, report, reported, "came back", showed, elevated, low, high,
normal, abnormal) suppresses the match, e.g. "Plan: review fasting glucose
findings", "Plan: go over urine culture result with parents". This guard is
scoped to the plan-line path specifically -- NOT applied when a genuine
order-verb window cue justified the match -- so that "Will obtain vitamin
B12 level." still fires despite "level" following the match: an explicit
"will obtain"/"order"/"requested"/etc. immediately establishes an order
regardless of what test-attribute word follows it, whereas a bare "plan:"
alone does not carry that same certainty.

Two further matching-precision guards (apply to cue matches only):
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

# Result-exclusion guards (fix: bare cues were false-firing on result-reporting
# text, e.g. "HbA1c 8.1% today. Plan: continue home meds."). Heuristic, not a
# clinical NLP model -- documented limitation.
_RESULT_NUMERIC_LOOKAHEAD_CHARS = 20  # raw window scanned before stripping
_RESULT_NUMERIC_SIGNIFICANT_CHARS = 12  # "within 12 chars, ignoring spaces/colon"
_RESULT_NUMERIC_PATTERN = re.compile(r"^[<>≤≥]?\d")
_SPACE_OR_COLON = re.compile(r"[\s:]")

_RESULT_WORD_BEFORE_WINDOW_CHARS = 20  # unconditional (applies to every match)
_RESULT_WORDS_BEFORE = (
    "result", "resulted", "level", "levels", "negative", "positive", "showed",
    "elevated", "low", "high", "normal", "abnormal", "raised", "reduced",
)
_RESULT_WORD_BEFORE_PATTERNS = [term_pattern(word) for word in _RESULT_WORDS_BEFORE]

_RESULT_WORD_AFTER_WINDOW_CHARS = 25  # scoped to the plan-line-only path (see above)
_RESULT_WORDS_AFTER = (
    "result", "results", "finding", "findings", "level", "levels", "value", "values",
    "reading", "readings", "report", "reported", "came back", "showed",
    "elevated", "low", "high", "normal", "abnormal",
)
_RESULT_WORD_AFTER_PATTERNS = [term_pattern(word) for word in _RESULT_WORDS_AFTER]

# "plan:" is intentionally NOT matched via the +/-60 window: it must appear on
# the same line as the order-term match (see module docstring).
_SAME_LINE_CUES = {"plan:"}

_PLAN_LINE_ORDER_VERBS = ("order", "ordered", "request", "requested", "arrange", "repeat", "obtain", "check")


@dataclass(frozen=True)
class NecessityGap:
    rule: NecessityRule
    evidence_excerpt: str


def _hyphen_safe_search(pattern: re.Pattern[str], text: str) -> bool:
    """True if `pattern` matches somewhere in `text` and the match is not
    immediately followed by "-" (hyphen counts as a word boundary here, e.g.
    "check-up"/"order-set" must not satisfy a bare "check"/"order" match)."""
    for match in pattern.finditer(text):
        if match.end() < len(text) and text[match.end()] == "-":
            continue
        return True
    return False


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
    before = note_text[max(0, start - _RESULT_WORD_BEFORE_WINDOW_CHARS) : start]
    return any(pattern.search(before) for pattern in _RESULT_WORD_BEFORE_PATTERNS)


def _result_word_follows(note_text: str, end: int) -> bool:
    after = note_text[end : end + _RESULT_WORD_AFTER_WINDOW_CHARS]
    return any(pattern.search(after) for pattern in _RESULT_WORD_AFTER_PATTERNS)


def _looks_like_result(note_text: str, start: int, end: int) -> bool:
    """Unconditional guards, checked for every candidate match regardless of
    which cue will justify it."""
    return _numeric_follows(note_text, end) or _result_word_precedes(note_text, start)


def _line_has_order_verb(line: str) -> bool:
    return any(_hyphen_safe_search(term_pattern(verb), line) for verb in _PLAN_LINE_ORDER_VERBS)


def _plan_same_line_satisfied(note_text: str, start: int) -> bool:
    line_start = note_text.rfind("\n", 0, start) + 1
    line_end = note_text.find("\n", start)
    if line_end == -1:
        line_end = len(note_text)
    line = note_text[line_start:line_end]
    plan_match = term_pattern("plan:").search(line)
    if plan_match is None:
        return False
    if _line_has_order_verb(line):
        return True
    term_start_in_line = start - line_start
    if term_start_in_line < plan_match.end():
        return False  # the term precedes "plan:" on the line -- not "under" it
    return line[plan_match.end() : term_start_in_line].strip() == ""


def _cue_reason(note_text: str, rule: NecessityRule, start: int, end: int) -> str | None:
    """'window_cue' if a genuine order-verb-phrase cue (anything other than
    "plan:") matches within +/-60 chars of the match span, 'plan_line' if
    only the same-line "plan:" rule is satisfied, else None."""
    window_cues = [c for c in rule.context_cues if c.strip().lower() not in _SAME_LINE_CUES]
    window = note_text[max(0, start - _CONTEXT_WINDOW_CHARS) : end + _CONTEXT_WINDOW_CHARS]
    if any(_hyphen_safe_search(_cue_pattern(cue), window) for cue in window_cues):
        return "window_cue"
    same_line_cues = [c for c in rule.context_cues if c.strip().lower() in _SAME_LINE_CUES]
    if same_line_cues and _plan_same_line_satisfied(note_text, start):
        return "plan_line"
    return None


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
                reason = _cue_reason(note_text, rule, match.start(), match.end())
                if reason is None:
                    continue
                if reason == "plan_line" and _result_word_follows(note_text, match.end()):
                    continue
                fired_match = match
                break
            if fired_match is not None:
                start, end = fired_match.start(), fired_match.end()
                excerpt = note_text[max(0, start - _EXCERPT_PAD_CHARS) : end + _EXCERPT_PAD_CHARS].strip()
                gaps.append(NecessityGap(rule=rule, evidence_excerpt=excerpt))
                break
    return gaps
