from fastapi.testclient import TestClient

from cdi_kb.webapp import app

client = TestClient(app)


def test_index_serves_ui() -> None:
    response = client.get("/")
    assert response.status_code == 200 and "CDI Audit Demo" in response.text


def test_audit_endpoint_returns_cited_findings() -> None:
    response = client.post("/api/audit", json={"note_text": "Known CKD, stable.", "use_llm": False})
    assert response.status_code == 200
    findings = response.json()["findings"]
    assert any(f["dedupe_key"] == "chronic kidney disease|stage" for f in findings)
    assert all(f["citations"] for f in findings)


def test_search_endpoint() -> None:
    response = client.get("/api/search", params={"q": "specificity stage"})
    assert response.status_code == 200 and isinstance(response.json()["hits"], list)
