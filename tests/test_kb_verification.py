"""V1-V5: prove the KB matches the source documents. Requires `build-kb` run first."""

import json
import re

from cdi_kb.extract import cache_path
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
    # 20 -> 35: the booklet was surveyed for every section carrying a
    # condition-specific documentation mandate that names a specificity axis.
    assert report.stats["requirements"] == 35
    assert report.stats["citations_checked"] >= 20


def test_doc_type_and_necessity_stats_are_reported() -> None:
    # Real-data breakdown (Task 7, updated for CHI-LRTI): 20 diagnosis entries carry 40
    # citations (37 + the 3 CHI-LRTI secondaries pneumonia gained when the Lower
    # Respiratory Tract Infection protocol was registered as a source); the 5
    # doc_requirements files carry 19 elements / 20 citations; the 4 necessity rules
    # (LBPMRI excluded, flowchart genre) carry 8 citations. citations_checked now covers
    # all three rule layers, not just diagnosis.
    report = run_verification()
    assert report.stats["doc_type_rules"] == 19
    assert report.stats["necessity_rules"] == 4
    # 40 -> 58 diagnosis citations: the 15 conditions added from the booklet survey
    # carry 18 citations between them (several cite two clauses).
    assert report.stats["citations_checked"] == 58 + 20 + 8


def test_mixed_authority_entries_are_named_in_notes() -> None:
    # Task 7 (resolves a Task 6 review finding): an entry that cites the generic
    # specificity mandate ALONGSIDE a condition-specific clause (mixed authority) gets a
    # dedicated V3-INFO note distinct from the mandate-anchored / title-reachable tiers --
    # it is not a failure, just a visible flag that one axis may still rest on generic
    # authority only. obesity is the known case: its 'type' axis is mandate-only while
    # 'stage' cites a CHI-BARIATRIC clause.
    report = run_verification()
    assert report.stats["mixed_authority_entries"] >= 1
    named = {
        note[len("V3-INFO "):].split(":", 1)[0]
        for note in report.notes
        if "retains generic-authority citation" in note
    }
    assert "obesity" in named


def test_stats_report_per_source_counts() -> None:
    report = run_verification()
    assert report.stats["sources"] == 42
    # 18 -> 19 after step 4: the page-furniture filter changes where segment
    # boundaries fall, so this source re-paragraphs by one clause. Extraction
    # itself is byte-identical for CHI-LRTI (it had no fused words).
    assert report.stats["clauses_CHI-LRTI"] == 19
    assert report.stats["clauses_CHI-ANEMIA"] > 10
    # Every MOH source must clear the build floor; a source that quietly drops
    # to zero clauses would still pass V1-V5 (nothing to check) while silently
    # leaving an authority out of the KB.
    moh = [sid for sid, s in config.SOURCES.items() if s.genre == "moh_protocol"]
    assert len(moh) == 31
    for source_id in moh:
        assert report.stats[f"clauses_{source_id}"] >= 5, source_id


def test_mandate_anchored_entries_are_named_in_notes() -> None:
    # urinary tract infection is the one entry whose citations are only the generic
    # specificity mandate clause -- neither the booklet nor any CHI source carries a
    # condition-specific clause for it. Before the 31 MOH sources were ingested, the
    # standard "condition + axis" query happened to still surface that mandate clause
    # inside its top 5 results, so V3 reported the entry as title-reachable rather than
    # mandate-anchored. After MOH ingestion diluted the index, the standard query no
    # longer surfaces it, so V3 correctly falls back to the axis-level query and reports
    # urinary tract infection as mandate-anchored -- the honest outcome, since there was
    # never a condition-specific clause to anchor it to. The Tier-2 mandate-anchor path
    # itself stays covered by test_mandate_anchor_tier_verified_via_axis_query below with
    # a synthetic fixture.
    #
    # Discriminator is the FULL mandate-tier phrase, not just "generic authority only":
    # the mixed-authority note (test above) also ends with "...generic authority only" --
    # a bare substring check on that shorter phrase would wrongly count mixed-authority
    # entries (e.g. obesity) as mandate-anchored here too. Only the mandate-anchored
    # tier's note continues on to name the reason ("— no condition-specific clause...").
    report = run_verification()
    assert report.stats["mandate_anchored_entries"] == 1
    named = set()
    for note in report.notes:
        assert note.startswith("V3-INFO "), note
        if "generic authority only — no condition-specific clause" not in note:
            continue  # a different V3-INFO fallback tier (title-reachable/mixed-authority); see above
        condition = note[len("V3-INFO "):].split(":", 1)[0]
        named.add(condition)
    assert named == {"urinary tract infection"}


