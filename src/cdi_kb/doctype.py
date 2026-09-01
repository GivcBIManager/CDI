"""Doc-type detection: heuristics that classify a clinical note's structural
shape so `AxisRule.applies_to` can scope certain axis rules to a specific
note type (e.g. a discharge-summary-only rule). Detection is conservative --
free prose that doesn't clearly match a known shape falls back to "any",
which every rule matches (see gapcheck.rule_applies).

Order of checks: header phrase (first two non-empty lines, line-anchored) ->
SOAP markers -> an untitled receiving/handover shape -> a diagnosis-list
shape -> "any".
"""

import re

from cdi_kb.gapcheck import term_pattern
from cdi_kb.requirements_model import DiagnosisRequirement, DocType

# (phrase, doc type) pairs. A phrase counts only when it anchors a whole
# line (see _normalize_header_line/_header_match) among the note's first two
# non-empty lines -- a phrase merely appearing mid-sentence in prose (e.g.
# "...presented to the emergency department...") must not match. Order
# matters: first match wins, so more specific phrases ("emergency department
# note") are listed ahead of the shorter phrases they contain.
_HEADER_PHRASES: tuple[tuple[str, DocType], ...] = (
    ("discharge summary", "discharge_summary"),
    ("discharge note", "discharge_summary"),
    ("admission note", "admission_note"),
    ("admission summary", "admission_note"),
    ("emergency department note", "emergency_note"),
    ("emergency department", "emergency_note"),
    ("emergency note", "emergency_note"),
    ("ed note", "emergency_note"),
    ("progress note", "progress_note"),
)

_HEADER_LOOKBACK_LINES = 2
_HEADER_MARKER_PREFIXES = ("#", "*")
# A header line may carry a few extra title-ish tokens beyond the phrase
# itself (a day count, a date, a parenthetical) without stopping being a
# header -- but a whole extra sentence's worth of words means it is prose.
_HEADER_MAX_EXTRA_WORDS = 3

# ">= 3 lines starting (after optional leading whitespace) with S/O/A/P
# followed by a colon" -- the classic SOAP-note skeleton.
_SOAP_LINE_PATTERN = re.compile(r"^\s*[SOAP]\s*:", re.IGNORECASE | re.MULTILINE)
_SOAP_MIN_LINES = 3

# Diagnosis-list shape: short, mostly-terse lines (problem-list style) rather
# than wrapped prose sentences.
_DIAGNOSIS_LIST_MIN_LINES = 3
_DIAGNOSIS_LIST_SHORT_LEN = 60
_DIAGNOSIS_LIST_SHORT_RATIO = 0.6
_DIAGNOSIS_LIST_ITEM_RATIO = 0.6
_DIAGNOSIS_LIST_BULLET_CHARS = ("-", "•", "*")  # "-", "•", "*"
_PROSE_MIN_WORDS = 8

# Receiving/handover-note shape: an untitled note written at the point of taking
# over a patient's care. A real ICU handover carried no title, so header matching
# found nothing; its only SOAP-ish marker was "Plan :" (the "P" is followed by
# "lan", so _SOAP_LINE_PATTERN correctly declined); and it fell back to "any",
# which has no DocTypeRequirement -- so none of the 19 completeness rules ran and
# the audit returned zero findings on a note missing its admitting diagnosis,
# history, comorbidities, care plan and discharge planning.
#
# TWO signals are required, because either alone is common and a wrong doc type
# is worse than none: a wrong type applies the wrong completeness rules and
# manufactures false positives, whereas "any" merely stays quiet.
#
#   ARRIVAL   the note says how the patient got here, near the top.
#   LABELLED  it is structured as "Label: value" lines rather than free prose.
#
# Measured across the 40 untyped eval notes: the highest labelled-line count is
# 1, and exactly one note carries an arrival phrase (with zero labelled lines).
# Requiring both leaves every one of them at "any" -- pinned by
# test_untyped_eval_notes_stay_below_the_receiving_note_threshold.
_ARRIVAL_PHRASES: tuple[str, ...] = (
    "presented to", "presenting to", "presents to", "received from",
    "admitted to", "was admitted", "transferred to", "shifted to",
    "arrived at", "arrived to", "brought to", "handed over",
)
_ARRIVAL_LOOKBACK_LINES = 6
_ARRIVAL_MIN = 1
# "Label:" at the start of a line -- letters, spaces, slashes and parentheses
# only, so a wrapped prose line ending in a colon does not qualify.
_LABELLED_LINE = re.compile(r"^[ \t]*[A-Za-z][A-Za-z /()]{1,28}[ \t]*:", re.MULTILINE)
_LABELLED_MIN = 2


def _arrival_phrase_count(note_text: str) -> int:
    """Arrival phrases among the note's first few non-empty lines. Restricted to
    the top of the note because a mid-note "transferred to the ward" is a plan,
    not a statement about how this note came to be written."""
    lines = [line for line in note_text.splitlines() if line.strip()]
    head = "\n".join(lines[:_ARRIVAL_LOOKBACK_LINES]).lower()
    return sum(1 for phrase in _ARRIVAL_PHRASES if phrase in head)


def _labelled_line_count(note_text: str) -> int:
    """Lines shaped "Label: value" -- the structural marker of a written-up note
    rather than the free prose the eval corpus is made of."""
    return len(_LABELLED_LINE.findall(note_text))


