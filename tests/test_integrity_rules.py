"""Documentation-integrity findings: copy-forward and conflicting documentation.

Both come from auditing a real internal-medicine progress note. Neither was
expressible before: every existing finding type evaluates ONE condition against
ONE checklist, so nothing could say "this note contradicts itself" or "this note
was cloned from an earlier one".
"""

import pytest

from cdi_kb import config
from cdi_kb.audit import run_audit
from cdi_kb.requirements_model import load_integrity_rules

_COPY_FORWARD_NOTE = """PROGRESS NOTE

SUBJECTIVE:
Patient reviewed, stable overnight.

ASSESSMENT / PLAN:
1. Continue current management.

Note: physical exam section carried forward from 2026-08-26 note.
"""

_CLEAN_NOTE = """PROGRESS NOTE

SUBJECTIVE:
Patient reviewed, stable overnight. Examined this morning.

ASSESSMENT / PLAN:
1. Continue current management.
"""

# NSTEMI in the cardiology consult, "demand ischemia" in the attending's plan --
# two different type labels for the same condition from two different authors.
_CONFLICTING_NOTE = """PROGRESS NOTE

SUBJECTIVE:
72 y/o male, chest discomfort resolved.

Cardiology consult note (08-27):
  Impression: NSTEMI in setting of acute illness.

ASSESSMENT / PLAN:
1. Troponin elevation — likely demand ischemia. Cardiology following.
"""

# Both labels written by the same author in one breath: a differential, not a
# conflict.
_DIFFERENTIAL_NOTE = """PROGRESS NOTE

SUBJECTIVE:
72 y/o male, chest discomfort.

ASSESSMENT / PLAN:
1. Chest pain — NSTEMI versus demand ischemia, awaiting serial troponins.
"""


def test_integrity_rules_load_with_verifiable_citations() -> None:
    rules = load_integrity_rules(config.INTEGRITY_RULES_DIR)
    kinds = {rule.kind for rule in rules}
    assert {"copy_forward", "conflicting_documentation"} <= kinds
    for rule in rules:
        assert rule.citations, f"{rule.kind} rule has no citation"


# --- copy-forward ----------------------------------------------------------

def test_note_declaring_carried_forward_content_raises_a_finding() -> None:
    result = run_audit(_COPY_FORWARD_NOTE)
    finding = [f for f in result.findings if f.dedupe_key == "note|copy_forward"]
    assert finding, [f.dedupe_key for f in result.findings]
    assert finding[0].finding_type == "copy_forward"
    assert finding[0].citations, "must carry a verified citation"
    assert "carried forward" in finding[0].evidence_excerpt


def test_note_without_a_copy_forward_cue_raises_nothing() -> None:
    result = run_audit(_CLEAN_NOTE)
    assert "note|copy_forward" not in {f.dedupe_key for f in result.findings}


def test_copy_forward_fires_once_even_with_several_cues() -> None:
    note = _COPY_FORWARD_NOTE + "\nExam copied forward. Plan auto-populated from template.\n"
    result = run_audit(note)
    keys = [f.dedupe_key for f in result.findings]
    assert keys.count("note|copy_forward") == 1


# --- conflicting documentation ---------------------------------------------

def test_two_type_labels_from_two_authors_raise_a_conflict() -> None:
    result = run_audit(_CONFLICTING_NOTE)
    finding = [f for f in result.findings
               if f.dedupe_key == "myocardial ischemia|conflicting_type"]
    assert finding, [f.dedupe_key for f in result.findings]
    assert finding[0].finding_type == "conflicting_documentation"
    assert finding[0].citations


def test_two_type_labels_from_one_author_are_a_differential_not_a_conflict() -> None:
    result = run_audit(_DIFFERENTIAL_NOTE)
    assert "myocardial ischemia|conflicting_type" not in {f.dedupe_key for f in result.findings}


def test_a_single_type_label_raises_no_conflict() -> None:
    note = _CONFLICTING_NOTE.replace(
        "1. Troponin elevation — likely demand ischemia. Cardiology following.",
        "1. NSTEMI — cardiology following, medical management.")
    result = run_audit(note)
    assert "myocardial ischemia|conflicting_type" not in {f.dedupe_key for f in result.findings}


def test_conflict_check_is_opt_in_per_axis() -> None:
    """Not every axis has mutually exclusive labels, so the check must be opted
    into rather than applied to all of them.

    `acute respiratory failure|onset` lists "acute", "chronic" and "acute on
    chronic" -- a note can legitimately carry two of those, and "acute" appears
    in ordinary prose like "no acute infiltrate". Firing a conflict there would
    be noise, so AxisRule.conflict_check defaults to False.
    """
    from cdi_kb.requirements_model import load_requirements

    requirements = load_requirements(config.REQUIREMENTS_DIR)
    opted_in = {f"{r.condition}|{a.axis}" for r in requirements for a in r.axes if a.conflict_check}
    assert "myocardial ischemia|type" in opted_in
    assert "acute respiratory failure|onset" not in opted_in


@pytest.mark.parametrize("note", [_CLEAN_NOTE, _DIFFERENTIAL_NOTE])
def test_integrity_findings_never_fire_on_an_unremarkable_note(note) -> None:
    kinds = {f.finding_type for f in run_audit(note).findings}
    assert "copy_forward" not in kinds
    assert "conflicting_documentation" not in kinds
