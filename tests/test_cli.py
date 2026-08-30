import json

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
