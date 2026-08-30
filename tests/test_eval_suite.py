import yaml

from cdi_kb import config
from cdi_kb.audit import run_audit
from cdi_kb.requirements_model import EXPECTED_CONDITIONS


def _expected() -> dict:
    return yaml.safe_load((config.EVAL_DIR / "expected.yaml").read_text(encoding="utf-8"))


def test_every_diagnosis_has_gap_and_control_note() -> None:
    names = {p.name for p in (config.EVAL_DIR / "notes").glob("*.txt")}
    assert len(names) == 40
    assert set(_expected()) == names


def test_gap_notes_raise_expected_findings_and_controls_do_not() -> None:
    failures: list[str] = []
    for name, spec in _expected().items():
        keys = {f.dedupe_key for f in
                run_audit((config.EVAL_DIR / "notes" / name).read_text(encoding="utf-8")).findings}
        for key in spec.get("must_find", []):
            if key not in keys:
                failures.append(f"{name}: expected {key}, got {sorted(keys)}")
        for key in spec.get("must_not_find", []):
            if key in keys:
                failures.append(f"{name}: false positive {key}")
    assert not failures, "\n".join(failures)


def test_eval_notes_never_yield_completeness_gap_findings() -> None:
    # All 40 eval notes are free prose that auto-detects as doc_type "any" (see
    # test_doctype.test_all_eval_notes_detect_as_any); "any" has no
    # DocTypeRequirement, so no completeness_gap (doc-type element) finding must
    # ever appear for them -- a regression here would mean doc-type detection or
    # the "any" guard in run_audit misfired for the existing corpus.
    offenders: list[str] = []
    for name in _expected():
        result = run_audit((config.EVAL_DIR / "notes" / name).read_text(encoding="utf-8"))
        if any(f.finding_type == "completeness_gap" for f in result.findings):
            offenders.append(name)
    assert not offenders, offenders
