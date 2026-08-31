"""Note segmentation by author role.

A clinical note is not one document by one author: it carries nursing entries,
allied-health consults and specialty consult notes inline. Every check in this
KB until now treated all of that text as equally authoritative, which is the
opposite of the coding rule -- a diagnosis recorded only by a dietitian is not
the treating doctor's diagnosis.

segment_note assigns each span of the note a role so the audit can tell who
wrote what.
"""

from cdi_kb.segments import ALLIED_HEALTH, NURSING, PHYSICIAN, UNATTRIBUTED, role_at, segment_note

_NOTE = """PROGRESS NOTE — INTERNAL MEDICINE

SUBJECTIVE:
72 y/o male, still drowsy this morning but arousable.

Physical Exam:
  General: Ill-appearing.

Nursing documentation (08-26, 08-27, 08-28):
  Sacral wound assessed — Stage 3 pressure injury, present on admission.

Dietitian note (08-27):
  Assessment: Severe protein-calorie malnutrition.

Cardiology consult note (08-27):
  Impression: NSTEMI in setting of acute illness.

ASSESSMENT / PLAN:
1. UTI — on meropenem.
"""


def test_note_without_author_headings_is_one_unattributed_segment() -> None:
    note = "Patient reviewed on the ward round. Afebrile. Continue current management."
    segments = segment_note(note)
    assert [s.role for s in segments] == [UNATTRIBUTED]
    assert segments[0].start == 0
    assert segments[0].end == len(note)


def test_leading_content_before_any_heading_is_unattributed() -> None:
    # Deliberately NOT "physician": the audit must not claim a doctor wrote text
    # nobody signed. Unattributed is treated as possibly-physician downstream, so
    # a wrong guess here would silently suppress findings rather than invent them.
    segments = segment_note(_NOTE)
    assert segments[0].role == UNATTRIBUTED
    assert segments[0].start == 0


def test_nursing_heading_opens_a_nursing_segment() -> None:
    segments = segment_note(_NOTE)
    nursing = [s for s in segments if s.role == NURSING]
    assert len(nursing) == 1
    assert "Sacral wound" in _NOTE[nursing[0].start:nursing[0].end]


def test_dietitian_heading_opens_an_allied_health_segment() -> None:
    segments = segment_note(_NOTE)
    allied = [s for s in segments if s.role == ALLIED_HEALTH]
    assert len(allied) == 1
    assert "protein-calorie malnutrition" in _NOTE[allied[0].start:allied[0].end]


def test_consult_heading_opens_a_physician_segment() -> None:
    segments = segment_note(_NOTE)
    physician = [s for s in segments if s.role == PHYSICIAN]
    assert len(physician) == 1
    assert "NSTEMI" in _NOTE[physician[0].start:physician[0].end]


def test_a_segment_ends_where_the_next_author_heading_begins() -> None:
    segments = segment_note(_NOTE)
    allied = next(s for s in segments if s.role == ALLIED_HEALTH)
    body = _NOTE[allied.start:allied.end]
    assert "malnutrition" in body
    assert "NSTEMI" not in body, "the allied-health segment ran into the cardiology consult"


def test_segments_tile_the_note_without_gaps_or_overlap() -> None:
    segments = segment_note(_NOTE)
    assert segments[0].start == 0
    assert segments[-1].end == len(_NOTE)
    for earlier, later in zip(segments, segments[1:]):
        assert earlier.end == later.start


def test_a_non_author_heading_does_not_start_a_new_segment() -> None:
    # "Physical Exam:" names a topic, not an author. Splitting on it would
    # fragment the note and strand mentions in segments with no role meaning.
    segments = segment_note(_NOTE)
    first = segments[0]
    assert "Physical Exam:" in _NOTE[first.start:first.end]


def test_role_at_reports_the_role_of_the_segment_containing_an_offset() -> None:
    segments = segment_note(_NOTE)
    assert role_at(segments, _NOTE.index("protein-calorie")) == ALLIED_HEALTH
    assert role_at(segments, _NOTE.index("Sacral")) == NURSING
    assert role_at(segments, _NOTE.index("NSTEMI")) == PHYSICIAN
    assert role_at(segments, _NOTE.index("72 y/o")) == UNATTRIBUTED


def test_trailing_assessment_plan_returns_to_the_note_author() -> None:
    # "ASSESSMENT / PLAN:" is a structural heading of the note's own body, so it
    # ends the inline cardiology consult and returns the note to its own writer.
    # Without this the treating doctor's plan reads as the consultant's
    # documentation, and a diagnosis the doctor DID record raises a false
    # provider-confirmation finding -- on the commonest note shape there is.
    segments = segment_note(_NOTE)
    assert role_at(segments, _NOTE.index("1. UTI")) == UNATTRIBUTED
