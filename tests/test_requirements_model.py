import pytest

from cdi_kb import config
from cdi_kb.requirements_model import DiagnosisRequirement, load_requirements


def test_ckd_entry_loads() -> None:
    entries = load_requirements(config.REQUIREMENTS_DIR)
    by_condition = {e.condition: e for e in entries}
    assert "chronic kidney disease" in by_condition
    ckd = by_condition["chronic kidney disease"]
    assert "ckd" in [s.lower() for s in ckd.synonyms]
    assert any(a.axis == "stage" and a.level == "required" for a in ckd.axes)
    assert ckd.citations and ckd.citations[0].clause_id.startswith("CDI-2021/")


def test_invalid_axis_rejected(tmp_path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "condition: x\nsynonyms: [x]\n"
        "axes: [{axis: colour, level: required, evidence_terms: [y]}]\n"
        "recommendation: r\ncitations: [{clause_id: 'CDI-2021/a/p1', quote: q}]\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="bad.yaml"):
        load_requirements(tmp_path)
