from cdi_kb import config
from cdi_kb.requirements_model import EXPECTED_CONDITIONS, load_requirements


def test_all_20_conditions_present_and_valid() -> None:
    entries = load_requirements(config.REQUIREMENTS_DIR)
    conditions = {e.condition for e in entries}
    missing = set(EXPECTED_CONDITIONS) - conditions
    assert not missing, f"missing requirement entries: {sorted(missing)}"
    for entry in entries:
        assert any(a.level == "required" for a in entry.axes), f"{entry.condition}: no required axis"
        assert all(c.quote.strip() for c in entry.citations), f"{entry.condition}: empty quote"
