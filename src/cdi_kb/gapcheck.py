"""Deterministic audit core: condition detection, axis evidence scan, gap check.

Demo limitations (accepted, documented): (1) axis evidence is scanned across
the whole note, not attributed to a specific condition mention; (2) negation
is a fixed cue window, not full ConText; (3) negation cues are matched only
pre-mention (resolved/ruled out post-positioned phrasings are not caught).
Both are called out in the proposal as the points where the production
NLP/LLM stage takes over.
"""

import re
from dataclasses import dataclass

from cdi_kb.requirements_model import AxisRule, DiagnosisRequirement

_NEGATION_CUES = ("no ", "not ", "denies", "denied", "without", "negative for",
                  "ruled out", "no evidence of", "resolved")
_NEGATION_WINDOW_CHARS = 40
# Window searched either side of an ambiguous abbreviation for a cue that pins
# down which condition it names. Sized to a clinical problem-list entry: wide
# enough to reach the rest of the line and the one after it, narrow enough not
# to reach an unrelated problem further down the plan.
_AMBIGUOUS_CUE_WINDOW_CHARS = 200


def _whitespace_flexible_pattern(term: str) -> str:
    """Join a (possibly multi-word) term's words with \\s+ so a note that wraps
    the term across a line break (e.g. "stage\\n4") still matches."""
    return r"\s+".join(re.escape(word) for word in term.split())


# Precompile boundary-aware patterns for negation cues
_NEGATION_CUE_PATTERNS = [
    re.compile(rf"(?<![A-Za-z0-9]){_whitespace_flexible_pattern(cue.rstrip())}(?![A-Za-z0-9])", re.IGNORECASE)
    for cue in _NEGATION_CUES
]


@dataclass(frozen=True)
class ConditionMention:
    condition: str
    matched_text: str
    start: int
    end: int
    negated: bool


@dataclass(frozen=True)
class Gap:
    condition: str
    axis: str
    level: str
    mention: ConditionMention


def term_pattern(term: str) -> re.Pattern[str]:
    """Wrap-tolerant, word-boundary regex for a (possibly multi-word) term --
    the shared matcher used across condition/axis/element detection."""
    escaped = _whitespace_flexible_pattern(term)
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)


_term_pattern = term_pattern  # back-compat alias for existing internal/test references


def _is_negated(note_text: str, start: int) -> bool:
    window = note_text[max(0, start - _NEGATION_WINDOW_CHARS) : start]
    return any(pattern.search(window) for pattern in _NEGATION_CUE_PATTERNS)


def is_negated(note_text: str, start: int) -> bool:
    """Public wrapper around the pre-mention negation-window check -- shared
    with necessity.py so order-term negation reuses this exact cue list/window
    instead of re-implementing it."""
    return _is_negated(note_text, start)


def _cue_nearby(note_text: str, start: int, end: int, cues: list[str]) -> bool:
    """Whether any disambiguating cue appears within the window around a mention.
    Symmetric (the cue can precede or follow the abbreviation) because clinical
    problem lines put it either way: "ARF - creatinine trending up" vs
    "blood gas shows a low pO2 ... the team documents ARF"."""
    window = note_text[max(0, start - _AMBIGUOUS_CUE_WINDOW_CHARS) : end + _AMBIGUOUS_CUE_WINDOW_CHARS]
    return any(term_pattern(cue).search(window) for cue in cues)


def detect_conditions(note_text: str, requirements: list[DiagnosisRequirement]) -> list[ConditionMention]:
    mentions: list[ConditionMention] = []
    for req in requirements:
        ambiguous = {entry.term: entry.requires_nearby for entry in req.ambiguous_synonyms}
        terms = sorted({req.condition, *req.synonyms, *ambiguous}, key=len, reverse=True)
        claimed: list[tuple[int, int]] = []
        for term in terms:
            cues = ambiguous.get(term)
            for match in term_pattern(term).finditer(note_text):
                if any(match.start() < end and match.end() > start for start, end in claimed):
                    continue  # longer term already claimed this span
                if cues is not None and not _cue_nearby(note_text, match.start(), match.end(), cues):
                    continue  # ambiguous term with nothing to disambiguate it -- claim nothing
                claimed.append((match.start(), match.end()))
                mentions.append(ConditionMention(
                    condition=req.condition, matched_text=match.group(0),
                    start=match.start(), end=match.end(),
                    negated=_is_negated(note_text, match.start()),
                ))
    return sorted(mentions, key=lambda m: m.start)


def scan_axes(note_text: str, requirement: DiagnosisRequirement) -> set[str]:
    present: set[str] = set()
    for rule in requirement.axes:
        if any(term_pattern(term).search(note_text) for term in rule.evidence_terms):
            present.add(rule.axis)
    return present


def rule_applies(rule: AxisRule, doc_type: str) -> bool:
    """Whether an axis rule scoped by `rule.applies_to` is in scope for
    `doc_type`. A rule scoped to "any" (the default) always applies; a note
    whose doc type could not be pinned down ("any") is matched by every
    rule regardless of that rule's own scoping."""
    return "any" in rule.applies_to or doc_type == "any" or doc_type in rule.applies_to


def find_gaps(
    note_text: str,
    requirements: list[DiagnosisRequirement],
    doc_type: str = "any",
) -> list[Gap]:
    by_condition = {req.condition: req for req in requirements}
    gaps: list[Gap] = []
    seen: set[tuple[str, str]] = set()
    for mention in detect_conditions(note_text, requirements):
        if mention.negated:
            continue
        req = by_condition[mention.condition]
        present = scan_axes(note_text, req)
        for rule in req.axes:
            if not rule_applies(rule, doc_type):
                continue
            key = (mention.condition, rule.axis)
            if rule.axis not in present and key not in seen:
                seen.add(key)
                gaps.append(Gap(condition=mention.condition, axis=rule.axis,
                                level=rule.level, mention=mention))
    return gaps
