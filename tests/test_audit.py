import pytest

from cdi_kb.audit import run_audit


def test_ckd_without_stage_yields_cited_finding() -> None:
    result = run_audit("Patient admitted with pneumonia due to klebsiella, community acquired. Known CKD.")
    keys = {f.dedupe_key for f in result.findings}
    assert "chronic kidney disease|stage" in keys
    for finding in result.findings:
        assert finding.citations, f"finding without citation escaped: {finding.dedupe_key}"


def test_fully_specified_note_yields_no_ckd_stage_finding() -> None:
    result = run_audit("CKD stage 4 (eGFR 22), stable.")
    assert "chronic kidney disease|stage" not in {f.dedupe_key for f in result.findings}


def test_empty_note() -> None:
    assert run_audit("").findings == []


def test_explicit_doc_type_sets_active_doc_type() -> None:
    result = run_audit("Known CKD.", doc_type="progress_note")
    assert result.active_doc_type == "progress_note"


def test_auto_detect_sets_active_doc_type_to_detected_value() -> None:
    result = run_audit("DISCHARGE SUMMARY\nKnown CKD, discharged home on furosemide today.")
    assert result.active_doc_type == "discharge_summary"


def test_default_active_doc_type_is_any_for_free_prose() -> None:
    result = run_audit("Patient admitted with pneumonia due to klebsiella, community acquired. Known CKD.")
    assert result.active_doc_type == "any"


def test_explicit_doc_type_override_wins_even_for_empty_note() -> None:
    # doc_type is an explicit caller override, not a claim about the note's
    # content -- it must be honored even when there is no text to auto-detect
    # from (auto-detect on empty text yields "any", which must never shadow
    # an explicit override).
    result = run_audit("", doc_type="progress_note")
    assert result.active_doc_type == "progress_note"
    assert result.findings == []


def test_run_audit_rejects_unknown_doc_type() -> None:
    # Defense in depth: doc_type must be one of DOC_TYPES or None even when
    # called directly (not just via the FastAPI/CLI validated entry points) --
    # a caller passing an arbitrary string (e.g. unsanitized user input) must
    # fail loudly rather than silently becoming the note's active_doc_type.
    with pytest.raises(ValueError, match="bogus"):
        run_audit("Known CKD.", doc_type="bogus")


def test_run_audit_rejects_any_as_explicit_doc_type() -> None:
    # "any" is the internal auto-detect fallback value, never a valid
    # explicit override -- callers who want auto-detect must pass None.
    with pytest.raises(ValueError, match="any"):
        run_audit("Known CKD.", doc_type="any")
