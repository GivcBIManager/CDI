"""Regression tests for cdi_kb.audit._inferred_findings: implicit conditions
from the LLM stage must be audited against the ORIGINAL note text, never a
synthetic marker, so they cannot self-satisfy axes or be falsely negated by
find_gaps's negation window -- and duplicate/already-named conditions must
not produce duplicate findings.
"""

import pytest

from cdi_kb import config
from cdi_kb.audit import AuditResult, _inferred_findings, _named_conditions
from cdi_kb.clauses import ClauseStore
from cdi_kb.requirements_model import load_requirements


@pytest.fixture()
def by_condition_and_store():
    requirements = load_requirements(config.REQUIREMENTS_DIR)
    by_condition = {req.condition: req for req in requirements}
    store = ClauseStore(config.KB_DB)
    try:
        yield by_condition, store
    finally:
        store.close()


def test_synthetic_marker_no_longer_self_satisfies_onset_axis(by_condition_and_store) -> None:
    # Old (defective) design appended "[assessment: acute respiratory failure]" to the
    # note, and the word "acute" in that marker satisfied the onset axis's own
    # evidence_terms (["acute", "acute on chronic", "chronic"]) -- suppressing the
    # exact gap the LLM stage exists to raise. The new design scans the ORIGINAL
    # note only, so the onset gap must still fire.
    by_condition, store = by_condition_and_store
    note = "Sats 82% on air, placed on BiPAP overnight."
    findings, dropped = _inferred_findings(
        [("acute respiratory failure", "on BiPAP, pO2 54")],
        note, by_condition, store, set(),
    )
    keys = {f.dedupe_key for f in findings} | set(dropped)
    assert "acute respiratory failure|onset" in keys

    onset_findings = [f for f in findings if f.dedupe_key == "acute respiratory failure|onset"]
    assert onset_findings, "onset gap must be a real (citation-verified) finding, not just dropped"
    assert "BiPAP" in onset_findings[0].evidence_excerpt


def test_trailing_negation_cue_does_not_suppress_inferred_gap(by_condition_and_store) -> None:
    # Old design ran find_gaps on the synthetic note, whose appended marker sat right
    # after "...ruled out." -- within the 40-char pre-mention negation window -- and
    # was falsely negated. The new design never runs find_gaps (or its negation
    # check) against inferred conditions, so a pre-mention negation cue elsewhere in
    # the note must not suppress the gap.
    by_condition, store = by_condition_and_store
    note = "Sats 82% on air, placed on BiPAP overnight. Bacterial infection ruled out."
    findings, dropped = _inferred_findings(
        [("acute respiratory failure", "on BiPAP, pO2 54")],
        note, by_condition, store, set(),
    )
    keys = {f.dedupe_key for f in findings} | set(dropped)
    assert "acute respiratory failure|onset" in keys
    assert "acute respiratory failure|type" in keys


def test_duplicate_implicit_conditions_yield_no_duplicate_findings(by_condition_and_store) -> None:
    by_condition, store = by_condition_and_store
    note = "Patient febrile, tachycardic, unwell."
    findings, _dropped = _inferred_findings(
        [("sepsis", "evidence one"), ("sepsis", "evidence two")],
        note, by_condition, store, set(),
    )
    keys = [f.dedupe_key for f in findings]
    assert len(keys) == len(set(keys)), f"duplicate dedupe_keys produced: {keys}"


def test_already_named_condition_is_skipped(by_condition_and_store) -> None:
    by_condition, store = by_condition_and_store
    note = "Patient febrile, tachycardic, unwell."
    findings, dropped = _inferred_findings(
        [("sepsis", "evidence one")],
        note, by_condition, store, {"sepsis"},
    )
    assert findings == []
    assert dropped == []


def test_named_conditions_includes_named_but_negated_condition() -> None:
    # A NAMED-BUT-NEGATED condition ("No sepsis.") is absent from findings/dropped
    # (nothing was raised for it), so a set derived only from those keys would miss
    # it. _named_conditions must re-detect mentions structurally, so it still shows
    # up here -- otherwise, if the LLM returned this condition as an implicit anyway,
    # _inferred_findings (which hardcodes negated=False by design) would emit a
    # clinically false finding for a condition the note explicitly rules out.
    requirements = load_requirements(config.REQUIREMENTS_DIR)
    note = "No evidence of sepsis. Afebrile."
    named = _named_conditions(note, requirements, AuditResult())
    assert "sepsis" in named


def test_inferred_findings_skips_condition_from_named_conditions_guard(by_condition_and_store) -> None:
    # End-to-end through the guard's own home: _named_conditions' output feeds
    # directly into _inferred_findings' skip set.
    by_condition, store = by_condition_and_store
    requirements = list(by_condition.values())
    note = "No evidence of sepsis. Afebrile."
    already_named = _named_conditions(note, requirements, AuditResult())
    findings, dropped = _inferred_findings(
        [("sepsis", "evidence one")],
        note, by_condition, store, already_named,
    )
    assert findings == []
    assert dropped == []
