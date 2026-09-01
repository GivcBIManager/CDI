"""The KB is the validation authority for LLM inference.

Rule (user-specified): the LLM first infers/understands/analyzes the note, and
every observation it produces is then validated against the provided documents
BEFORE it may be reported. Two firewalls apply, in this order:

  1. Note-side  -- the observation's evidence must appear verbatim in the note.
  2. KB-side    -- supporting clauses must come from the retrieved candidate set,
                   exist in the clause store, and quote it verbatim.

If nothing in the documentation relates to the observation, the finding is still
reported, explicitly marked "no reference in the KB" -- never silently dropped
and never citing authority that was not verified.
"""

import pytest

from cdi_kb import config
from cdi_kb.clauses import ClauseStore
from cdi_kb.index import SearchIndex
from cdi_kb.requirements_model import load_requirements


@pytest.fixture()
def kb():
    store = ClauseStore(config.KB_DB)
    index = SearchIndex(config.KB_DB)
    try:
        yield store, index
    finally:
        store.close()
        index.close()


@pytest.fixture()
def by_condition():
    return {req.condition: req for req in load_requirements(config.REQUIREMENTS_DIR)}


# --------------------------------------------------------------------------
# Note-side firewall
# --------------------------------------------------------------------------

def test_observation_quoting_text_absent_from_the_note_is_rejected(by_condition) -> None:
    from cdi_kb.llm_infer import NoteObservation, keep_grounded

    note = "Sats 82% on air, placed on BiPAP overnight."
    fabricated = NoteObservation(
        condition="acute respiratory failure", axis="type",
        issue="type not documented", note_quote="ABG shows pCO2 of 78",
    )
    assert keep_grounded([fabricated], note, by_condition) == []


def test_observation_quoting_real_note_text_survives(by_condition) -> None:
    from cdi_kb.llm_infer import NoteObservation, keep_grounded

    note = "Sats 82% on air, placed on BiPAP overnight."
    grounded = NoteObservation(
        condition="acute respiratory failure", axis="type",
        issue="type not documented", note_quote="placed on BiPAP overnight",
    )
    assert keep_grounded([grounded], note, by_condition) == [grounded]


def test_observation_naming_an_unknown_condition_is_rejected(by_condition) -> None:
    from cdi_kb.llm_infer import NoteObservation, keep_grounded

    note = "Scales noted across both forearms."
    unknown = NoteObservation(
        condition="dragon pox", axis="type",
        issue="type not documented", note_quote="Scales noted",
    )
    assert keep_grounded([unknown], note, by_condition) == []


def test_observation_naming_an_axis_the_requirement_does_not_have_is_rejected(by_condition) -> None:
    from cdi_kb.llm_infer import NoteObservation, keep_grounded

    note = "Blood cultures growing E. coli, patient hypotensive."
    # sepsis.yaml declares axes agent + type only -- "stage" is not one of them.
    bogus_axis = NoteObservation(
        condition="sepsis", axis="stage",
        issue="stage not documented", note_quote="patient hypotensive",
    )
    assert keep_grounded([bogus_axis], note, by_condition) == []


# --------------------------------------------------------------------------
# Retrieval: the candidate set comes from the KB, not the model
# --------------------------------------------------------------------------

def test_candidates_are_retrieved_from_the_search_index(kb, by_condition) -> None:
    from cdi_kb.llm_infer import NoteObservation, retrieve_candidates

    _store, index = kb
    observation = NoteObservation(
        condition="sepsis", axis="agent",
        issue="organism not linked to the sepsis", note_quote="hypotensive",
    )
    candidates = retrieve_candidates(index, observation, by_condition["sepsis"], limit=8)
    assert candidates, "retrieval must return candidate clauses for a known condition"
    assert len(candidates) <= 8
    assert all(isinstance(clause_id, str) for clause_id in candidates)


# --------------------------------------------------------------------------
# KB-side firewall
# --------------------------------------------------------------------------

