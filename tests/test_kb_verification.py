"""V1-V5: prove the KB matches the source documents. Requires `build-kb` run first."""

import json

from cdi_kb import config
from cdi_kb.clauses import Clause, ClauseStore
from cdi_kb.index import SearchIndex
from cdi_kb.verify import MANDATE_SECTION, run_verification


def test_kb_verification_all_checks_pass() -> None:
    report = run_verification()
    assert report.passed, "KB verification failures:\n" + "\n".join(report.failures)


def test_stats_are_reported() -> None:
    report = run_verification()
    assert report.stats["clauses"] > 200
    assert report.stats["requirements"] == 20
    assert report.stats["citations_checked"] >= 20


def test_stats_report_per_source_counts() -> None:
    report = run_verification()
    assert report.stats["sources"] == 10
    assert report.stats["clauses_CHI-ANEMIA"] > 10


def test_mandate_anchored_entries_are_named_in_notes() -> None:
    # Post CHI-upgrade (Task 6): heart failure, stroke and obesity were all re-anchored to
    # condition-specific CHI clauses, so no requirement entry is mandate-anchored (generic
    # authority only) any more. The Tier-2 mandate-anchor path itself stays covered by
    # test_mandate_anchor_tier_verified_via_axis_query below with a synthetic fixture.
    report = run_verification()
    assert report.stats["mandate_anchored_entries"] == 0
    named = set()
    for note in report.notes:
        assert note.startswith("V3-INFO "), note
        if "generic authority only" not in note:
            continue  # a different V3-INFO fallback tier (title-reachable); see below
        condition = note[len("V3-INFO "):].split(":", 1)[0]
        named.add(condition)
    assert named == set()


def test_title_reachable_entries_are_named_in_notes() -> None:
    report = run_verification()
    assert report.stats["title_reachable_entries"] >= 1
    named = {
        note[len("V3-INFO "):].split(":", 1)[0]
        for note in report.notes
        if "reachable by title query only" in note
    }
    assert {"acute kidney injury", "diabetes mellitus"} <= named


def test_mandate_anchor_tier_verified_via_axis_query(tmp_path, monkeypatch) -> None:
    """Synthetic regression test for V3's Tier-2 (mandate-anchored) fallback.

    Real KB data no longer exercises this path (see test above), so this test builds a
    tmp ClauseStore/SearchIndex containing only the generic mandate clause, plus a
    requirement whose sole citation is that clause. The standard "condition + axis" query
    must MISS (the mandate text never names the condition), while the axis-only
    "documenting specificity <axis>" query must find it — the exact contract documented in
    verify.py's module docstring.
    """
    mandate_clause = Clause(
        clause_id=f"{MANDATE_SECTION}/p1",
        section_title="Documenting for Specificity",
        page=62,
        text=(
            "When documenting any condition, use as many of these descriptors as clinically "
            "relevant to convey full specificity of the condition."
        ),
    )

    db_path = tmp_path / "kb.sqlite"
    store = ClauseStore(db_path)
    store.rebuild([mandate_clause])
    store.close()
    index = SearchIndex(db_path)
    index.rebuild([mandate_clause])
    index.close()

    raw_text_dir = tmp_path / "raw_text"
    raw_text_dir.mkdir()
    (raw_text_dir / "fake-booklet.json").write_text(
        json.dumps([{"page_number": 62, "text": mandate_clause.text}]), encoding="utf-8"
    )

    requirements_dir = tmp_path / "requirements"
    requirements_dir.mkdir()
    (requirements_dir / "synthfoo.yaml").write_text(
        "condition: synthfoo\n"
        "synonyms: [synthfoo-synonym]\n"
        "axes:\n"
        "  - axis: agent\n"
        "    level: required\n"
        "    evidence_terms: [synthfoo-agent]\n"
        "recommendation: synthetic fixture, not a real requirement.\n"
        "citations:\n"
        f'  - clause_id: "{mandate_clause.clause_id}"\n'
        f'    quote: "{mandate_clause.text}"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        config,
        "SOURCES",
        {
            "CDI-2021": config.SourceDoc(
                source_id="CDI-2021",
                path=tmp_path / "fake-booklet.pdf",
                title="Fake Booklet",
                authority="TEST",
                genre="booklet",
            )
        },
    )
    monkeypatch.setattr(config, "KB_DB", db_path)
    monkeypatch.setattr(config, "RAW_TEXT_DIR", raw_text_dir)
    monkeypatch.setattr(config, "REQUIREMENTS_DIR", requirements_dir)

    report = run_verification()

    assert report.stats["mandate_anchored_entries"] == 1
    assert any(
        note.startswith("V3-INFO synthfoo") and "generic authority only" in note
        for note in report.notes
    )
    assert not any(f.startswith("V3 synthfoo") for f in report.failures)
