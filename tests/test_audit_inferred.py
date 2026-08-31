"""Regression tests for cdi_kb.audit._validated_findings: KB-validated
observations from the LLM stage must be grounded in the ORIGINAL note, must not
duplicate or contradict deterministic findings, and must respect the same
doc-type scoping deterministic gaps do.

History: this module previously tested `_inferred_findings`, which re-derived
axes with gapcheck.scan_axes (a whole-note string scan). That mechanism is gone
-- the model's own axis judgment is now authoritative, because scan_axes marked
axes satisfied from text belonging to unrelated problems. The assertions that
survived the rewrite are the ones about grounding, dedupe, negation and
doc-type scoping; they are behaviour, not mechanism.
"""

import pytest

from cdi_kb import config
from cdi_kb.audit import _fully_negated_conditions, _validated_findings
from cdi_kb.clauses import ClauseStore
from cdi_kb.llm_infer import NoteObservation, ValidatedObservation
from cdi_kb.requirements_model import AxisRule, Citation, DiagnosisRequirement, load_requirements


@pytest.fixture()
def by_condition_and_store():
    requirements = load_requirements(config.REQUIREMENTS_DIR)
    by_condition = {req.condition: req for req in requirements}
    store = ClauseStore(config.KB_DB)
    try:
        yield by_condition, store
    finally:
        store.close()


def _observed(condition: str, axis: str, note_quote: str, supports=()) -> ValidatedObservation:
    return ValidatedObservation(
        observation=NoteObservation(
            condition=condition, axis=axis, issue=f"{axis} not documented", note_quote=note_quote
        ),
        supports=list(supports),
    )


def test_inferred_finding_evidence_is_verbatim_note_text(by_condition_and_store) -> None:
    # The evidence a reviewer sees must be text they can find in the note. The
    # old design put a truncated model-authored string here; the new one carries
    # the quote that already cleared the note-side firewall.
    by_condition, store = by_condition_and_store
    note = "Sats 82% on air, placed on BiPAP overnight."
    findings = _validated_findings(
        [_observed("acute respiratory failure", "onset", "placed on BiPAP overnight")],
        note, by_condition, store, set(), set(),
    )
    assert [f.dedupe_key for f in findings] == ["acute respiratory failure|onset"]
    assert findings[0].evidence_excerpt in note


def test_observation_quoting_text_absent_from_the_note_is_rejected_at_the_audit_layer(
    by_condition_and_store,
) -> None:
    # Defense in depth: the note-side firewall is re-applied here, so it holds
    # for any injected stage, not just the production one.
    by_condition, store = by_condition_and_store
    note = "Sats 82% on air, placed on BiPAP overnight."
    findings = _validated_findings(
        [_observed("acute respiratory failure", "onset", "intubated for hypercapnia")],
        note, by_condition, store, set(), set(),
    )
    assert findings == []


def test_trailing_negation_cue_does_not_suppress_an_inferred_gap(by_condition_and_store) -> None:
    # A negation cue elsewhere in the note (for a different, ruled-out problem)
    # must not suppress a gap for a condition that is not itself negated.
    by_condition, store = by_condition_and_store
    note = "Sats 82% on air, placed on BiPAP overnight. Bacterial infection ruled out."
    findings = _validated_findings(
        [_observed("acute respiratory failure", "onset", "placed on BiPAP overnight"),
         _observed("acute respiratory failure", "type", "Sats 82% on air")],
        note, by_condition, store, set(), set(),
    )
    keys = {f.dedupe_key for f in findings}
    assert keys == {"acute respiratory failure|onset", "acute respiratory failure|type"}


def test_duplicate_observations_yield_no_duplicate_findings(by_condition_and_store) -> None:
    by_condition, store = by_condition_and_store
    note = "Patient febrile, tachycardic, unwell."
    findings = _validated_findings(
        [_observed("sepsis", "agent", "Patient febrile, tachycardic"),
         _observed("sepsis", "agent", "tachycardic, unwell")],
        note, by_condition, store, set(), set(),
    )
    keys = [f.dedupe_key for f in findings]
    assert len(keys) == len(set(keys)), f"duplicate dedupe_keys produced: {keys}"