def test_support_naming_a_clause_outside_the_candidate_set_is_rejected() -> None:
    from cdi_kb.llm_infer import KbSupport, keep_candidate_supports

    supports = [KbSupport(clause_id="CDI-2021/sepsis/p1", quote="anything"),
                KbSupport(clause_id="CDI-2021/invented-section/p9", quote="anything")]
    kept = keep_candidate_supports(supports, ["CDI-2021/sepsis/p1"])
    assert [s.clause_id for s in kept] == ["CDI-2021/sepsis/p1"]


# --------------------------------------------------------------------------
# Composition: supported vs "no reference in the KB"
# --------------------------------------------------------------------------

def test_inferred_finding_with_a_verbatim_clause_quote_is_marked_supported(kb, by_condition) -> None:
    from cdi_kb.findings import KB_SUPPORTED, compose_inferred_finding
    from cdi_kb.llm_infer import KbSupport, NoteObservation

    store, _index = kb
    clause = store.get("CDI-2021/sepsis/p1")
    assert clause is not None, "fixture depends on a built KB (run build-kb)"
    observation = NoteObservation(
        condition="sepsis", axis="agent",
        issue="organism never linked to the sepsis", note_quote="hypotensive",
    )
    finding = compose_inferred_finding(
        observation, by_condition["sepsis"],
        [KbSupport(clause_id=clause.clause_id, quote=clause.text[:160])], store,
    )
    assert finding is not None
    assert finding.kb_status == KB_SUPPORTED
    assert [c.clause_id for c in finding.citations] == ["CDI-2021/sepsis/p1"]


def test_inferred_finding_with_no_kb_support_is_reported_as_no_reference(kb, by_condition) -> None:
    from cdi_kb.findings import NO_KB_REFERENCE, compose_inferred_finding
    from cdi_kb.llm_infer import NoteObservation

    store, _index = kb
    observation = NoteObservation(
        condition="sepsis", axis="agent",
        issue="organism never linked to the sepsis", note_quote="hypotensive",
    )
    finding = compose_inferred_finding(observation, by_condition["sepsis"], [], store)
    assert finding is not None, "an unsupported observation must still be reported, not dropped"
    assert finding.kb_status == NO_KB_REFERENCE
    assert finding.citations == ()


def test_inferred_finding_whose_quote_is_not_verbatim_falls_back_to_no_reference(kb, by_condition) -> None:
    from cdi_kb.findings import NO_KB_REFERENCE, compose_inferred_finding
    from cdi_kb.llm_infer import KbSupport, NoteObservation

    store, _index = kb
    observation = NoteObservation(
        condition="sepsis", axis="agent",
        issue="organism never linked to the sepsis", note_quote="hypotensive",
    )
    finding = compose_inferred_finding(
        observation, by_condition["sepsis"],
        [KbSupport(clause_id="CDI-2021/sepsis/p1",
                   quote="Sepsis must always be coded as the principal diagnosis.")],
        store,
    )
    assert finding is not None
    assert finding.kb_status == NO_KB_REFERENCE
    assert finding.citations == ()


def test_deterministic_findings_are_marked_supported(kb) -> None:
    from cdi_kb.findings import KB_SUPPORTED, compose_finding
    from cdi_kb.gapcheck import ConditionMention, Gap

    store, _index = kb
    requirements = {req.condition: req for req in load_requirements(config.REQUIREMENTS_DIR)}
    gap = Gap(condition="sepsis", axis="agent", level="required",
              mention=ConditionMention(condition="sepsis", matched_text="sepsis",
                                       start=0, end=6, negated=False))
    finding = compose_finding(gap, requirements["sepsis"], store)
    assert finding is not None
    assert finding.kb_status == KB_SUPPORTED


# --------------------------------------------------------------------------
# Audit wiring: the LLM decides the axis, and the stage can never kill an audit
# --------------------------------------------------------------------------

def _stage(*validated):
    """Build an injectable llm_stage returning fixed ValidatedObservations."""
    def stage(_note_text, _requirements, _index):
        return list(validated)
    return stage


