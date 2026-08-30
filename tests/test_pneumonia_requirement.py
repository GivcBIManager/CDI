"""Pneumonia requirement entry (data/requirements/pneumonia.yaml) exercised against
the real catalogue, so a regression in the CHI-LRTI-derived synonyms, evidence
terms, severity axis, or citations is caught by the offline suite."""

from cdi_kb import config
from cdi_kb.gapcheck import detect_conditions, find_gaps, scan_axes
from cdi_kb.requirements_model import DiagnosisRequirement, load_requirements


def _pneumonia() -> DiagnosisRequirement:
    entries = load_requirements(config.REQUIREMENTS_DIR)
    return next(entry for entry in entries if entry.condition == "pneumonia")


def _pneumonia_mentions(note: str) -> list:
    return [m for m in detect_conditions(note, [_pneumonia()]) if m.condition == "pneumonia"]


def test_bare_onset_modifiers_are_not_pneumonia_synonyms() -> None:
    # "hospital acquired", "nosocomial", "aspiration", "community acquired" qualify many
    # conditions (a hospital-acquired UTI, a joint aspiration). On their own they must
    # never make the catalogue think pneumonia was mentioned -- a false-finding path.
    for note in (
        "Hospital acquired urinary tract infection, treated with nitrofurantoin.",
        "Nosocomial infection surveillance swab sent.",
        "Knee joint aspiration performed under aseptic technique.",
        "Community acquired MRSA skin infection of the left forearm.",
    ):
        assert _pneumonia_mentions(note) == [], note


def test_chi_lrti_acronyms_and_phrases_detect_pneumonia() -> None:
    for note in (
        "Diagnosis: VAP, day 5 of ventilation.",
        "Ventilator-associated pneumonia suspected.",
        "Lower respiratory infection on admission.",
    ):
        assert len(_pneumonia_mentions(note)) == 1, note


def test_hyphenated_onset_phrasing_satisfies_onset_axis() -> None:
    req = _pneumonia()
    assert "onset" in scan_axes("Community-acquired pneumonia, right lower lobe.", req)
    assert "onset" in scan_axes("Hospital-acquired pneumonia developed on day 6.", req)
    assert "onset" in scan_axes("Ventilator-associated pneumonia.", req)


def test_chi_lrti_organisms_satisfy_agent_axis() -> None:
    req = _pneumonia()
    assert "agent" in scan_axes("HAP, sputum grew MRSA.", req)
    assert "agent" in scan_axes("VAP with P. aeruginosa isolated on BAL.", req)


def test_severity_axis_is_recommended_and_satisfied_by_severity_terms() -> None:
    req = _pneumonia()
    type_rule = next(rule for rule in req.axes if rule.axis == "type")
    assert type_rule.level == "recommended"
    assert "type" in scan_axes("Severe community-acquired pneumonia, admitted to ICU.", req)
    assert "type" in scan_axes("Non-severe community acquired pneumonia, PSI class II.", req)
    gaps = find_gaps("Pneumonia due to klebsiella, hospital acquired.", [req])
    assert [(gap.axis, gap.level) for gap in gaps] == [("type", "recommended")]


def test_fully_specified_vap_note_has_no_pneumonia_gaps() -> None:
    assert find_gaps("Severe ventilator-associated pneumonia due to MRSA.", [_pneumonia()]) == []


def test_pneumonia_cites_chi_lrti_alongside_booklet() -> None:
    sources = {citation.clause_id.split("/", 1)[0] for citation in _pneumonia().citations}
    assert {"CDI-2021", "CHI-LRTI"} <= sources


def test_bare_cap_is_not_a_pneumonia_synonym() -> None:
    # Matching is case-insensitive, so a bare "CAP" synonym would fire on the capsule
    # abbreviation ("500 mg cap PO") and on "knee cap" -- a false required finding.
    for note in (
        "Amoxicillin 500 mg cap PO TDS for 5 days.",
        "Tenderness over the knee cap, no effusion.",
    ):
        assert _pneumonia_mentions(note) == [], note


def test_capsule_abbreviation_does_not_satisfy_onset_axis() -> None:
    gaps = find_gaps("Pneumonia, right lower lobe. Augmentin 625 mg cap PO TDS.", [_pneumonia()])
    assert ("onset", "required") in [(gap.axis, gap.level) for gap in gaps]
