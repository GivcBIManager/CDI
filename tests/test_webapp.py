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


def test_audit_endpoint_rejects_xss_doc_type() -> None:
    response = client.post(
        "/api/audit",
        json={"note_text": "Known CKD, stable.", "doc_type": "<img src=x onerror=alert(1)>", "use_llm": False},
    )
    assert response.status_code == 422


def test_audit_endpoint_rejects_any_as_explicit_doc_type() -> None:
    # The dropdown only ever offers Auto (omitted/null) + the 5 concrete
    # types -- "any" is the internal auto-detect fallback value, never a
    # valid client-supplied choice.
    response = client.post(
        "/api/audit", json={"note_text": "Known CKD, stable.", "doc_type": "any", "use_llm": False}
    )
    assert response.status_code == 422


def test_index_page_escapes_server_supplied_fields_before_innerhtml() -> None:
    # Defense in depth: the JS must run every server-supplied field (findings
    # are KB-authored today, but active_doc_type/condition/axis/severity/
    # recommendation/clause_id/page/quote all reach the page verbatim from
    # the API response) through an escaping helper before string-concatenating
    # into innerHTML -- never interpolate raw response text into innerHTML.
    response = client.get("/")
    text = response.text
    assert "function esc(" in text
    for field in ("d.active_doc_type", "f.condition", "f.axis", "f.severity",
                  "f.recommendation", "c.clause_id", "c.page", "c.quote"):
        assert f"esc({field})" in text, f"{field} is interpolated without esc()"
