"""Tests for doc-type completeness rules: schema (Element/DocTypeRequirement/
load_doc_requirements), the shared citation firewall (_verified_citations /
compose_element_finding), element-gap detection (doc_gaps.find_element_gaps),
and the end-to-end audit wiring."""

from pathlib import Path

import pytest

from cdi_kb import config
from cdi_kb.audit import run_audit
from cdi_kb.clauses import Clause, ClauseStore
from cdi_kb.doc_gaps import find_element_gaps
from cdi_kb.findings import compose_element_finding
from cdi_kb.requirements_model import Citation, DocTypeRequirement, Element, load_doc_requirements

CLAUSE = Clause(
    "CDI-2021/discharge-summary/p9", "Discharge Summary", 67,
    "Documentation of follow-up care is mandatory. This includes dates and times of "
    "appointments booked, or who is responsible for booking, with a timeframe provided.",
)


def _store(tmp_path: Path, clauses: list[Clause]) -> ClauseStore:
    store = ClauseStore(tmp_path / "kb.sqlite")
    store.rebuild(clauses)
    return store


def _element(quote: str) -> Element:
    return Element(
        name="follow_up_plan",
        evidence_terms=["follow up", "follow-up"],
        level="required",
        recommendation="Document the follow-up plan.",
        citations=[Citation(clause_id="CDI-2021/discharge-summary/p9", quote=quote)],
    )


# --- schema ---------------------------------------------------------------

def test_load_doc_requirements_keyed_by_doc_type() -> None:
    reqs = load_doc_requirements(config.DOC_REQUIREMENTS_DIR)
    assert "discharge_summary" in reqs
    entry = reqs["discharge_summary"]
    assert entry.doc_type == "discharge_summary"
    assert 3 <= len(entry.elements) <= 8
    for element in entry.elements:
        assert element.citations
        assert element.evidence_terms


def test_all_five_doc_types_present() -> None:
    reqs = load_doc_requirements(config.DOC_REQUIREMENTS_DIR)
    for doc_type in ("discharge_summary", "admission_note", "progress_note",
                      "emergency_note", "diagnosis_list"):
        assert doc_type in reqs, f"missing doc requirement file for {doc_type}"


