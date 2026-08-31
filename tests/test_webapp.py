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


def test_audit_api_exposes_kb_status_on_every_finding() -> None:
    from fastapi.testclient import TestClient

    from cdi_kb.webapp import app

    client = TestClient(app)
    payload = client.post("/api/audit", json={"note_text": "Known CKD, on regular follow-up."}).json()
    assert payload["findings"]
    assert all("kb_status" in finding for finding in payload["findings"])


def test_audit_api_exposes_llm_error_field() -> None:
    from fastapi.testclient import TestClient

    from cdi_kb.webapp import app

    client = TestClient(app)
    payload = client.post("/api/audit", json={"note_text": "Known CKD."}).json()
    assert "llm_error" in payload


def test_page_renders_the_no_reference_marker() -> None:
    # The browser view must distinguish a KB-supported finding from one the
    # documents do not cover -- otherwise "no reference in the KB" is invisible
    # to the only audience that matters.
    from cdi_kb.webapp import _PAGE

    assert "kb_status" in _PAGE


# --- findings matrix: severity x finding type ------------------------------

def _finding(finding_type, severity, key):
    from cdi_kb.findings import Finding, VerifiedCitation
    return Finding(
        finding_type=finding_type, severity=severity, condition=key.split("|")[0],
        axis=key.split("|")[1], evidence_excerpt="e", recommendation="r",
        citations=(VerifiedCitation(clause_id="CDI-2021/x/p1", section_title="X", page=1, quote="q"),),
        dedupe_key=key,
    )


def test_matrix_has_one_row_per_finding_type_present() -> None:
    from cdi_kb.webapp import build_matrix

    rows = build_matrix([
        _finding("specificity_gap", "required", "sepsis|agent"),
        _finding("copy_forward", "recommended", "note|copy_forward"),
    ])
    assert [row["finding_type"] for row in rows] == ["specificity_gap", "copy_forward"]


def test_matrix_omits_finding_types_with_no_findings() -> None:
    from cdi_kb.webapp import build_matrix

    rows = build_matrix([_finding("specificity_gap", "required", "sepsis|agent")])
    assert [row["finding_type"] for row in rows] == ["specificity_gap"]


def test_matrix_splits_each_row_into_required_and_recommended() -> None:
    from cdi_kb.webapp import build_matrix

    rows = build_matrix([
        _finding("specificity_gap", "required", "sepsis|agent"),
        _finding("specificity_gap", "recommended", "uti|site"),
    ])
    row = rows[0]
    assert [f["dedupe_key"] for f in row["required"]] == ["sepsis|agent"]
    assert [f["dedupe_key"] for f in row["recommended"]] == ["uti|site"]


def test_matrix_rows_follow_a_fixed_display_order_not_arrival_order() -> None:
    # Deterministic findings should read before inferred ones regardless of the
    # order run_audit happened to append them in.
    from cdi_kb.webapp import build_matrix

    rows = build_matrix([
        _finding("inferred_gap", "required", "sepsis|type"),
        _finding("specificity_gap", "required", "anemia|type"),
    ])
    assert [row["finding_type"] for row in rows] == ["specificity_gap", "inferred_gap"]


def test_every_finding_type_the_audit_can_emit_has_a_matrix_label() -> None:
    # A type with no label would render as a bare identifier in the grid header.
    from cdi_kb.webapp import FINDING_TYPE_LABELS

    emitted = {"specificity_gap", "inferred_gap", "completeness_gap", "necessity_mismatch",
               "provider_confirmation", "copy_forward", "conflicting_documentation"}
    assert emitted <= set(FINDING_TYPE_LABELS)


def test_matrix_row_carries_a_label_and_counts() -> None:
    from cdi_kb.webapp import build_matrix

    row = build_matrix([
        _finding("specificity_gap", "required", "sepsis|agent"),
        _finding("specificity_gap", "required", "anemia|type"),
        _finding("specificity_gap", "recommended", "uti|site"),
    ])[0]
    assert row["label"]
    assert row["counts"] == {"required": 2, "recommended": 1}


def test_audit_api_returns_the_matrix() -> None:
    from fastapi.testclient import TestClient

    from cdi_kb.webapp import app

    payload = TestClient(app).post(
        "/api/audit", json={"note_text": "Known CKD, on regular follow-up."}).json()
    assert payload["matrix"], payload
    assert all({"finding_type", "label", "required", "recommended", "counts"} <= set(r)
               for r in payload["matrix"])


def test_page_renders_the_matrix_grid() -> None:
    from cdi_kb.webapp import _PAGE

    assert "matrix" in _PAGE
    assert "Required" in _PAGE and "Recommended" in _PAGE


def _script_block() -> str:
    import re

    from cdi_kb.webapp import _PAGE
    match = re.search(r"<script>(.*?)</script>", _PAGE, re.S)
    assert match, "page has no script block"
    return match.group(1)


def test_page_script_defines_the_render_helpers() -> None:
    js = _script_block()
    for fn in ("function esc(", "function headline(", "function renderFinding(", "async function audit("):
        assert fn in js, f"missing {fn}"


def test_page_script_brackets_balance() -> None:
    """The page is a hand-written JS string inside a Python literal, so an
    unbalanced brace breaks the whole UI at runtime with nothing failing at
    import time. Cheap structural guard: skip strings, line comments and regex
    literals (the escaper uses /"/g and friends), then count."""
    js = _script_block()
    depth = {"(": 0, "[": 0, "{": 0}
    closers = {")": "(", "]": "[", "}": "{"}
    i, n, quote = 0, len(js), None
    while i < n:
        ch = js[i]
        if quote is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if js.startswith("//", i):
            newline = js.find("\n", i)
            i = n if newline < 0 else newline
            continue
        if ch in "'\"`":
            quote = ch
            i += 1
            continue
        if ch == "/" and i + 1 < n and js[i + 1] not in "/*":
            j = i + 1
            while j < n and js[j] != "/":
                j += 2 if js[j] == "\\" else 1
            if j < n:
                i = j + 1
                continue
        if ch in depth:
            depth[ch] += 1
        elif ch in closers:
            depth[closers[ch]] -= 1
        i += 1
    assert quote is None, "unterminated string literal in the page script"
    assert depth == {"(": 0, "[": 0, "{": 0}, depth
