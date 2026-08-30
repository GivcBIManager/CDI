"""Tests for cdi_kb.doctype.detect_doc_type: header phrase, SOAP-marker, and
diagnosis-list shape heuristics, falling back to "any" for free prose."""

from cdi_kb.doctype import detect_doc_type


def test_discharge_summary_header_detected() -> None:
    note = "DISCHARGE SUMMARY\nAdmitted with pneumonia, treated with antibiotics, discharged home."
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