def _is_receiving_note(note_text: str) -> bool:
    return (_arrival_phrase_count(note_text) >= _ARRIVAL_MIN
            and _labelled_line_count(note_text) >= _LABELLED_MIN)



def _normalize_header_line(line: str) -> str:
    """Strip, drop any leading run of '#'/'*' markers (e.g. "##", "**"),
    lowercase, drop an optional trailing ':' -- so "## Discharge Summary:"
    and "discharge summary" normalize the same way."""
    line = line.strip()
    while line[:1] in _HEADER_MARKER_PREFIXES:
        line = line[1:].strip()
    line = line.lower()
    if line.endswith(":"):
        line = line[:-1].rstrip()
    return line


def _header_match(note_text: str) -> DocType | None:
    lines = [line for line in note_text.splitlines() if line.strip()]
    for line in lines[:_HEADER_LOOKBACK_LINES]:
        normalized = _normalize_header_line(line)
        # A header line is title-like, not a sentence: it must not end with a
        # sentence period, and it must not run much longer than the phrase it
        # names (regression: "Emergency department attendance overnight with
        # chest pain, now admitted to CCU." starts with "emergency
        # department" but is prose, not a header -- both conditions below
        # rule that out while still allowing genuine short headers like
        # "Progress Note - Day 3" or "Admission note 12/08/2026").
        if normalized.endswith("."):
            continue
        for phrase, doc_type in _HEADER_PHRASES:
            if not (normalized == phrase or normalized.startswith(phrase)):
                continue
            if len(normalized.split()) > len(phrase.split()) + _HEADER_MAX_EXTRA_WORDS:
                continue
            return doc_type
    return None


def _is_soap(note_text: str) -> bool:
    return len(_SOAP_LINE_PATTERN.findall(note_text)) >= _SOAP_MIN_LINES


def _is_list_item_line(line: str, terms: list[str]) -> bool:
    """A line counts as a list item when either (a) no requirement catalogue
    is available and it opens with a digit/bullet lead, or (b) a catalogue IS
    available and the line contains one of its condition/synonym terms
    anywhere (via gapcheck.term_pattern, not just a leading match). The
    digit/bullet lead is deliberately NOT sufficient on its own once a
    catalogue exists -- a numbered plan or medication list ("1. Continue IV
    antibiotics") is otherwise indistinguishable from a numbered diagnosis
    list purely by shape (see the numbered-plan/med-list regression)."""
    if terms:
        return any(term_pattern(term).search(line) for term in terms)
    return line[0].isdigit() or line.startswith(_DIAGNOSIS_LIST_BULLET_CHARS)


def _is_diagnosis_list(
    note_text: str,
    requirements: list[DiagnosisRequirement] | None = None,
) -> bool:
    lines = [line.strip() for line in note_text.splitlines() if line.strip()]
    if len(lines) < _DIAGNOSIS_LIST_MIN_LINES:
        return False

    short_count = sum(1 for line in lines if len(line) < _DIAGNOSIS_LIST_SHORT_LEN)
    if short_count / len(lines) < _DIAGNOSIS_LIST_SHORT_RATIO:
        return False

    # No line may itself be a full prose sentence (>= 8 words) -- rules out
    # terse-but-unrelated prose ("Pt seen today.\nStable.\nNo new
    # complaints.") that would otherwise pass the short-line-ratio check.
    if any(len(line.split()) >= _PROSE_MIN_WORDS for line in lines):
        return False

    # A line ending in a sentence period immediately followed by another
    # prose line (>= 8 words) is wrapped prose, not a diagnosis list.
    for line, following in zip(lines, lines[1:]):
        if line.endswith(".") and len(following.split()) >= _PROSE_MIN_WORDS:
            return False

    # Most lines must actually look like list items: numbered/bulleted (only
    # when no catalogue is supplied), or (when a requirement catalogue IS
    # supplied) containing a known condition/synonym term. Without a
    # catalogue this falls back to digit/bullet leads only -- terse unrelated
    # sentences do not qualify.
    terms: list[str] = []
    if requirements is not None:
        for req in requirements:
            terms.append(req.condition)
            terms.extend(req.synonyms)
    list_item_count = sum(1 for line in lines if _is_list_item_line(line, terms))
    if list_item_count / len(lines) < _DIAGNOSIS_LIST_ITEM_RATIO:
        return False

    # Regression: a numbered/bulleted plan or medication list ("Plan:\n1.
    # Continue IV antibiotics\n2. Repeat CXR tomorrow\n...") has the exact
    # shape of a diagnosis list but names no catalogue condition anywhere --
    # when a catalogue is supplied, require at least one line to actually
    # contain a condition/synonym term, or this is not a diagnosis list.
    if requirements is not None:
        if not any(any(term_pattern(term).search(line) for term in terms) for line in lines):
            return False

    return True


def detect_doc_type(
    note_text: str,
    requirements: list[DiagnosisRequirement] | None = None,
) -> DocType:
    header = _header_match(note_text)
    if header is not None:
        return header
    if _is_soap(note_text):
        return "progress_note"
    # After the header and SOAP checks so an explicit title or a real SOAP
    # skeleton always wins, and before the diagnosis-list shape, which a
    # labelled-line note could otherwise be mistaken for.
    if _is_receiving_note(note_text):
        return "admission_note"
    if _is_diagnosis_list(note_text, requirements):
        return "diagnosis_list"
    return "any"
