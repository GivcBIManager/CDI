from fastapi.testclient import TestClient

from cdi_kb.webapp import app

client = TestClient(app)


def test_index_serves_ui() -> None:
    response = client.get("/")
    assert response.status_code == 200 and "CDI Audit Demo" in response.text


def test_index_serves_doc_type_dropdown() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="doctype"' in response.text
    assert "discharge_summary" in response.text and "diagnosis_list" in response.text


def test_audit_endpoint_returns_cited_findings() -> None:
    response = client.post("/api/audit", json={"note_text": "Known CKD, stable.", "use_llm": False})
    assert response.status_code == 200
    findings = response.json()["findings"]
    assert any(f["dedupe_key"] == "chronic kidney disease|stage" for f in findings)
    assert all(f["citations"] for f in findings)


def test_audit_endpoint_echoes_active_doc_type() -> None:
    response = client.post("/api/audit", json={"note_text": "Known CKD, stable.", "use_llm": False})
    assert response.status_code == 200
    assert response.json()["active_doc_type"] == "any"


def test_audit_endpoint_with_doc_type_returns_completeness_gap_and_active_doc_type() -> None:
    note = (
        "Admitted with community acquired pneumonia. Principal diagnosis: pneumonia.\n"
        "Procedure performed: chest drain insertion under local anesthesia in theatre.\n"
    )
    response = client.post(
        "/api/audit", json={"note_text": note, "doc_type": "discharge_summary", "use_llm": False}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["active_doc_type"] == "discharge_summary"
    assert any(f["finding_type"] == "completeness_gap" for f in body["findings"])


def test_audit_endpoint_auto_doc_type_on_plain_note_returns_any() -> None:
    response = client.post("/api/audit", json={"note_text": "Known CKD, stable.", "doc_type": None, "use_llm": False})
    assert response.status_code == 200
    assert response.json()["active_doc_type"] == "any"


def test_search_endpoint() -> None:
    response = client.get("/api/search", params={"q": "specificity stage"})
    assert response.status_code == 200 and isinstance(response.json()["hits"], list)