def test_inferred_axis_decision_comes_from_the_llm_not_the_string_scanner() -> None:
    # Regression for the defect this rewrite exists to fix. The note documents an
    # organism ("E. coli") but never links it to sepsis, and never says "sepsis".
    # The old design ran scan_axes over the WHOLE note, saw "e.coli"/"culture" in
    # sepsis.yaml's evidence_terms, marked the agent axis satisfied, and suppressed
    # the single most valuable query in the note. The model's own axis judgment
    # must win now.
    from cdi_kb.audit import run_audit
    from cdi_kb.llm_infer import NoteObservation, ValidatedObservation

    note = ("Febrile 38.9, HR 118, BP 92/54, lactate 3.2. Blood culture: E. coli. "
            "Plan: continue meropenem for the urinary source.")
    observation = NoteObservation(
        condition="sepsis", axis="agent",
        issue="an organism is documented but never linked to the sepsis",
        note_quote="Blood culture: E. coli",
    )
    result = run_audit(note, use_llm=True,
                       llm_stage=_stage(ValidatedObservation(observation, [])))
    assert "sepsis|agent" in {f.dedupe_key for f in result.findings}


def test_unsupported_inferred_finding_is_reported_as_no_reference_in_the_kb() -> None:
    from cdi_kb.audit import run_audit
    from cdi_kb.findings import NO_KB_REFERENCE
    from cdi_kb.llm_infer import NoteObservation, ValidatedObservation

    note = "Febrile 38.9, HR 118, BP 92/54, lactate 3.2. Blood culture: E. coli."
    observation = NoteObservation(
        condition="sepsis", axis="agent",
        issue="an organism is documented but never linked to the sepsis",
        note_quote="Blood culture: E. coli",
    )
    result = run_audit(note, use_llm=True,
                       llm_stage=_stage(ValidatedObservation(observation, [])))
    sepsis = [f for f in result.findings if f.dedupe_key == "sepsis|agent"]
    assert sepsis and sepsis[0].kb_status == NO_KB_REFERENCE
    assert sepsis[0].citations == ()


def test_supported_inferred_finding_carries_the_verified_clause(kb) -> None:
    from cdi_kb.audit import run_audit
    from cdi_kb.findings import KB_SUPPORTED
    from cdi_kb.llm_infer import KbSupport, NoteObservation, ValidatedObservation

    store, _index = kb
    clause = store.get("CDI-2021/sepsis/p1")
    note = "Febrile 38.9, HR 118, BP 92/54, lactate 3.2. Blood culture: E. coli."
    observation = NoteObservation(
        condition="sepsis", axis="agent",
        issue="an organism is documented but never linked to the sepsis",
        note_quote="Blood culture: E. coli",
    )
    validated = ValidatedObservation(
        observation, [KbSupport(clause_id=clause.clause_id, quote=clause.text[:160])]
    )
    result = run_audit(note, use_llm=True, llm_stage=_stage(validated))
    sepsis = [f for f in result.findings if f.dedupe_key == "sepsis|agent"]
    assert sepsis and sepsis[0].kb_status == KB_SUPPORTED
    assert [c.clause_id for c in sepsis[0].citations] == ["CDI-2021/sepsis/p1"]


def test_llm_stage_failure_degrades_to_the_deterministic_findings() -> None:
    # The stage crashed on 6 of 9 runs against a real note and took the whole
    # audit down with it, discarding deterministic findings already in hand.
    from cdi_kb.audit import run_audit

    def exploding_stage(_note_text, _requirements, _index):
        raise RuntimeError("inference unavailable")

    note = "Anemia noted, Hgb 7.8, transfused 2 units."
    result = run_audit(note, use_llm=True, llm_stage=exploding_stage)
    assert "anemia|type" in {f.dedupe_key for f in result.findings}
    assert result.llm_error is not None


def test_inferred_observation_never_duplicates_a_deterministic_finding() -> None:
    from cdi_kb.audit import run_audit
    from cdi_kb.llm_infer import NoteObservation, ValidatedObservation

    note = "Anemia noted, Hgb 7.8, transfused 2 units."
    observation = NoteObservation(
        condition="anemia", axis="type", issue="type not documented",
        note_quote="Anemia noted, Hgb 7.8",
    )
    result = run_audit(note, use_llm=True,
                       llm_stage=_stage(ValidatedObservation(observation, [])))
    keys = [f.dedupe_key for f in result.findings]
    assert keys.count("anemia|type") == 1


