"""Note segmentation by author role.

A clinical note is not one document by one author. A ward progress note carries
nursing entries, allied-health consults and specialty consult notes inline, and
until now every check in this KB read all of it as equally authoritative. That
is the opposite of the coding rule: CDI-2021/allied-health/p2 treats allied
health documentation as clinician documentation only when it adds specificity
to "an already documented condition that was originally recorded by the treating
doctor".

Segmentation is heading-based and deliberately conservative:

* A new segment opens only on a line that BOTH names an author role and reads
  like a heading (ends in ':', optionally after a parenthetical date). A topic
  heading such as "Physical Exam:" names no role and does not split the note.
* Text before the first author heading is UNATTRIBUTED, never PHYSICIAN. The
  note may well be the doctor's, but nothing in the text says so, and the
  provider-confirmation check treats unattributed as possibly-physician -- so a
  wrong guess here suppresses findings rather than inventing them.
* A segment runs to the next author heading OR to the next structural heading of
  the note's own body ("ASSESSMENT / PLAN:", "OBJECTIVE:"), which returns the
  note to its own writer. Without that second boundary a trailing plan after an
  inline consult inherits the consultant's role, and a diagnosis the treating
  doctor did record raises a false confirmation finding.
* RESIDUAL: a note that resumes the doctor's voice with NO heading at all, or
  one whose structural heading is not in _BODY_HEADINGS, still carries the
  previous role forward. Closing that needs real authorship metadata from the
  EMR, not more heading patterns.
"""

import re
from dataclasses import dataclass

PHYSICIAN = "physician"
NURSING = "nursing"
ALLIED_HEALTH = "allied_health"
UNATTRIBUTED = "unattributed"

# Allied-health disciplines are the booklet's own list (CDI-2021/allied-health-
# request-and-allied-health-note/p1, p.74): dietetics, physiotherapy,
# occupational therapy, speech therapy, podiatry, social work, pastoral care,
# orthotics and pharmacy. Nursing is deliberately NOT in it -- the booklet
# defines allied health as excluding nursing, and the confirmation rule cites a
# clause that speaks only about allied health.
_ROLE_TERMS: dict[str, tuple[str, ...]] = {
    ALLIED_HEALTH: (
        "dietitian", "dietician", "dietetics", "dietary",
        "physiotherapy", "physiotherapist", "physio",
        "occupational therapy", "occupational therapist",
        "speech therapy", "speech pathology", "speech pathologist", "speech and language",
        "podiatry", "podiatrist", "social work", "social worker",
        "pastoral care", "orthotics", "orthotist", "pharmacy", "pharmacist",
        "exercise physiologist", "allied health",
    ),
    NURSING: ("nursing", "nurse", "midwife", "midwifery"),
    PHYSICIAN: (
        "physician", "doctor", "medical officer", "medical team", "consultant",
        "registrar", "attending", "resident", "intern", "surgical team",
        "cardiology", "respiratory", "nephrology", "neurology", "gastroenterology",
        "endocrinology", "haematology", "hematology", "oncology", "psychiatry",
        "infectious diseases", "microbiology", "surgery", "orthopaedics", "orthopedics",
        "consult", "consultation",
    ),
}

# Structural headings of the note's OWN body. They name a section, not an
# author, so they return the note to its own writer. Without them a trailing
# "ASSESSMENT / PLAN:" after an inline consult inherits the consultant's role,
# and the treating doctor's own plan reads as somebody else's documentation --
# which turned a correctly-documented diagnosis into a false confirmation
# finding on the commonest note shape there is.
_BODY_HEADINGS: tuple[str, ...] = (
    "subjective", "objective", "assessment", "plan", "assessment / plan",
    "assessment/plan", "a/p", "impression", "impressions", "disposition",
    "history", "past medical history", "social history", "family history",
    "chief complaint", "presenting complaint", "hpi", "hpc",
    "examination", "physical exam", "physical examination", "exam",
    "review of systems", "ros", "vitals", "observations",
    "labs", "laboratory", "results", "investigations", "imaging", "studies",
    "micro", "microbiology", "medications", "allergies",
    "hospital course", "progress", "summary", "problem list",
    "diagnosis", "diagnoses", "follow-up", "follow up",
)

# A heading line: optional leading bullet/number, some text, an optional
# parenthetical (usually dates), then a colon at end of line.
_HEADING = re.compile(r"^[ \t]*(?:[-*•]\s*)?(?P<label>[^:\n]{2,80}):[ \t]*$", re.MULTILINE)


@dataclass(frozen=True)
class NoteSegment:
    role: str
    heading: str
    start: int
    end: int


def _role_of_heading(label: str) -> str | None:
    """The author role a heading label names, or None if it names no role.

    Longest term first so "occupational therapy" is not shadowed by a shorter
    term, and allied health is checked before physician so a "Dietitian consult
    note:" heading is allied health rather than being claimed by "consult".
    """
    lowered = label.lower()
    for role in (ALLIED_HEALTH, NURSING, PHYSICIAN):
        for term in sorted(_ROLE_TERMS[role], key=len, reverse=True):
            if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", lowered):
                return role
    # Roles are checked first so "Nursing plan:" is nursing, not a body heading.
    stripped = re.sub(r"\s*\([^)]*\)\s*", " ", lowered).strip(" 	-—:")
    if stripped in _BODY_HEADINGS:
        return UNATTRIBUTED
    return None


def segment_note(note_text: str) -> list[NoteSegment]:
    """Split `note_text` into role-tagged segments that tile it exactly."""
    boundaries: list[tuple[int, str, str]] = []  # (start, role, heading)
    for match in _HEADING.finditer(note_text):
        role = _role_of_heading(match.group("label"))
        if role is not None:
            boundaries.append((match.start(), role, match.group("label").strip()))

    if not boundaries:
        return [NoteSegment(role=UNATTRIBUTED, heading="", start=0, end=len(note_text))]

    segments: list[NoteSegment] = []
    if boundaries[0][0] > 0:
        segments.append(NoteSegment(role=UNATTRIBUTED, heading="", start=0, end=boundaries[0][0]))
    for index, (start, role, heading) in enumerate(boundaries):
        end = boundaries[index + 1][0] if index + 1 < len(boundaries) else len(note_text)
        segments.append(NoteSegment(role=role, heading=heading, start=start, end=end))
    return _merge_adjacent(segments)


def _merge_adjacent(segments: list[NoteSegment]) -> list[NoteSegment]:
    """Collapse neighbouring segments that share a role, so a run of body
    headings under one author is one span rather than a fragment per heading."""
    merged: list[NoteSegment] = []
    for segment in segments:
        if merged and merged[-1].role == segment.role:
            previous = merged.pop()
            merged.append(NoteSegment(role=previous.role, heading=previous.heading,
                                      start=previous.start, end=segment.end))
        else:
            merged.append(segment)
    return merged


def role_at(segments: list[NoteSegment], offset: int) -> str:
    """The role of the segment containing `offset` (UNATTRIBUTED if none does)."""
    for segment in segments:
        if segment.start <= offset < segment.end:
            return segment.role
    return UNATTRIBUTED
