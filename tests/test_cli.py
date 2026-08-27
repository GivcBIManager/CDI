import json

from cdi_kb.cli import main


def test_audit_command_json_output(tmp_path, capsys) -> None:
    note = tmp_path / "note.txt"
    note.write_text("Known CKD, on regular follow-up.", encoding="utf-8")
    exit_code = main(["audit", str(note), "--json"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert any(f["dedupe_key"] == "chronic kidney disease|stage" for f in payload["findings"])


def test_audit_command_human_output(tmp_path, capsys) -> None:
    note = tmp_path / "note.txt"
    note.write_text("Known CKD.", encoding="utf-8")
    assert main(["audit", str(note)]) == 0
    out = capsys.readouterr().out
    assert "chronic kidney disease" in out and "CDI-2021/" in out