def test_inferred_observation_for_a_negated_condition_is_skipped() -> None:
    from cdi_kb.audit import run_audit
    from cdi_kb.llm_infer import NoteObservation, ValidatedObservation

    note = "No evidence of sepsis. Afebrile. Blood culture: no growth."
    observation = NoteObservation(
        condition="sepsis", axis="agent", issue="organism not documented",
        note_quote="Blood culture: no growth",
    )
    result = run_audit(note, use_llm=True,
                       llm_stage=_stage(ValidatedObservation(observation, [])))
    assert "sepsis|agent" not in {f.dedupe_key for f in result.findings}


def test_candidate_retrieval_is_independent_of_the_models_issue_phrasing(kb, by_condition) -> None:
    # The candidate set is the authority boundary: it decides which clauses the
    # model is allowed to cite, so it must be a property of the KB, not of how
    # the model happened to word its observation. Folding the model-authored
    # `issue` sentence into the FTS query made it unstable -- BM25 OR-joins every
    # term over 2 chars, so a long issue diluted the query enough to push the
    # governing clause out of the top-N (and pull unrelated sections in). The
    # same observation then validated on one run and came back "no reference in
    # the KB" on the next.
    from cdi_kb.llm_infer import NoteObservation, retrieve_candidates

    _store, index = kb
    requirement = by_condition["acute kidney injury"]
    phrasings = [
        "",
        "the acuity of the renal failure is not documented",
        "ARF is documented without specifying whether it is acute or acute on chronic "
        "in the setting of known chronic kidney disease",
    ]
    candidate_sets = [
        retrieve_candidates(
            index,
            NoteObservation(condition="acute kidney injury", axis="onset",
                            issue=phrasing, note_quote="ARF"),
            requirement,
        )
        for phrasing in phrasings
    ]
    assert candidate_sets[0] == candidate_sets[1] == candidate_sets[2]


def test_retrieval_can_reach_the_clause_the_kb_itself_calls_governing(kb, by_condition) -> None:
    # Sanity floor on the candidate set: for a condition whose requirement file
    # already names a governing clause, retrieval must at least be able to put
    # that clause in front of the model. Otherwise "no reference in the KB" would
    # be reported for observations the documents demonstrably do cover.
    from cdi_kb.llm_infer import NoteObservation, retrieve_candidates

    _store, index = kb
    requirement = by_condition["acute kidney injury"]
    candidates = retrieve_candidates(
        index,
        NoteObservation(condition="acute kidney injury", axis="onset",
                        issue="acuity not documented", note_quote="ARF"),
        requirement,
    )
    assert "CDI-2021/renal-failure-impairment/p1" in candidates


def test_no_single_source_monopolises_the_candidate_set(kb, by_condition) -> None:
    """De-fusing the journal-typeset CHI guidelines (step 4) made 1,582 clauses of
    dense guideline prose genuinely searchable for the first time -- previously
    their fused text matched no query term, so they never competed. A single
    global top-N then let one verbose source fill the whole candidate set:
    CHI-CKD took every slot for "acute kidney injury onset", pushing the booklet's
    own Renal Failure/Impairment clause out, and reach fell 31/37 -> 29/37.

    A per-source cap keeps the candidate set representative of the corpus rather
    than of whichever source happens to be wordiest about the query terms.
    """
    from cdi_kb.llm_infer import PER_SOURCE_LIMIT, NoteObservation, retrieve_candidates

    _store, index = kb
    candidates = retrieve_candidates(
        index,
        NoteObservation(condition="acute kidney injury", axis="onset",
                        issue="", note_quote="x"),
        by_condition["acute kidney injury"],
    )
    per_source: dict[str, int] = {}
    for clause_id in candidates:
        source = clause_id.split("/")[0]
        per_source[source] = per_source.get(source, 0) + 1
    assert max(per_source.values()) <= PER_SOURCE_LIMIT, per_source
    assert len(per_source) > 1, f"candidate set came from one source only: {per_source}"


