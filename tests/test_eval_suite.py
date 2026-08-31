import yaml

from cdi_kb import config
from cdi_kb.audit import run_audit
from cdi_kb.requirements_model import EXPECTED_CONDITIONS

# Task 8: 8 notes (4 gap/control pairs) intentionally auto-detect as a
# concrete doc type (discharge_summary, diagnosis_list) or exercise a
# necessity rule -- unlike the original 40 free-prose diagnosis notes, they
# are DESIGNED to raise completeness_gap / necessity_mismatch findings. The
# corpus-level guards below (and test_doctype.test_all_eval_notes_detect_as_any)
# exclude them by filename prefix, keeping the original-40 guard intact.
_TYPED_NOTE_PREFIXES = ("discharge-summary-", "diagnosis-list-", "necessity-hba1c-",
                        "necessity-b12-", "multicondition-")


def _expected() -> dict:
    return yaml.safe_load((config.EVAL_DIR / "expected.yaml").read_text(encoding="utf-8"))


def _is_typed_note(name: str) -> bool:
    return name.startswith(_TYPED_NOTE_PREFIXES)


def test_every_diagnosis_has_gap_and_control_note() -> None:
    names = {p.name for p in (config.EVAL_DIR / "notes").glob("*.txt")}
    # 48 -> 50. The 20 original conditions have a gap/control pair each; the 15
    # conditions added from the booklet survey do not yet, and the two
    # multicondition notes are a dense ward-note pair rather than a condition pair.
    assert len(names) == 50
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
    # The original 40 eval notes are free prose that auto-detects as doc_type
    # "any" (see test_doctype.test_all_eval_notes_detect_as_any); "any" has no
    # DocTypeRequirement, so no completeness_gap (doc-type element) finding must
    # ever appear for them -- a regression here would mean doc-type detection or
    # the "any" guard in run_audit misfired for the existing corpus. The 8 Task-8
    # typed notes are excluded -- discharge-summary-gap.txt and
    # diagnosis-list-gap.txt are intentionally built to raise completeness_gap.
    offenders: list[str] = []
    for name in _expected():
        if _is_typed_note(name):
            continue
        result = run_audit((config.EVAL_DIR / "notes" / name).read_text(encoding="utf-8"))
        if any(f.finding_type == "completeness_gap" for f in result.findings):
            offenders.append(name)
    assert not offenders, offenders


def test_eval_notes_never_yield_necessity_mismatch_findings() -> None:
    # None of the original 40 diagnosis-focused notes mention a necessity-rule
    # order term with order-specific phrasing, so none should ever raise a
    # necessity_mismatch finding. The 8 Task-8 typed notes are excluded --
    # necessity-hba1c-gap.txt and necessity-b12-gap.txt are intentionally built
    # to raise necessity_mismatch.
    offenders: list[str] = []
    for name in _expected():
        if _is_typed_note(name):
            continue
        result = run_audit((config.EVAL_DIR / "notes" / name).read_text(encoding="utf-8"))
        if any(f.finding_type == "necessity_mismatch" for f in result.findings):
            offenders.append(name)
    assert not offenders, offenders
