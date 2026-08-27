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