def test_explicitly_negated_condition_is_skipped(by_condition_and_store) -> None:
    # Step 2 narrowed this guard: it used to skip every condition the note NAMED,
    # which locked the model out of exactly the axes the string scanner gets wrong.
    # Now only a condition whose every mention is negated is suppressed -- because
    # observations carry no negation flag for compose_inferred_finding to honour.
    by_condition, store = by_condition_and_store
    note = "Patient febrile, tachycardic, unwell."
    findings = _validated_findings(
        [_observed("sepsis", "agent", "Patient febrile, tachycardic")],
        note, by_condition, store, {"sepsis"}, set(),
    )
    assert findings == []


def test_named_but_affirmed_condition_is_no_longer_skipped(by_condition_and_store) -> None:
    by_condition, store = by_condition_and_store
    note = "A: Sepsis, source urinary. Blood cultures growing E. coli."
    findings = _validated_findings(
        [_observed("sepsis", "agent", "Blood cultures growing E. coli")],
        note, by_condition, store, set(), set(),
    )
    assert [f.dedupe_key for f in findings] == ["sepsis|agent"]


def test_key_already_emitted_deterministically_is_skipped(by_condition_and_store) -> None:
    by_condition, store = by_condition_and_store
    note = "A: Sepsis, source urinary. Blood cultures growing E. coli."
    findings = _validated_findings(
        [_observed("sepsis", "agent", "Blood cultures growing E. coli")],
        note, by_condition, store, set(), {"sepsis|agent"},
    )
    assert findings == []


def test_fully_negated_conditions_includes_a_ruled_out_condition() -> None:
    # A ruled-out condition raises no finding, so a set derived from finding keys
    # would miss it. _fully_negated_conditions re-detects mentions structurally,
    # so it still shows up -- otherwise, if the LLM returned this condition,
    # _validated_findings would emit a clinically false finding for a condition
    # the note explicitly rules out.
    requirements = load_requirements(config.REQUIREMENTS_DIR)
    negated = _fully_negated_conditions("No evidence of sepsis. Afebrile.", requirements)
    assert "sepsis" in negated


def test_fully_negated_conditions_excludes_a_condition_affirmed_anywhere() -> None:
    requirements = load_requirements(config.REQUIREMENTS_DIR)
    note = ("Day 1: no evidence of sepsis, cultures pending and patient afebrile throughout.\n"
            "Day 3: patient deteriorated overnight and is now in septic shock.\n")
    assert "sepsis" not in _fully_negated_conditions(note, requirements)


def test_validated_findings_skips_condition_from_the_negation_guard(by_condition_and_store) -> None:
    # End-to-end through the guard's own home: _fully_negated_conditions' output
    # feeds directly into _validated_findings' skip set.
    by_condition, store = by_condition_and_store
    requirements = list(by_condition.values())
    note = "No evidence of sepsis. Afebrile."
    negated = _fully_negated_conditions(note, requirements)
    findings = _validated_findings(
        [_observed("sepsis", "agent", "No evidence of sepsis")],
        note, by_condition, store, negated, set(),
    )
    assert findings == []


def test_validated_findings_respect_applies_to_doc_type_scoping(by_condition_and_store) -> None:
    # An axis rule scoped to a specific doc_type (applies_to) must be filtered out
    # of LLM-derived findings exactly as it is for deterministic find_gaps --
    # otherwise a doc-type-scoped rule would still fire via the LLM path for a
    # note of the wrong doc type.
    by_condition, store = by_condition_and_store
    scoped_req = DiagnosisRequirement(
        condition="chronic kidney disease",
        synonyms=["CKD"],
        axes=[AxisRule(axis="stage", level="required",
                       evidence_terms=["stage 4"], applies_to=["discharge_summary"])],
        recommendation="r",
        citations=[Citation(clause_id="CDI-2021/x/p1", quote="q")],
    )
    scoped_by_condition = {**by_condition, "chronic kidney disease": scoped_req}
    note = "Renal impairment noted, stage not documented."
    observed = [_observed("chronic kidney disease", "stage", "Renal impairment noted")]

    findings = _validated_findings(
        observed, note, scoped_by_condition, store, set(), set(), doc_type="progress_note",
    )
    assert "chronic kidney disease|stage" not in {f.dedupe_key for f in findings}

    for doc_type in ("discharge_summary", "any"):
        findings = _validated_findings(
            observed, note, scoped_by_condition, store, set(), set(), doc_type=doc_type,
        )
        assert "chronic kidney disease|stage" in {f.dedupe_key for f in findings}