def test_retrieval_reach_across_every_requirement_axis(kb, by_condition) -> None:
    """Executable disclosure of how much of the KB's own authority the candidate
    set can actually reach.

    For each requirement axis, retrieval must surface at least one of the clauses
    that requirement itself names as governing. Where it cannot, the LLM path will
    honestly report "no reference in the KB" -- so this test pins both the floor
    and the exact known-unreachable set, and fails if either moves.

    The unreachable eight are pre-existing KB limitations, not inference bugs. Six
    of them: heart failure, obesity and stroke are the repo's `mixed_authority_entries`
    (their citations are the generic "Documenting for Specificity" mandate plus a CHI
    clause), and the CHI clauses involved extract as space-stripped runs
    ("TheclassificationforbaselineandsubsequentLVEFisshown") that tokenize as one
    term and so match no condition or axis word. Fixing them means re-chunking
    those CHI PDFs, not tuning retrieval. The other two, corneal ulcer|agent/stage,
    are a distinct root cause -- see the comment in the assert below.

    Re-measured after the 31 curated MOH-KSA protocols were registered as
    sources (11 -> 42, this test's own `total` 37 -> 65): the candidate window
    had to widen from 16 to 32 (see CANDIDATE_LIMIT in llm_infer.py), because
    same-condition MOH clauses now fill every slot below 32 before the cited
    clause surfaces, for urinary tract infection|site and surgical wound
    infection|onset/agent. Reachability plateaus at 57/65 axes from limit 32
    onward: 48/65 at limit 8, 54/65 at 16, 56/65 at 24, 57/65 at 32, and no
    further gain out to 64.
    """
    from cdi_kb.llm_infer import NoteObservation, retrieve_candidates

    _store, index = kb
    unreachable = set()
    total = 0
    for requirement in by_condition.values():
        cited = {c.clause_id for c in requirement.citations}
        for rule in requirement.axes:
            total += 1
            candidates = set(retrieve_candidates(
                index,
                NoteObservation(condition=requirement.condition, axis=rule.axis,
                                issue="", note_quote="x"),
                requirement,
            ))
            if not cited & candidates:
                unreachable.add(f"{requirement.condition}|{rule.axis}")

    assert unreachable == {
        "heart failure|type", "heart failure|onset",
        "obesity|type", "obesity|stage",
        "stroke|type", "stroke|onset",
        # Same root cause, found when the requirement set grew to 35: the Corneal
        # Ulcers mandate sentence lives in a CONTINUATION paragraph that never names
        # the condition ("Documentation should include details of cause, including
        # type of trauma or type of chemical..."). A lexical condition+axis query
        # cannot reach a clause that contains neither term. Re-anchoring to p1, which
        # does name the condition, would mean citing a clause that carries no
        # documentation mandate -- the worse trade.
        "corneal ulcer|agent", "corneal ulcer|stage",
    }
    assert total - len(unreachable) >= 57


# --------------------------------------------------------------------------
# Step 2: the LLM may judge axes for conditions the note NAMES, not only
# conditions it never mentions. The blanket already-named gate is replaced by
# two narrower ones: never contradict an explicit negation, never duplicate a
# key the deterministic pass already emitted.
# --------------------------------------------------------------------------

def test_observation_for_a_named_condition_is_reported() -> None:
    # The whole point of lifting the gate. The note NAMES the UTI and names an
    # organism, so gapcheck.scan_axes marks the `agent` axis satisfied from
    # "E. coli" appearing anywhere -- even though the note never draws the link
    # the booklet asks for. Only the model can see that, and until now it was
    # forbidden from looking at named conditions at all.
    from cdi_kb.audit import run_audit
    from cdi_kb.llm_infer import NoteObservation, ValidatedObservation

    note = ("Progress Note\nS: dysuria.\nO: urine culture grew E. coli.\n"
            "A: UTI.\nP: antibiotics.")
    observation = NoteObservation(
        condition="urinary tract infection", axis="agent",
        issue="an organism is documented but never linked to the UTI",
        note_quote="urine culture grew E. coli",
    )
    result = run_audit(note, use_llm=True,
                       llm_stage=_stage(ValidatedObservation(observation, [])))
    assert "urinary tract infection|agent" in {f.dedupe_key for f in result.findings}


