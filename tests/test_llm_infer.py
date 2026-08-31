import pytest


def test_make_client_constructs_with_explicit_ssl_context() -> None:
    # Offline: constructing the client must not hit the double-truststore
    # recursion this machine's ssl bootstrap can trigger (no network call).
    from cdi_kb.llm_infer import _make_client

    client = _make_client()
    assert client is not None


def test_condition_catalogue_lists_every_condition_with_its_axes() -> None:
    # Pass A can only return a valid condition/axis pair if the catalogue it is
    # given actually enumerates them; a catalogue missing axes would push the
    # model into guessing axis names that keep_grounded then discards.
    from cdi_kb import config
    from cdi_kb.llm_infer import _condition_catalogue
    from cdi_kb.requirements_model import load_requirements

    requirements = load_requirements(config.REQUIREMENTS_DIR)
    catalogue = _condition_catalogue(requirements)
    for requirement in requirements:
        assert requirement.condition in catalogue
        for rule in requirement.axes:
            assert rule.axis in catalogue


def test_validate_against_kb_makes_no_api_call_without_candidates() -> None:
    # Retrieval returning nothing is already the answer ("no reference in the
    # KB"); paying for a validation call with an empty candidate list is waste.
    from cdi_kb.llm_infer import NoteObservation, validate_against_kb

    observation = NoteObservation(
        condition="sepsis", axis="agent", issue="organism not linked", note_quote="febrile",
    )
    assert validate_against_kb(observation, []) == []


@pytest.mark.live
def test_live_stage_infers_respiratory_failure_and_validates_it_against_the_kb() -> None:
    from cdi_kb import config
    from cdi_kb.index import SearchIndex
    from cdi_kb.llm_infer import run_llm_stage
    from cdi_kb.requirements_model import load_requirements

    note = "Sats 82% on air, placed on high-flow oxygen then BiPAP overnight. ABG: pO2 54."
    requirements = load_requirements(config.REQUIREMENTS_DIR)
    index = SearchIndex(config.KB_DB)
    try:
        validated = run_llm_stage(note, requirements, index)
    finally:
        index.close()

    conditions = {v.observation.condition for v in validated}
    assert "acute respiratory failure" in conditions

    for entry in validated:
        # Note-side firewall: every surviving quote is verbatim note text.
        assert entry.observation.note_quote in note
        # KB-side firewall, gate 1: any support names a real clause.
        for support in entry.supports:
            assert support.clause_id.count("/") >= 2


@pytest.mark.live
def test_live_stage_never_cites_a_clause_outside_the_retrieved_candidates() -> None:
    from cdi_kb import config
    from cdi_kb.clauses import ClauseStore
    from cdi_kb.index import SearchIndex
    from cdi_kb.llm_infer import run_llm_stage
    from cdi_kb.requirements_model import load_requirements

    note = "Sats 82% on air, placed on high-flow oxygen then BiPAP overnight. ABG: pO2 54."
    requirements = load_requirements(config.REQUIREMENTS_DIR)
    index = SearchIndex(config.KB_DB)
    store = ClauseStore(config.KB_DB)
    try:
        validated = run_llm_stage(note, requirements, index)
        for entry in validated:
            for support in entry.supports:
                assert store.get(support.clause_id) is not None, (
                    f"cited clause_id {support.clause_id} is not in the clause store"
                )
    finally:
        index.close()
        store.close()
