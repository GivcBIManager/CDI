from cdi_kb.gapcheck import detect_conditions, find_gaps, scan_axes
from cdi_kb.requirements_model import AxisRule, Citation, DiagnosisRequirement

CKD = DiagnosisRequirement(
    condition="chronic kidney disease",
    synonyms=["CKD", "chronic renal failure"],
    axes=[AxisRule(axis="stage", level="required",
                   evidence_terms=["stage 1", "stage 2", "stage 3", "stage 3a", "stage 3b", "stage 4", "stage 5", "esrd"])],
    recommendation="CKD is documented without a stage. Please document the stage, if known.",
    citations=[Citation(clause_id="CDI-2021/x/p1", quote="q")],
)


def test_detects_condition_via_synonym_case_insensitive() -> None:
    mentions = detect_conditions("Known CKD, on follow-up.", [CKD])
    assert len(mentions) == 1
    assert mentions[0].condition == "chronic kidney disease"
    assert not mentions[0].negated


def test_word_boundary_no_substring_hits() -> None:
    assert detect_conditions("Buckderm cream applied.", [CKD]) == []  # 'ckd' inside a word


def test_negation_window_suppresses() -> None:
    mentions = detect_conditions("No evidence of chronic kidney disease.", [CKD])
    assert len(mentions) == 1 and mentions[0].negated


def test_axis_present_when_evidence_term_found() -> None:
    assert scan_axes("CKD stage 4 secondary to diabetes", CKD) == {"stage"}


def test_gap_raised_when_required_axis_absent() -> None:
    gaps = find_gaps("Patient has CKD, on regular follow-up.", [CKD])
    assert [(g.condition, g.axis, g.level) for g in gaps] == [("chronic kidney disease", "stage", "required")]


def test_no_gap_when_axis_documented_or_condition_negated() -> None:
    assert find_gaps("CKD stage 3b, stable.", [CKD]) == []
    assert find_gaps("Denies chronic kidney disease.", [CKD]) == []


def test_negation_cue_in_word_does_not_falsely_negate() -> None:
    """Regression: 'albino' contains 'no', but should not trigger negation."""
    gaps = find_gaps("Patient has albino complexion; chronic kidney disease under review.", [CKD])
    # Should find a gap because CKD is NOT negated (the "no" is inside "albino")
    assert len(gaps) == 1
    assert gaps[0].axis == "stage"
    assert not gaps[0].mention.negated


def test_negation_window_still_suppresses_legitimate_negation() -> None:
    """Verify 'No evidence of' still triggers negation correctly."""
    mentions = detect_conditions("No evidence of chronic kidney disease.", [CKD])
    assert len(mentions) == 1 and mentions[0].negated


def test_cannot_exclude_does_not_trigger_not_cue() -> None:
    """Regression: 'cannot' contains 'not' but should not falsely negate."""
    gaps = find_gaps("Cannot exclude chronic kidney disease.", [CKD])
    # Should find a gap because "cannot" does not match the "not " cue (word boundary)
    assert len(gaps) == 1
    assert gaps[0].axis == "stage"
    assert not gaps[0].mention.negated