def test_title_reachable_entries_are_named_in_notes() -> None:
    report = run_verification()
    assert report.stats["title_reachable_entries"] >= 1
    named = {
        note[len("V3-INFO "):].split(":", 1)[0]
        for note in report.notes
        if "reachable by title query only" in note
    }
    assert {"acute kidney injury", "diabetes mellitus"} <= named


def test_moh_ingestion_does_not_worsen_retrieval_fallbacks() -> None:
    # The dilution guard. The pre-MOH baseline, measured on 2026-09-01 with 11 sources
    # and 3,017 clauses, was title_reachable_entries = 5 and mandate_anchored_entries = 0.
    # After ingesting the 31 MOH sources, bringing the KB to 4,650 clauses, those numbers
    # moved to 7 and 1.
    #
    # That movement is the V3 fallback tiers doing exactly what they were built for: the
    # larger index pushed some cited CHI/booklet sections out of the standard query's top
    # 5 results, and V3 fell back to the title query (or, for urinary tract infection, all
    # the way to the axis-level query) to keep confirming those citations are real. `cli
    # verify` still reports VERIFICATION PASSED -- every cited section remains reachable,
    # just via a named fallback query instead of the standard condition query. Urinary
    # tract infection's citations genuinely are only the generic mandate clause, so
    # reporting it as mandate-anchored now is more honest than the pre-MOH accident of the
    # standard query happening to still find it.
    #
    # The guard's purpose is to catch FUTURE growth, not to relitigate this one. If it
    # fails, investigate and fix retrieval (or narrow the source set) -- do NOT re-baseline
    # these numbers again just to make it pass.
    report = run_verification()
    assert report.stats["title_reachable_entries"] <= 7
    # <=1, not ==1: this line is deliberately a ceiling against future growth, not a pin
    # on today's exact value -- test_mandate_anchored_entries_are_named_in_notes above
    # already pins mandate_anchored_entries == 1 precisely.
    assert report.stats["mandate_anchored_entries"] <= 1


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
    cache_path(tmp_path / "fake-booklet.pdf", raw_text_dir).write_text(
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


def _write_fake_source(tmp_path, monkeypatch, clause: Clause) -> None:
    """Shared fixture plumbing for the two synthetic V2-failure tests below: a tmp
    ClauseStore/SearchIndex containing a single real clause, plus a matching raw-text
    cache so V1's extract_pages() call never touches a real PDF."""
    db_path = tmp_path / "kb.sqlite"
    store = ClauseStore(db_path)
    store.rebuild([clause])
    store.close()
    index = SearchIndex(db_path)
    index.rebuild([clause])
    index.close()

    raw_text_dir = tmp_path / "raw_text"
    raw_text_dir.mkdir()
    cache_path(tmp_path / "fake-booklet.pdf", raw_text_dir).write_text(
        json.dumps([{"page_number": clause.page, "text": clause.text}]), encoding="utf-8"
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


def test_fabricated_doc_element_quote_yields_v2_doc_failure(tmp_path, monkeypatch) -> None:
    clause = Clause(
        clause_id="CDI-2021/fake-doc-section/p1",
        section_title="Fake Doc Section",
        page=10,
        text="This is the real verbatim sentence stored in the clause.",
    )
    _write_fake_source(tmp_path, monkeypatch, clause)

    requirements_dir = tmp_path / "requirements"
    requirements_dir.mkdir()  # empty: this test only exercises the doc-requirements layer

    doc_requirements_dir = tmp_path / "doc_requirements"
    doc_requirements_dir.mkdir()
    (doc_requirements_dir / "fake.yaml").write_text(
        "doc_type: discharge_summary\n"
        "elements:\n"
        "  - name: fake_element\n"
        "    evidence_terms: [fake]\n"
        "    level: required\n"
        "    recommendation: fake recommendation\n"
        "    citations:\n"
        f'      - clause_id: "{clause.clause_id}"\n'
        '        quote: "This fabricated sentence never appears in the clause text."\n',
        encoding="utf-8",
    )

    necessity_dir = tmp_path / "necessity"
    necessity_dir.mkdir()  # empty: not exercised by this test

    monkeypatch.setattr(config, "REQUIREMENTS_DIR", requirements_dir)
    monkeypatch.setattr(config, "DOC_REQUIREMENTS_DIR", doc_requirements_dir)
    monkeypatch.setattr(config, "NECESSITY_DIR", necessity_dir)

    report = run_verification()

    assert any(
        f.startswith("V2 doc:discharge_summary/fake_element") and "quote does not match" in f
        for f in report.failures
    ), report.failures


def test_fabricated_necessity_quote_yields_v2_necessity_failure(tmp_path, monkeypatch) -> None:
    clause = Clause(
        clause_id="CDI-2021/fake-nec-section/p1",
        section_title="Fake Necessity Section",
        page=11,
        text="This is the real verbatim sentence backing the necessity rule.",
    )
    _write_fake_source(tmp_path, monkeypatch, clause)

    requirements_dir = tmp_path / "requirements"
    requirements_dir.mkdir()  # empty: not exercised by this test

    doc_requirements_dir = tmp_path / "doc_requirements"
    doc_requirements_dir.mkdir()  # empty: not exercised by this test

    necessity_dir = tmp_path / "necessity"
    necessity_dir.mkdir()
    (necessity_dir / "fake.yaml").write_text(
        "order: fake-order\n"
        "display_name: Fake Order Test\n"
        "order_terms: [fakeorder]\n"
        "context_cues: [order]\n"
        "valid_indication_terms: [fake]\n"
        "recommendation: fake recommendation\n"
        "citations:\n"
        f'  - clause_id: "{clause.clause_id}"\n'
        '    quote: "This fabricated sentence never appears in the clause text either."\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "REQUIREMENTS_DIR", requirements_dir)
    monkeypatch.setattr(config, "DOC_REQUIREMENTS_DIR", doc_requirements_dir)
    monkeypatch.setattr(config, "NECESSITY_DIR", necessity_dir)

    report = run_verification()

    assert any(
        f.startswith("V2 necessity:fake-order") and "quote does not match" in f
        for f in report.failures
    ), report.failures


_FOLD_HEADER = re.compile(r":\s*[>|][-+]?\s*$")

_AUTHORED_YAML_DIRS = (
    config.REQUIREMENTS_DIR, config.DOC_REQUIREMENTS_DIR, config.NECESSITY_DIR,
    config.PROVIDER_RULES_DIR, config.INTEGRITY_RULES_DIR,
)


def test_no_folded_yaml_block_wraps_a_line_on_a_hyphen() -> None:
    """A folded scalar (`>-`) rejoins its wrapped lines with a SPACE, so a break
    inside a hyphenated word silently corrupts the parsed string.

    malignant-neoplasm's citation wrapped after "in-", so the quote parsed back as
    "in- situ" where the booklet says "in-situ". It cleared V2 at 0.9509 against the
    0.95 threshold -- one bad character diluted by a long quote -- and reached the
    clinician verbatim, because findings._verified_citations reports the AUTHORED
    quote, not the clause text. The same typo in a SHORTER quote scores below
    threshold and silently drops the whole finding instead, so this defect corrupts
    or deletes depending only on quote length. Neither failure is visible.

    Checked on raw text, not the parsed model: once YAML has folded the block the
    evidence is gone. No false positives -- real prose never ends a line on a bare
    hyphen (pneumonia's "community-, hospital- or ventilator-acquired" ends those
    lines with a comma or a word).
    """
    offenders: list[str] = []
    for directory in _AUTHORED_YAML_DIRS:
        for path in sorted(directory.glob("*.yaml")):
            indent = -1
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _FOLD_HEADER.search(line):
                    indent = len(line) - len(line.lstrip())
                    continue
                if indent >= 0 and (not line.strip() or len(line) - len(line.lstrip()) <= indent):
                    indent = -1
                if indent >= 0 and line.rstrip().endswith("-"):
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, (
        "folded block wrapped on a hyphen -- the parsed text gains a space:\n"
        + "\n".join(offenders)
    )