def test_observation_for_an_explicitly_negated_condition_is_still_skipped() -> None:
    # The gate this replaces existed for exactly this case: observations carry
    # no negation flag, so a condition the note rules out must be filtered by
    # the audit, not trusted to the model.
    from cdi_kb.audit import run_audit
    from cdi_kb.llm_infer import NoteObservation, ValidatedObservation

    note = "No evidence of sepsis. Afebrile. Blood culture: no growth."
    observation = NoteObservation(
        condition="sepsis", axis="agent", issue="organism not documented",
        note_quote="Blood culture: no growth",
    )
    result = run_audit(note, use_llm=True,
                       llm_stage=_stage(ValidatedObservation(observation, [])))
    assert "sepsis|agent" not in {f.dedupe_key for f in result.findings}


def test_condition_negated_once_but_affirmed_elsewhere_is_not_skipped() -> None:
    # "Ruled out on admission, present now" is ordinary progress-note narrative.
    # Only a condition whose EVERY mention is negated may be suppressed.
    from cdi_kb.audit import run_audit
    from cdi_kb.llm_infer import NoteObservation, ValidatedObservation

    # Spaced as a real note would be. gapcheck._is_negated uses a fixed 40-char
    # PRE-mention window, so an affirmation packed within 40 characters of the
    # negation ("No sepsis on admission. Day 3: now in septic shock") is itself
    # read as negated -- a documented limitation of the negation heuristic, not
    # of this gate. See README-DEMO.md honest limits.
    note = ("Day 1: no evidence of sepsis, cultures pending and patient afebrile throughout.\n"
            "Day 3: patient deteriorated overnight and is now in septic shock, "
            "blood cultures growing E. coli.\n")
    observation = NoteObservation(
        condition="sepsis", axis="agent",
        issue="the organism is never linked to the sepsis",
        note_quote="blood cultures growing E. coli",
    )
    result = run_audit(note, use_llm=True,
                       llm_stage=_stage(ValidatedObservation(observation, [])))
    assert "sepsis|agent" in {f.dedupe_key for f in result.findings}


def test_observation_matching_a_deterministic_finding_key_is_skipped() -> None:
    from cdi_kb.audit import run_audit
    from cdi_kb.llm_infer import NoteObservation, ValidatedObservation

    note = "Progress Note\nS: tired.\nO: Hgb 7.8, transfused 2 units.\nA: Anemia.\nP: monitor."
    deterministic = run_audit(note)
    assert "anemia|type" in {f.dedupe_key for f in deterministic.findings}

    observation = NoteObservation(
        condition="anemia", axis="type", issue="type not documented",
        note_quote="Hgb 7.8, transfused 2 units",
    )
    result = run_audit(note, use_llm=True,
                       llm_stage=_stage(ValidatedObservation(observation, [])))
    keys = [f.dedupe_key for f in result.findings]
    assert keys.count("anemia|type") == 1


def test_observation_may_reraise_an_axis_whose_deterministic_citation_was_dropped() -> None:
    # A dropped citation means the deterministic pass raised nothing at all for
    # that axis -- its hand-authored quote failed verification. The LLM path
    # reaches its authority by retrieval instead, so it is not a duplicate and
    # must not be suppressed.
    from cdi_kb.audit import _validated_findings
    from cdi_kb.clauses import ClauseStore
    from cdi_kb.llm_infer import NoteObservation, ValidatedObservation
    from cdi_kb.requirements_model import AxisRule, Citation, DiagnosisRequirement

    broken = DiagnosisRequirement(
        condition="sepsis", synonyms=["septicaemia"],
        axes=[AxisRule(axis="agent", level="required", evidence_terms=["due to"])],
        recommendation="r",
        citations=[Citation(clause_id="CDI-2021/does-not-exist/p1", quote="q")],
    )
    note = "Septicaemia noted, patient febrile and hypotensive."
    store = ClauseStore(config.KB_DB)
    try:
        findings = _validated_findings(
            [ValidatedObservation(
                NoteObservation(condition="sepsis", axis="agent",
                                issue="organism not documented",
                                note_quote="patient febrile and hypotensive"), [])],
            note, {"sepsis": broken}, store,
            negated_conditions=set(), existing_keys={"sepsis|onset"},
        )
    finally:
        store.close()
    assert [f.dedupe_key for f in findings] == ["sepsis|agent"]