def test_invalid_doc_requirement_file_rejected(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("doc_type: discharge_summary\nelements: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.yaml"):
        load_doc_requirements(tmp_path)


# Single common English/clinical words as lone evidence terms are prone to
# matching ordinary, unrelated text and silently suppressing a real
# completeness gap (e.g. bare "observations" or "procedure" -- see the
# reviewer fixes that tightened the 19 elements above). This allowlist is the
# ONLY escape hatch from the specificity rule enforced below: every entry
# must be a genuinely distinctive clinical term/acronym/compound, never an
# ordinary English word, and carries its own justification comment.
ALLOWED_SINGLE_WORD_TERMS = {
    "hopc",            # History Of Presenting Complaint -- a specific clinical acronym, not ordinary English
    "pdx",             # Principal Diagnosis acronym (booklet's own "PDx") -- not ordinary English
    "adx",             # Additional Diagnosis acronym (booklet's own "ADx") -- not ordinary English
    "comorbidities",   # specific clinical concept term, not a generic filler word
    "co-morbidities",  # hyphenated variant spelling of the above
    "operative",       # specific to surgical/procedural documentation ("operative note", "post-operative")
    "follow-up",       # hyphenated compound clinical term; distinct from (and needed alongside) the
                       # two-word "follow up" term -- the \s+-joined pattern for "follow up" requires
                       # literal whitespace between the words and does NOT also match the hyphenated
                       # spelling, so both variants are carried for recall
    # Wave 3 (reviewer fix): realistic shorthand-note evidence terms added to widen
    # completeness detection past booklet vocabulary. Every entry below is a specific
    # clinical acronym/shorthand token, never an ordinary English word.
    "hpc",             # History Presenting Complaint -- clinical acronym, not ordinary English
    "hpi",             # History of Present Illness -- clinical acronym, not ordinary English
    "pmh",             # Past Medical History -- clinical acronym, not ordinary English
    "pmhx",            # Past Medical History (x-suffixed variant spelling) -- clinical acronym
    "edd",             # Estimated Date of Discharge -- clinical acronym, not ordinary English
    "f/u",             # Follow-Up -- clinical shorthand token (slash form), not ordinary English
    "opd",             # Outpatient Department -- clinical acronym, not ordinary English
    "outpatient",      # specific to non-inpatient clinic care, not a generic filler word
    "ddx",             # Differential Diagnosis -- clinical acronym, not ordinary English
    "handover",        # specific to clinical handoff of patient care, not a generic filler word
}


def test_no_over_broad_single_word_evidence_terms() -> None:
    """Structural guard: every evidence term must be EITHER multi-word
    (contains whitespace -- e.g. "care plan"), OR colon-anchored (ends with
    ":" -- e.g. "plan:"), OR an explicitly justified single-word token in
    ALLOWED_SINGLE_WORD_TERMS. No length-based exception: a bare single
    common word can never slip through this guard merely by being long."""
    offenders: list[str] = []
    for doc_type, doc_req in load_doc_requirements(config.DOC_REQUIREMENTS_DIR).items():
        for element in doc_req.elements:
            for term in element.evidence_terms:
                if len(term.split()) > 1:
                    continue  # multi-word: inherently more specific
                if term.endswith(":"):
                    continue  # colon-anchored: inherently more specific
                if term.lower() in ALLOWED_SINGLE_WORD_TERMS:
                    continue
                offenders.append(f"{doc_type}|{element.name}: {term!r}")
    assert not offenders, offenders


# --- empirical detection (realistic snippets, wave-2 reviewer fix) ---------

def test_procedures_operations_detects_colon_header() -> None:
    doc_req = load_doc_requirements(config.DOC_REQUIREMENTS_DIR)["discharge_summary"]
    gaps = find_element_gaps("Procedures: Laparoscopic appendicectomy performed on Day 2.", doc_req)
    assert "procedures_operations" not in {e.name for e in gaps}


def test_procedures_operations_does_not_fire_on_unrelated_underwent() -> None:
    doc_req = load_doc_requirements(config.DOC_REQUIREMENTS_DIR)["discharge_summary"]
    gaps = find_element_gaps("Patient underwent CT scan of the abdomen.", doc_req)
    assert "procedures_operations" in {e.name for e in gaps}


def test_wellbeing_observations_detects_behaviour_header() -> None:
    doc_req = load_doc_requirements(config.DOC_REQUIREMENTS_DIR)["progress_note"]
    gaps = find_element_gaps("Behaviour: settled and cooperative.", doc_req)
    assert "wellbeing_observations" not in {e.name for e in gaps}


def test_causal_linkage_does_not_fire_on_unrelated_complicating() -> None:
    doc_req = load_doc_requirements(config.DOC_REQUIREMENTS_DIR)["diagnosis_list"]
    gaps = find_element_gaps("Type 2 diabetes complicating wound healing.", doc_req)
    assert "causal_linkage" in {e.name for e in gaps}


# --- firewall ---------------------------------------------------------------

def test_element_with_verified_citation_produces_finding(tmp_path) -> None:
    finding = compose_element_finding(
        "discharge_summary", _element("Documentation of follow-up care is mandatory."),
        _store(tmp_path, [CLAUSE]),
    )
    assert finding is not None
    assert finding.finding_type == "completeness_gap"
    assert finding.condition == "discharge_summary"
    assert finding.axis == "follow_up_plan"
    assert finding.severity == "required"
    assert finding.evidence_excerpt == "discharge_summary (element not found)"
    assert finding.dedupe_key == "discharge_summary|follow_up_plan"
    assert finding.citations[0].clause_id == "CDI-2021/discharge-summary/p9"


def test_element_with_fabricated_quote_yields_no_finding(tmp_path) -> None:
    # The firewall: a quote not in the clause text must kill the finding entirely.
    finding = compose_element_finding(
        "discharge_summary", _element("clinicians must always call the patient after discharge"),
        _store(tmp_path, [CLAUSE]),
    )
    assert finding is None


def test_element_with_unresolvable_clause_id_yields_no_finding(tmp_path) -> None:
    finding = compose_element_finding(
        "discharge_summary", _element("Documentation of follow-up care is mandatory."),
        _store(tmp_path, []),
    )
    assert finding is None


def test_element_recommended_severity_branch(tmp_path) -> None:
    element = Element(
        name="medications_on_discharge", evidence_terms=["medications on discharge"],
        level="recommended", recommendation="r",
        citations=[Citation(clause_id="CDI-2021/discharge-summary/p9", quote="follow-up care is mandatory")],
    )
    finding = compose_element_finding("discharge_summary", element, _store(tmp_path, [CLAUSE]))
    assert finding is not None
    assert finding.severity == "recommended"


# --- detection ---------------------------------------------------------------

def _doc_req() -> DocTypeRequirement:
    return DocTypeRequirement(doc_type="discharge_summary", elements=[
        Element(name="follow_up_plan",
                evidence_terms=["follow up", "follow-up", "review in", "clinic appointment"],
                level="required", recommendation="r",
                citations=[Citation(clause_id="x/p1", quote="q")]),
        Element(name="medications_on_discharge", evidence_terms=["medications on discharge"],
                level="recommended", recommendation="r",
                citations=[Citation(clause_id="x/p1", quote="q")]),
    ])


def test_find_element_gaps_detects_missing_and_present_elements() -> None:
    doc_req = _doc_req()
    note = "Patient discharged home. Medications on discharge: amoxicillin 500mg."
    gaps = find_element_gaps(note, doc_req)
    names = {e.name for e in gaps}
    assert "follow_up_plan" in names
    assert "medications_on_discharge" not in names


def test_find_element_gaps_wrap_tolerant_multi_word_term() -> None:
    doc_req = _doc_req()
    # "Medications on\ndischarge" wraps across a line break, and "Follow up" is present.
    note = "Medications on\ndischarge: amoxicillin. Follow up in clinic in 2 weeks."
    assert find_element_gaps(note, doc_req) == []


def test_find_element_gaps_all_missing_when_no_evidence() -> None:
    doc_req = _doc_req()
    note = "Patient stable, observations within normal limits."
    gaps = find_element_gaps(note, doc_req)
    assert {e.name for e in gaps} == {"follow_up_plan", "medications_on_discharge"}


# --- integration (run_audit wiring) ------------------------------------------

_DISCHARGE_NOTE = (
    "DISCHARGE SUMMARY\n"
    "Admitted with community acquired pneumonia. Principal diagnosis: pneumonia.\n"
    "Procedure performed: chest tube insertion in theatre.\n"
    "Medications on discharge: amoxicillin 500mg TDS for 5 days.\n"
)


def test_discharge_summary_note_missing_follow_up_yields_completeness_finding() -> None:
    result = run_audit(_DISCHARGE_NOTE)
    assert result.active_doc_type == "discharge_summary"
    matches = [f for f in result.findings if f.dedupe_key == "discharge_summary|follow_up_plan"]
    assert matches, [f.dedupe_key for f in result.findings]
    assert matches[0].finding_type == "completeness_gap"
    assert matches[0].citations


def test_same_body_as_progress_note_yields_no_discharge_summary_findings() -> None:
    result = run_audit(_DISCHARGE_NOTE, doc_type="progress_note")
    assert result.active_doc_type == "progress_note"
    assert not any(f.dedupe_key.startswith("discharge_summary|") for f in result.findings)


def test_any_doc_type_yields_no_completeness_gap_findings() -> None:
    # Free prose that auto-detects as "any" must never raise element-completeness
    # findings -- there is no DocTypeRequirement keyed by "any".
    result = run_audit(
        "62M admitted with fluid overload. Background: hypertension, CKD, ex-smoker. "
        "On furosemide. Creatinine 210 on admission bloods. Plan: daily weights, renal profile."
    )
    assert result.active_doc_type == "any"
    assert not any(f.finding_type == "completeness_gap" for f in result.findings)


# --- Important 3: realistic shorthand notes must not fire required completeness
# gaps just because they use note vocabulary instead of booklet vocabulary ------

def _required_completeness_findings(result) -> list:
    return [f for f in result.findings if f.finding_type == "completeness_gap" and f.severity == "required"]


def test_shorthand_admission_note_yields_no_required_completeness_findings() -> None:
    note = (
        "Admission Note\n"
        "HPC: Central chest pain, onset 2 hours ago, radiating to left arm.\n"
        "PMH: Hypertension, type 2 diabetes mellitus.\n"
        "Impression: Unstable angina, admit for cardiology workup.\n"
        "D/C planning: anticipate discharge home in 3-4 days with GP follow-up.\n"
    )
    result = run_audit(note, doc_type="admission_note")
    findings = _required_completeness_findings(result)
    assert findings == [], [f.dedupe_key for f in findings]


def test_shorthand_emergency_note_yields_no_required_completeness_findings() -> None:
    note = (
        "Emergency Department note\n"
        "PC: Chest pain and shortness of breath, onset 1 hour ago.\n"
        "Triage cat 2.\n"
        "Obs: HR 110, BP 100/70, SpO2 94% on room air.\n"
        "DDx: Acute coronary syndrome, pulmonary embolism.\n"
        "Impression: likely ACS.\n"
        "Disposition: admit under cardiology.\n"
        "Handed over to CCU team at 14:00.\n"
    )
    result = run_audit(note, doc_type="emergency_note")
    findings = _required_completeness_findings(result)
    assert findings == [], [f.dedupe_key for f in findings]


def test_shorthand_discharge_summary_with_dx_and_fu_yields_no_required_completeness_findings() -> None:
    note = (
        "Discharge Summary\n"
        "Dx: ST-elevation myocardial infarction.\n"
        "Procedure performed: PCI to LAD in the cath lab.\n"
        "Meds on discharge: aspirin 75mg OD, clopidogrel 75mg OD, atorvastatin 80mg ON.\n"
        "F/U: cardiology clinic in 6 weeks.\n"
    )
    result = run_audit(note, doc_type="discharge_summary")
    findings = _required_completeness_findings(result)
    assert findings == [], [f.dedupe_key for f in findings]


def test_shorthand_discharge_summary_with_gp_and_opd_yields_no_required_completeness_findings() -> None:
    note = (
        "DISCHARGE SUMMARY\n"
        "Diagnosis: Community acquired pneumonia.\n"
        "Procedures: none during this admission.\n"
        "Medications: amoxicillin 500mg TDS for 5 days.\n"
        "GP to see patient in one week; respiratory OPD booked.\n"
    )
    result = run_audit(note, doc_type="discharge_summary")
    findings = _required_completeness_findings(result)
    assert findings == [], [f.dedupe_key for f in findings]


# --- Important 4: soap_structure must not fire on a genuine SOAP-structured note ---

def test_soap_structure_does_not_fire_on_labs_colon_false_boundary() -> None:
    """Regression: "Labs:" must NOT satisfy the "s:" evidence term -- the character
    immediately before "s" is "b" (alphanumeric), so gapcheck.term_pattern's
    word-boundary lookbehind correctly rejects it."""
    doc_req = load_doc_requirements(config.DOC_REQUIREMENTS_DIR)["progress_note"]
    gaps = find_element_gaps("Labs: normal.", doc_req)
    assert "soap_structure" in {e.name for e in gaps}


def test_soap_structure_satisfied_by_single_letter_soap_note() -> None:
    note = (
        "S: Patient reports feeling better today.\n"
        "O: Afebrile, vitals stable.\n"
        "A: Community acquired pneumonia, improving.\n"
        "P: Continue current antibiotic course.\n"
    )
    doc_req = load_doc_requirements(config.DOC_REQUIREMENTS_DIR)["progress_note"]
    gaps = find_element_gaps(note, doc_req)
    assert "soap_structure" not in {e.name for e in gaps}


def test_run_audit_soap_note_yields_no_soap_structure_finding() -> None:
    note = (
        "S: Patient reports feeling better today, appetite improving.\n"
        "O: Afebrile, vitals stable, chest clear on auscultation.\n"
        "A: Community acquired pneumonia, improving on antibiotics.\n"
        "P: Continue current antibiotic course, reassess tomorrow.\n"
    )
    result = run_audit(note)
    assert result.active_doc_type == "progress_note"
    assert not any(f.dedupe_key == "progress_note|soap_structure" for f in result.findings)
