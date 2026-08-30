"""Tests for cdi_kb.doctype.detect_doc_type: header phrase, SOAP-marker, and
diagnosis-list shape heuristics, falling back to "any" for free prose."""

from cdi_kb import config
from cdi_kb.doctype import detect_doc_type
from cdi_kb.requirements_model import AxisRule, Citation, DiagnosisRequirement, load_requirements


def test_discharge_summary_header_detected() -> None:
    note = "DISCHARGE SUMMARY\nAdmitted with pneumonia, treated with antibiotics, discharged home."
    assert detect_doc_type(note) == "discharge_summary"


def test_repeated_header_marker_chars_stripped() -> None:
    """Regression: a repeated marker prefix (e.g. Markdown "## " or "** ")
    must be stripped entirely, not just a single leading character."""
    note = "## Discharge Summary\nAdmitted with pneumonia, treated with antibiotics, discharged home."
    assert detect_doc_type(note) == "discharge_summary"


def test_progress_note_header_with_soap_body_detected() -> None:
    note = (
        "Progress Note\n"
        "S: Patient reports feeling better today, appetite improving.\n"
        "O: Afebrile, vitals stable, chest clear on auscultation.\n"
        "A: Community acquired pneumonia, improving on antibiotics.\n"
        "P: Continue current antibiotic course, reassess tomorrow.\n"
    )
    assert detect_doc_type(note) == "progress_note"


def test_soap_markers_without_title_detected_as_progress_note() -> None:
    note = (
        "S: Patient reports feeling better today, appetite improving well.\n"
        "O: Afebrile, vitals stable, chest clear on auscultation exam.\n"
        "A: Community acquired pneumonia, improving on antibiotics course.\n"
        "P: Continue current antibiotic course, reassess again tomorrow.\n"
    )
    assert detect_doc_type(note) == "progress_note"


def test_numbered_short_lines_detected_as_diagnosis_list() -> None:
    note = "1. CKD stage 4\n2. Anemia\n3. T2DM"
    assert detect_doc_type(note) == "diagnosis_list"


def test_free_prose_falls_back_to_any() -> None:
    note = (
        "62M admitted with fluid overload. Background: hypertension, CKD followed by\n"
        "nephrology, ex-smoker. On furosemide. Creatinine 210 on admission bloods.\n"
        "Plan: daily weights, renal profile, medication review."
    )
    assert detect_doc_type(note) == "any"


def test_explicit_emergency_department_header_detected() -> None:
    note = "Emergency Department note\nPatient presents with chest pain and shortness of breath."
    assert detect_doc_type(note) == "emergency_note"


def test_admission_note_header_detected() -> None:
    note = "Admission Note\nPatient admitted for management of sepsis secondary to pneumonia."
    assert detect_doc_type(note) == "admission_note"


def test_empty_note_falls_back_to_any() -> None:
    assert detect_doc_type("") == "any"


def test_terse_short_prose_not_misdetected_as_diagnosis_list() -> None:
    """Regression: short unrelated sentences (not a numbered/bulleted list, no
    known condition terms) must not trip the diagnosis-list shape heuristic
    merely because they are all short lines."""
    note = "Pt seen today.\nStable.\nNo new complaints."
    assert detect_doc_type(note) == "any"


def test_diagnosis_list_via_known_condition_terms_when_requirements_supplied() -> None:
    reqs = [
        DiagnosisRequirement(
            condition="chronic kidney disease", synonyms=["CKD"],
            axes=[AxisRule(axis="stage", level="required", evidence_terms=["stage 4"])],
            recommendation="r", citations=[Citation(clause_id="CDI-2021/x/p1", quote="q")],
        ),
        DiagnosisRequirement(
            condition="anemia", synonyms=["anaemia"],
            axes=[AxisRule(axis="type", level="required", evidence_terms=["iron deficiency"])],
            recommendation="r", citations=[Citation(clause_id="CDI-2021/x/p1", quote="q")],
        ),
    ]
    note = "Chronic kidney disease\nAnemia\nHypertension"
    assert detect_doc_type(note, requirements=reqs) == "diagnosis_list"
    # Without the catalogue, the same note falls back to digit/bullet-only and
    # does not qualify (none of the lines are numbered or bulleted).
    assert detect_doc_type(note) == "any"


# --- Important 1: header match must not over-match sentence-like first lines ---

def test_sentence_like_ed_line_not_misdetected_as_header() -> None:
    """Regression: a full sentence that happens to start with a header phrase
    but reads as prose (ends with a sentence period) must not be misdetected
    as a header -- it previously typed this note as emergency_note, raising 4
    false required completeness findings."""
    note = "Emergency department attendance overnight with chest pain, now admitted to CCU."
    assert detect_doc_type(note) == "any"


