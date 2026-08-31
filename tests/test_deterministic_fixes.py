"""Fixes for the four deterministic defects found by auditing a real
internal-medicine progress note (see the comparison in that session):

1. `ARF` abbreviation collision -- claimed by acute respiratory failure only,
   so "ARF - creatinine trending up" produced a respiratory finding and no
   renal one.
2. `pressure injury|site` fired on "Sacral wound" because the evidence term
   was `sacrum`.
3. `recommendation` is condition-level, so a `missing site` finding printed the
   *agent* advice ("document the infective agent") for an organism the note
   already documented.
4. `presenting_complaint_management` matched only the booklet's own vocabulary
   ("presenting complaint", "co-morbidities"), so a note with a twelve-item
   assessment/plan still reported the element missing.
"""

import pytest

from cdi_kb import config
from cdi_kb.audit import run_audit
from cdi_kb.doc_gaps import find_element_gaps
from cdi_kb.gapcheck import detect_conditions
from cdi_kb.requirements_model import load_doc_requirements, load_requirements


@pytest.fixture()
def requirements():
    return load_requirements(config.REQUIREMENTS_DIR)


# --- 1. ARF abbreviation collision -----------------------------------------

def test_arf_in_renal_context_detects_acute_kidney_injury(requirements) -> None:
    note = "2. ARF — creatinine trending up. Hold nephrotoxics, gentle fluids. Renal to see."
    detected = {m.condition for m in detect_conditions(note, requirements)}
    assert "acute kidney injury" in detected


def test_arf_in_renal_context_does_not_detect_acute_respiratory_failure(requirements) -> None:
    note = "2. ARF — creatinine trending up. Hold nephrotoxics, gentle fluids. Renal to see."
    detected = {m.condition for m in detect_conditions(note, requirements)}
    assert "acute respiratory failure" not in detected


def test_arf_in_respiratory_context_detects_acute_respiratory_failure(requirements) -> None:
    note = ("Arterial blood gas shows a low pO2. The team documents ARF and "
            "commences oxygen therapy.")
    detected = {m.condition for m in detect_conditions(note, requirements)}
    assert "acute respiratory failure" in detected


def test_arf_in_respiratory_context_does_not_detect_acute_kidney_injury(requirements) -> None:
    note = ("Arterial blood gas shows a low pO2. The team documents ARF and "
            "commences oxygen therapy.")
    detected = {m.condition for m in detect_conditions(note, requirements)}
    assert "acute kidney injury" not in detected


def test_bare_arf_with_no_disambiguating_cue_detects_neither(requirements) -> None:
    # Assigning an ambiguous abbreviation to the wrong organ system sends the
    # clinician a query about a condition the patient may not have. With no cue
    # either way, raising nothing is the safer failure -- and the note is then
    # a candidate for the LLM stage, which reads context rather than tokens.
    note = "Impression: ARF. Will review tomorrow."
    detected = {m.condition for m in detect_conditions(note, requirements)}
    assert "acute kidney injury" not in detected
    assert "acute respiratory failure" not in detected


def test_unambiguous_synonyms_are_unaffected_by_the_cue_requirement(requirements) -> None:
    # Only the terms declared ambiguous need a cue; ordinary synonyms must keep
    # matching on their own.
    note = "Impression: acute renal failure. Will review tomorrow."
    detected = {m.condition for m in detect_conditions(note, requirements)}
    assert "acute kidney injury" in detected


# --- 2. pressure injury site: "sacral" ------------------------------------

def test_sacral_pressure_injury_does_not_fire_a_site_gap() -> None:
    note = ("Progress Note\nS: comfortable.\nO: Sacral wound assessed — full thickness, "
            "Stage 3 pressure injury, present on admission.\nA: stable.\nP: continue care.")
    result = run_audit(note)
    assert "pressure injury|site" not in {f.dedupe_key for f in result.findings}


def test_pressure_injury_site_still_fires_when_no_site_is_documented() -> None:
    note = ("Progress Note\nS: comfortable.\nO: Stage 3 pressure injury noted, present on "
            "admission.\nA: stable.\nP: continue care.")
    result = run_audit(note)
    assert "pressure injury|site" in {f.dedupe_key for f in result.findings}


# --- 3. axis-level recommendation -----------------------------------------

def test_uti_site_finding_recommends_documenting_the_site_not_the_organism() -> None:
    note = "Progress Note\nS: dysuria.\nO: urine culture grew E. coli.\nA: UTI.\nP: antibiotics."
    result = run_audit(note)
    site = [f for f in result.findings if f.dedupe_key == "urinary tract infection|site"]
    assert site, "the site axis should still fire -- upper vs lower UTI is undocumented"
    text = site[0].recommendation.lower()
    assert "pyelonephritis" in text or "upper" in text
    assert "infective agent" not in text


def test_condition_level_recommendation_still_used_when_an_axis_has_none() -> None:
    note = "Progress Note\nS: tired.\nO: Hgb 7.8, transfused 2 units.\nA: Anemia.\nP: monitor."
    result = run_audit(note)
    anemia = [f for f in result.findings if f.dedupe_key == "anemia|type"]
    assert anemia
    assert "type of anemia" in anemia[0].recommendation.lower()


# --- 4. presenting_complaint_management -----------------------------------

def test_presenting_complaint_management_satisfied_by_a_documented_plan() -> None:
    note = (
        "ASSESSMENT / PLAN:\n"
        "1. UTI — on meropenem, cultures growing E. coli. Continue abx.\n"
        "2. CHF — LVEF 30% on echo. Continue diuresis.\n"
        "3. Hypertension — antihypertensives held.\n"
    )
    doc_req = load_doc_requirements(config.DOC_REQUIREMENTS_DIR)["progress_note"]
    gaps = {e.name for e in find_element_gaps(note, doc_req)}
    assert "presenting_complaint_management" not in gaps


def test_presenting_complaint_management_still_fires_without_documented_actions() -> None:
    note = "Patient seen on the ward round. Afebrile. Chest clear. Abdomen soft, non-tender."
    doc_req = load_doc_requirements(config.DOC_REQUIREMENTS_DIR)["progress_note"]
    gaps = {e.name for e in find_element_gaps(note, doc_req)}
    assert "presenting_complaint_management" in gaps
