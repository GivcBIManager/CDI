import pytest

from cdi_kb.llm_infer import ImplicitFinding, filter_to_known


def test_filter_discards_unknown_conditions() -> None:
    raw = [ImplicitFinding(condition="sepsis", evidence="on norepinephrine, lactate 4"),
           ImplicitFinding(condition="dragon pox", evidence="scales noted")]
    kept = filter_to_known(raw, ("sepsis", "pneumonia"))
    assert [f.condition for f in kept] == ["sepsis"]


@pytest.mark.live
def test_live_inference_names_respiratory_failure() -> None:
    from cdi_kb.llm_infer import infer_implicit_conditions
    from cdi_kb.requirements_model import EXPECTED_CONDITIONS

    note = "Sats 82% on air, placed on high-flow oxygen then BiPAP overnight. ABG: pO2 54."
    inferred = infer_implicit_conditions(note, EXPECTED_CONDITIONS)
    assert "acute respiratory failure" in [f.condition for f in inferred]


def test_make_client_constructs_with_explicit_ssl_context() -> None:
    # Offline: constructing the client must not hit the double-truststore
    # recursion this machine's ssl bootstrap can trigger (no network call).
    from cdi_kb.llm_infer import _make_client

    client = _make_client()
    assert client is not None
