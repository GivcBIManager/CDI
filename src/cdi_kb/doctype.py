"""Doc-type detection: heuristics that classify a clinical note's structural
shape so `AxisRule.applies_to` can scope certain axis rules to a specific
note type (e.g. a discharge-summary-only rule). Detection is conservative --
free prose that doesn't clearly match a known shape falls back to "any",
which every rule matches (see gapcheck.rule_applies).

Order of checks: header phrase (first 400 chars) -> SOAP markers -> a
diagnosis-list shape -> "any".
"""

import re

from cdi_kb.requirements_model import DocType

# (phrase, doc type) pairs checked against the lowercased first 400 chars of
# the note. Order matters: first match wins, so more specific phrases
# ("emergency department") are listed ahead of generic ones would be if any
# existed.
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

_HEADER_SCAN_CHARS = 400

# ">= 3 lines starting (after optional leading whitespace) with S/O/A/P
# followed by a colon" -- the classic SOAP-note skeleton.
_SOAP_LINE_PATTERN = re.compile(r"^\s*[SOAP]\s*:", re.IGNORECASE | re.MULTILINE)
_SOAP_MIN_LINES = 3

# Diagnosis-list shape: short, mostly-terse lines (problem-list style) rather
# than wrapped prose sentences.
_DIAGNOSIS_LIST_MIN_LINES = 3
_DIAGNOSIS_LIST_SHORT_LEN = 60
_DIAGNOSIS_LIST_SHORT_RATIO = 0.6
_PROSE_MIN_WORDS = 8


def _header_match(note_text: str) -> DocType | None:
    head = note_text[:_HEADER_SCAN_CHARS].lower()
    for phrase, doc_type in _HEADER_PHRASES:
        if phrase in head:
            return doc_type
    return None


def _is_soap(note_text: str) -> bool:
    return len(_SOAP_LINE_PATTERN.findall(note_text)) >= _SOAP_MIN_LINES


def _is_diagnosis_list(note_text: str) -> bool:
    lines = [line.strip() for line in note_text.splitlines() if line.strip()]
    if len(lines) < _DIAGNOSIS_LIST_MIN_LINES:
        return False

    short_count = sum(1 for line in lines if len(line) < _DIAGNOSIS_LIST_SHORT_LEN)
    if short_count / len(lines) < _DIAGNOSIS_LIST_SHORT_RATIO:
        return False

    # A line ending in a sentence period immediately followed by another
    # prose line (>= 8 words) is wrapped prose, not a diagnosis list.
    for line, following in zip(lines, lines[1:]):
        if line.endswith(".") and len(following.split()) >= _PROSE_MIN_WORDS:
            return False

    return True


def detect_doc_type(note_text: str) -> DocType:
    header = _header_match(note_text)
    if header is not None:
        return header
    if _is_soap(note_text):
        return "progress_note"
    if _is_diagnosis_list(note_text):
        return "diagnosis_list"
    return "any"
