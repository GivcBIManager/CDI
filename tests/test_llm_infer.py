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


def test_client_is_reused_across_calls() -> None:
    # _make_client built a fresh Anthropic client -- and a fresh SSL context --
    # for every single API call, so a note producing ten observations paid the
    # setup cost eleven times and reused no connection.
    from cdi_kb.llm_infer import _make_client

    assert _make_client() is _make_client()


def test_validate_all_returns_one_result_per_item_in_input_order() -> None:
    # Results are zipped back onto their observations by position, so an
    # out-of-order result would attach one observation's KB support to another.
    from cdi_kb.llm_infer import KbSupport, NoteObservation, validate_all

    def fake_validator(observation, _candidates):
        return [KbSupport(clause_id=f"X/{observation.axis}/p1", quote="q")]

    items = [
        (NoteObservation(condition="sepsis", axis=axis, issue="i", note_quote="q"), [])
        for axis in ("agent", "type")
    ]
    results = validate_all(items, validator=fake_validator, max_workers=4)
    assert [r[0].clause_id for r in results] == ["X/agent/p1", "X/type/p1"]


def test_validate_all_runs_items_concurrently() -> None:
    import time

    from cdi_kb.llm_infer import NoteObservation, validate_all

    def slow_validator(_observation, _candidates):
        time.sleep(0.2)
        return []

    items = [
        (NoteObservation(condition="sepsis", axis="agent", issue="i", note_quote=str(n)), [])
        for n in range(5)
    ]
    started = time.monotonic()
    results = validate_all(items, validator=slow_validator, max_workers=5)
    elapsed = time.monotonic() - started

    assert len(results) == 5
    assert elapsed < 0.6, f"ran sequentially: {elapsed:.2f}s for 5 x 0.2s items"


def test_validate_all_on_empty_input_makes_no_calls() -> None:
    from cdi_kb.llm_infer import validate_all

    def exploding_validator(_observation, _candidates):
        raise AssertionError("must not be called")

    assert validate_all([], validator=exploding_validator) == []