def test_sentence_like_discharge_summary_line_not_misdetected_as_header() -> None:
    note = "Discharge summary from previous admission reviewed."
    assert detect_doc_type(note) == "any"


def test_title_like_progress_note_with_day_count_still_detected() -> None:
    assert detect_doc_type("Progress Note - Day 3\nPatient stable overnight.") == "progress_note"


def test_title_like_discharge_summary_with_parenthetical_still_detected() -> None:
    note = "Discharge Summary (Final)\nAdmitted with pneumonia, treated with antibiotics, discharged home."
    assert detect_doc_type(note) == "discharge_summary"


def test_title_like_admission_note_with_date_still_detected() -> None:
    note = "Admission note 12/08/2026\nPatient admitted for management of sepsis secondary to pneumonia."
    assert detect_doc_type(note) == "admission_note"


def test_markdown_discharge_summary_header_still_detected() -> None:
    note = "## Discharge Summary\nAdmitted with pneumonia, treated with antibiotics, discharged home."
    assert detect_doc_type(note) == "discharge_summary"


# --- Important 2: numbered plans/med lists must not be misdetected as diagnosis_list ---

def test_numbered_plan_with_catalogue_not_misdetected_as_diagnosis_list() -> None:
    """Regression: a numbered plan has the exact shape of a diagnosis list
    (short, numbered lines) but names no catalogue condition -- with the real
    requirements catalogue supplied (as run_audit does), this must fall back
    to "any", not diagnosis_list."""
    note = (
        "Plan:\n"
        "1. Continue IV antibiotics\n"
        "2. Repeat CXR tomorrow\n"
        "3. Physio review\n"
        "4. Discharge planning meeting Friday"
    )
    reqs = load_requirements(config.REQUIREMENTS_DIR)
    assert detect_doc_type(note, requirements=reqs) == "any"


def test_numbered_medication_list_with_catalogue_not_misdetected_as_diagnosis_list() -> None:
    note = (
        "Medications:\n"
        "1. Metformin 500mg BD\n"
        "2. Amlodipine 5mg OD\n"
        "3. Atorvastatin 20mg ON\n"
        "4. Aspirin 75mg OD"
    )
    reqs = load_requirements(config.REQUIREMENTS_DIR)
    assert detect_doc_type(note, requirements=reqs) == "any"


def test_numbered_known_conditions_still_detected_as_diagnosis_list_with_catalogue() -> None:
    """A numbered list that DOES name catalogue conditions must still be
    detected as diagnosis_list even with the real catalogue supplied."""
    note = "1. CKD stage 4\n2. Anemia\n3. T2DM"
    reqs = load_requirements(config.REQUIREMENTS_DIR)
    assert detect_doc_type(note, requirements=reqs) == "diagnosis_list"


def test_header_phrase_mid_sentence_is_not_a_header_match() -> None:
    """Regression: a header phrase must be line-anchored (first two non-empty
    lines only, the line itself naming the doc type) -- a prose sentence that
    merely mentions e.g. "emergency department" must not be misdetected."""
    note = (
        "66M presented to the emergency department with central chest pain radiating\n"
        "to the left arm, associated with diaphoresis and nausea, onset two hours\n"
        "prior to arrival. Background: hypertension, hyperlipidemia, ex-smoker."
    )
    assert detect_doc_type(note) == "any"


# Task 8: 8 notes (discharge-summary-*, diagnosis-list-*, necessity-hba1c-*,
# necessity-b12-*) are intentionally typed/necessity fixtures -- see
# test_eval_suite._TYPED_NOTE_PREFIXES. Excluded here by filename prefix so
# this guard keeps covering exactly the original 40 free-prose notes.
_TYPED_NOTE_PREFIXES = ("discharge-summary-", "diagnosis-list-", "necessity-hba1c-", "necessity-b12-")


def test_all_eval_notes_detect_as_any() -> None:
    """Corpus-level guard: the original 40 eval notes are prose gap/control
    notes with no headers, SOAP markers, or diagnosis-list shape -- every one
    must detect as "any" so applies_to-scoped rules (default ["any"]) behave
    identically to before doc-type detection existed."""
    notes_dir = config.EVAL_DIR / "notes"
    misclassified = []
    for path in sorted(notes_dir.glob("*.txt")):
        if path.name.startswith(_TYPED_NOTE_PREFIXES):
            continue
        detected = detect_doc_type(path.read_text(encoding="utf-8"))
        if detected != "any":
            misclassified.append(f"{path.name} -> {detected}")
    assert not misclassified, "\n".join(misclassified)
