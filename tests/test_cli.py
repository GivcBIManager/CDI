import json

import pytest

from cdi_kb.cli import main


def test_audit_command_json_output(tmp_path, capsys) -> None:
    note = tmp_path / "note.txt"
    note.write_text("Known CKD, on regular follow-up.", encoding="utf-8")
    exit_code = main(["audit", str(note), "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(f["dedupe_key"] == "chronic kidney disease|stage" for f in payload["findings"])


def test_audit_command_json_output_includes_active_doc_type(tmp_path, capsys) -> None:
    note = tmp_path / "note.txt"
    note.write_text("Known CKD, on regular follow-up.", encoding="utf-8")
    exit_code = main(["audit", str(note), "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["active_doc_type"] == "any"


def test_audit_command_human_output(tmp_path, capsys) -> None:
    note = tmp_path / "note.txt"
    note.write_text("Known CKD.", encoding="utf-8")
    assert main(["audit", str(note)]) == 0
    out = capsys.readouterr().out
    assert "chronic kidney disease" in out and "CDI-2021/" in out


def test_audit_command_human_output_prints_doc_type_first_line(tmp_path, capsys) -> None:
    note = tmp_path / "note.txt"
    note.write_text("Known CKD.", encoding="utf-8")
    assert main(["audit", str(note)]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "doc type: any"


def test_audit_command_doc_type_flag_overrides_auto_detection(tmp_path, capsys) -> None:
    note = tmp_path / "note.txt"
    note.write_text(
        "Admitted with community acquired pneumonia. Principal diagnosis: pneumonia.\n"
        "Procedure performed: chest drain insertion under local anesthesia in theatre.\n",
        encoding="utf-8",
    )
    exit_code = main(["audit", str(note), "--doc-type", "discharge_summary", "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["active_doc_type"] == "discharge_summary"
    assert any(f["finding_type"] == "completeness_gap" for f in payload["findings"])


def test_audit_command_doc_type_flag_default_is_auto(tmp_path, capsys) -> None:
    note = tmp_path / "note.txt"
    note.write_text("DISCHARGE SUMMARY\nKnown CKD.\n", encoding="utf-8")
    assert main(["audit", str(note)]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "doc type: discharge_summary"


def test_audit_command_doc_type_flag_rejects_invalid_choice(tmp_path, capsys) -> None:
    note = tmp_path / "note.txt"
    note.write_text("Known CKD.", encoding="utf-8")
    try:
        main(["audit", str(note), "--doc-type", "not-a-real-type"])
        raised = False
    except SystemExit:
        raised = True
    assert raised


def test_format_finding_marks_an_unsupported_finding_as_no_reference_in_the_kb() -> None:
    # The KB is the validation authority: a finding the documents do not support
    # must say so on its own line, never look like an ordinary cited finding.
    from cdi_kb.cli import format_finding
    from cdi_kb.findings import NO_KB_REFERENCE, Finding

    finding = Finding(
        finding_type="inferred_gap", severity="required", condition="sepsis", axis="agent",
        evidence_excerpt="Blood culture: E. coli", recommendation="Document the infective agent.",
        citations=(), dedupe_key="sepsis|agent", kb_status=NO_KB_REFERENCE,
    )
    rendered = format_finding(finding)
    assert NO_KB_REFERENCE in rendered
    assert "source:" not in rendered


def test_format_finding_prints_sources_for_a_supported_finding() -> None:
    from cdi_kb.cli import format_finding
    from cdi_kb.findings import Finding, VerifiedCitation

    finding = Finding(
        finding_type="specificity_gap", severity="required", condition="sepsis", axis="agent",
        evidence_excerpt="sepsis", recommendation="Document the infective agent.",
        citations=(VerifiedCitation(clause_id="CDI-2021/sepsis/p1", section_title="Sepsis",
                                    page=118, quote="The infective agent should be documented",
                                    authority="TCC"),),
        dedupe_key="sepsis|agent",
    )
    rendered = format_finding(finding)
    assert "source: [TCC] CDI-2021/sepsis/p1 (p.118)" in rendered
    assert "no reference in the KB" not in rendered


def test_audit_command_reports_an_llm_stage_failure_without_failing_the_audit(tmp_path, capsys) -> None:
    from cdi_kb import cli

    note = tmp_path / "note.txt"
    note.write_text("Known CKD, on regular follow-up.", encoding="utf-8")

    def exploding_stage(_note_text, _requirements, _index):
        raise RuntimeError("inference unavailable")

    assert cli.main(["audit", str(note), "--llm"], llm_stage=exploding_stage) == 0
    out = capsys.readouterr().out
    assert "chronic kidney disease" in out
    assert "llm stage unavailable" in out


def test_format_finding_does_not_say_missing_for_a_provider_confirmation_finding() -> None:
    # "malnutrition — missing provider_confirmation" reads as a missing axis.
    # The finding is that a diagnosis lacks the treating doctor's confirmation.
    from cdi_kb.cli import format_finding
    from cdi_kb.findings import Finding, VerifiedCitation

    finding = Finding(
        finding_type="provider_confirmation", severity="recommended",
        condition="malnutrition", axis="provider_confirmation",
        evidence_excerpt="documented in the allied_health note",
        recommendation="Please document the condition in the medical record.",
        citations=(VerifiedCitation(clause_id="CDI-2021/allied-health/p2",
                                    section_title="Allied Health", page=130, quote="q",
                                    authority="TCC"),),
        dedupe_key="malnutrition|provider_confirmation",
    )
    headline = format_finding(finding).splitlines()[0]
    assert "missing" not in headline
    assert "malnutrition" in headline
    assert "documented in the allied_health note" in format_finding(finding)


@pytest.mark.parametrize(
    ("finding_type", "condition", "axis", "expected"),
    [("copy_forward", "note", "copy_forward", "content carried forward"),
     ("conflicting_documentation", "myocardial ischemia", "conflicting_type",
      "conflicting type documented")],
)
def test_format_finding_headline_reads_as_the_actual_problem(
    finding_type, condition, axis, expected,
) -> None:
    # "note — missing copy_forward" and "myocardial ischemia — missing
    # conflicting_type" both describe the wrong problem. Nothing is missing.
    from cdi_kb.cli import format_finding
    from cdi_kb.findings import Finding, VerifiedCitation

    finding = Finding(
        finding_type=finding_type, severity="recommended", condition=condition, axis=axis,
        evidence_excerpt="evidence here", recommendation="Please clarify.",
        citations=(VerifiedCitation(clause_id="CDI-2021/x/p1", section_title="X",
                                    page=1, quote="q", authority="TCC"),),
        dedupe_key=f"{condition}|{axis}",
    )
    headline = format_finding(finding).splitlines()[0]
    assert "missing" not in headline, headline
    assert expected in headline, headline
