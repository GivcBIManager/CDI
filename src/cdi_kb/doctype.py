"""Doc-type detection: heuristics that classify a clinical note's structural
shape so `AxisRule.applies_to` can scope certain axis rules to a specific
note type (e.g. a discharge-summary-only rule). Detection is conservative --
free prose that doesn't clearly match a known shape falls back to "any",
which every rule matches (see gapcheck.rule_applies).

Order of checks: header phrase (first two non-empty lines, line-anchored) ->
SOAP markers -> a diagnosis-list shape -> "any".
"""

import re

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
        for phrase, doc_type in _HEADER_PHRASES:
            if normalized == phrase or normalized.startswith(phrase):
                return doc_type
    return None


def _is_soap(note_text: str) -> bool:
    return len(_SOAP_LINE_PATTERN.findall(note_text)) >= _SOAP_MIN_LINES


def _is_list_item_line(line: str, terms: list[str]) -> bool:
    if line[0].isdigit() or line.startswith(_DIAGNOSIS_LIST_BULLET_CHARS):
        return True
    if not terms:
        return False
    lowered = line.lower()
    return any(lowered.startswith(term.lower()) for term in terms)


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

    # Most lines must actually look like list items: numbered/bulleted, or
    # (when a requirement catalogue is supplied) opening with a known
    # condition/synonym term. Without a catalogue this falls back to
    # digit/bullet leads only -- terse unrelated sentences do not qualify.
    terms: list[str] = []
    if requirements is not None:
        for req in requirements:
            terms.append(req.condition)
            terms.extend(req.synonyms)
    list_item_count = sum(1 for line in lines if _is_list_item_line(line, terms))
    if list_item_count / len(lines) < _DIAGNOSIS_LIST_ITEM_RATIO:
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
    if _is_diagnosis_list(note_text, requirements):
        return "diagnosis_list"
    return "any"
