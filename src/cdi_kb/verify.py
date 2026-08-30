"""KB verification: five checks proving every layer matches the source PDFs.

V1  Extraction fidelity: every stored clause text occurs in the raw page text of
    its OWN source PDF (clauses are grouped by the clause_id's source-id prefix
    and checked against that source only, not the booklet). A clause whose
    prefix does not match a known config.SOURCES id is itself a V1 failure.
V2  Citation integrity: every requirement citation's quote matches its clause
    (find_quote >= threshold) and its clause_id resolves in Layer 1. Since Task 7
    this covers all three rule layers, not just diagnosis: every data/requirements
    entry citation, every data/doc_requirements element citation ("V2 doc:<doc_type>/
    <element>" on failure), and every data/necessity rule citation ("V2 necessity:
    <order>" on failure). All are counted in stats["citations_checked"].
V3  Retrieval adequacy (two fallback tiers, both visible): for every requirement,
    searching the condition + required-axis name retrieves the cited clause's
    section in the top 5 (the standard query). Two categories of entry have a
    legitimately different retrieval contract and get a named fallback instead of
    an unconditional failure — neither is silently allowlisted:
      - Mandate-anchored entries: every citation is the generic "Documenting for
        Specificity" clause, which structurally never contains the condition's
        name, so the standard query cannot fairly test it. An axis-level query
        ("documenting specificity" + required axis names, no condition name) must
        surface that section in the top 5 instead. Counted in
        stats["mandate_anchored_entries"], named in report.notes as "V3-INFO"
        lines.
      - Title-reachable entries: not mandate-anchored, but the standard query
        misses because the multi-source index dilutes it (unrelated CHI-source
        clauses now outrank the citation). A query built from the cited clause(s)
        own section_title(s) (expansions = the entry's synonyms) must surface the
        cited section in the top 5 instead. Counted in
        stats["title_reachable_entries"], named in report.notes as "V3-INFO"
        lines.
    If an entry qualifies for neither fallback, or its fallback also misses, that
    is a real V3 failure — there is no further fallback beyond these two.

    Since Task 7, doc_requirements files and necessity rules get the same standard
    query + title-reachability fallback contract (mandate-anchoring does not apply
    to them — none of their citations are the generic mandate clause):
      - Per doc-type file: query "<doc type words> documentation requirements"
        (e.g. "discharge summary documentation requirements"); passes if ANY
        section cited by that file's elements is in the top 5 (union over the
        file's citations, not per-element).
      - Per necessity rule: query "<display_name> criteria indications" with
        expansions = the rule's order_terms; passes if a cited section is in the
        top 5.
    A miss falls back to the title query exactly as for diagnosis entries, counted
    in the same stats["title_reachable_entries"] and named "V3-INFO doc:<doc_type>"
    / "V3-INFO necessity:<order>". A second miss is a real V3 failure.

    Task 7 also adds an axis-aware INFO note (not a failure, resolves a Task 6
    review finding): any diagnosis entry whose citations include BOTH the generic
    mandate section AND at least one condition-specific section (mixed authority)
    — meaning at least one of its axes may rest on the mandate clause alone even
    though the entry as a whole clears V3 — is flagged "V3-INFO <condition>: retains
    generic-authority citation ..." and counted in stats["mixed_authority_entries"].
V4  is enforced structurally at runtime in findings.py (tested in Task 8/9).
V5  Coverage: all EXPECTED_CONDITIONS have an entry with a required axis. Since
    Task 7 this also checks the other two rule layers: exactly the DOC_TYPES set
    has a doc_requirements file, exactly 4 necessity rules exist (LBPMRI excluded
    — flowchart genre, not yet linearized), and every doc-type element / necessity
    rule carries at least one citation (schema-enforced already, checked here too
    for a visible, layer-symmetric V5 contract).
"""

from dataclasses import dataclass, field

from cdi_kb import config
from cdi_kb.clauses import Clause, ClauseStore
from cdi_kb.extract import extract_pages
from cdi_kb.index import SearchIndex
from cdi_kb.normalize import find_quote, normalize
from cdi_kb.requirements_model import (
    DOC_TYPES,
    EXPECTED_CONDITIONS,
    load_doc_requirements,
    load_necessity_rules,
    load_requirements,
)

MANDATE_SECTION = f"{config.SOURCE_ID}/documenting-for-specificity"


@dataclass
class VerificationReport:
    passed: bool
    failures: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def run_verification() -> VerificationReport:
    failures: list[str] = []
    notes: list[str] = []
    full_source_by_id = {
        sid: normalize(" ".join(page.text for page in extract_pages(src.path, config.RAW_TEXT_DIR)))
        for sid, src in config.SOURCES.items()
    }
    store = ClauseStore(config.KB_DB)
    index = SearchIndex(config.KB_DB)
    clauses = store.all()
    requirements = load_requirements(config.REQUIREMENTS_DIR)
    doc_requirements = load_doc_requirements(config.DOC_REQUIREMENTS_DIR)
    necessity_rules = load_necessity_rules(config.NECESSITY_DIR)

    # V1 — every clause is verbatim text of its own source PDF (per-source, not booklet-only)
    clauses_by_source: dict[str, list[Clause]] = {}
    for clause in clauses:
        source_id = clause.clause_id.split("/", 1)[0]
        clauses_by_source.setdefault(source_id, []).append(clause)

    for source_id, group in clauses_by_source.items():
        source_text = full_source_by_id.get(source_id)
        if source_text is None:
            for clause in group:
                failures.append(f"V1 {clause.clause_id}: unknown source id '{source_id}'")
            continue
        for clause in group:
            if normalize(clause.text) not in source_text:
                failures.append(f"V1 {clause.clause_id}: clause text not found in source PDF")

    # V2 — every citation quote matches its clause
    citations_checked = 0
    for req in requirements:
        for citation in req.citations:
            citations_checked += 1
            clause = store.get(citation.clause_id)
            if clause is None:
                failures.append(f"V2 {req.condition}: clause_id {citation.clause_id} does not resolve")
                continue
            match = find_quote(citation.quote, clause.text, config.QUOTE_MATCH_THRESHOLD)
            if not match.found:
                failures.append(
                    f"V2 {req.condition}: quote does not match {citation.clause_id} (score {match.score})"
                )

    for doc_type, doc_req in doc_requirements.items():
        for element in doc_req.elements:
            for citation in element.citations:
                citations_checked += 1
                label = f"doc:{doc_type}/{element.name}"
                clause = store.get(citation.clause_id)
                if clause is None:
                    failures.append(f"V2 {label}: clause_id {citation.clause_id} does not resolve")
                    continue
                match = find_quote(citation.quote, clause.text, config.QUOTE_MATCH_THRESHOLD)
                if not match.found:
                    failures.append(
                        f"V2 {label}: quote does not match {citation.clause_id} (score {match.score})"
                    )

    for rule in necessity_rules:
        for citation in rule.citations:
            citations_checked += 1
            label = f"necessity:{rule.order}"
            clause = store.get(citation.clause_id)
            if clause is None:
                failures.append(f"V2 {label}: clause_id {citation.clause_id} does not resolve")
                continue
            match = find_quote(citation.quote, clause.text, config.QUOTE_MATCH_THRESHOLD)
            if not match.found:
                failures.append(
                    f"V2 {label}: quote does not match {citation.clause_id} (score {match.score})"
                )

    # V3 — retrieval finds the cited section (standard query + two named fallback
    # tiers; see module docstring)
    mandate_anchored_entries = 0
    title_reachable_entries = 0
    mixed_authority_entries = 0
    for req in requirements:
        required_axes = [a.axis for a in req.axes if a.level == "required"]
        query = f"{req.condition} {' '.join(required_axes)}"
        hits = index.search(query, expansions=req.synonyms, limit=5)
        cited_clauses = list(filter(None, (store.get(cit.clause_id) for cit in req.citations)))
        cited_sections = {c.clause_id.rsplit("/", 1)[0] for c in cited_clauses}
        hit_sections = {h.clause_id.rsplit("/", 1)[0] for h in hits}

        if MANDATE_SECTION in cited_sections and len(cited_sections) > 1:
            # Mixed authority: this entry is not purely mandate-anchored (it clears the
            # mandate-anchored branch below), but it still retains the generic mandate
            # clause alongside a condition-specific one — at least one axis may still
            # rest on generic authority only. Visible, not a failure (Task 7).
            mixed_authority_entries += 1
            notes.append(
                f"V3-INFO {req.condition}: retains generic-authority citation (mandate clause) "
                "alongside condition-specific clauses — at least one axis may rest on generic "
                "authority only"
            )

        if not cited_sections or cited_sections & hit_sections:
            continue  # nothing to check, or the standard query passed

        if cited_sections == {MANDATE_SECTION}:
            # Every citation for this entry is the generic mandate clause, which
            # never names the condition — test its real retrieval contract instead.
            axis_query = f"documenting specificity {' '.join(required_axes)}"
            axis_hits = index.search(axis_query, limit=5)
            axis_hit_sections = {h.clause_id.rsplit("/", 1)[0] for h in axis_hits}
            if MANDATE_SECTION not in axis_hit_sections:
                failures.append(
                    f"V3 {req.condition}: mandate-anchored citation not in top-5 for axis query "
                    f"'{axis_query}'"
                )
                continue

            mandate_anchored_entries += 1
            notes.append(
                f"V3-INFO {req.condition}: generic authority only — no condition-specific clause "
                "exists in source; retrieval verified at axis level"
            )
            continue

        # Not mandate-anchored: the standard condition-query missed. Before failing,
        # try the cited section's own title as the query — a multi-source index can
        # dilute the standard query with unrelated CHI-source hits even though the
        # citation is still findable by name.
        cited_titles = sorted({c.section_title for c in cited_clauses})
        title_query = " ".join(cited_titles)
        title_hits = index.search(title_query, expansions=req.synonyms, limit=5) if title_query else []
        title_hit_sections = {h.clause_id.rsplit("/", 1)[0] for h in title_hits}
        if cited_sections & title_hit_sections:
            title_reachable_entries += 1
            notes.append(
                f"V3-INFO {req.condition}: cited section reachable by title query only "
                "(index diluted by multi-source content)"
            )
            continue

        failures.append(f"V3 {req.condition}: cited section not in top-5 for query '{query}'")

    # V3 — doc_requirements files: one query per file, passes if any element's cited
    # section (union over the file) is in the top 5. No mandate-anchoring applies here
    # (no doc-type element cites the generic mandate clause) — only the standard query
    # and the title-reachability fallback.
    for doc_type, doc_req in doc_requirements.items():
        label = f"doc:{doc_type}"
        words = doc_type.replace("_", " ")
        query = f"{words} documentation requirements"
        hits = index.search(query, limit=5)
        hit_sections = {h.clause_id.rsplit("/", 1)[0] for h in hits}
        cited_clauses = list(filter(
            None,
            (store.get(cit.clause_id) for element in doc_req.elements for cit in element.citations),
        ))
        cited_sections = {c.clause_id.rsplit("/", 1)[0] for c in cited_clauses}

        if not cited_sections or cited_sections & hit_sections:
            continue  # nothing to check, or the standard query passed

        cited_titles = sorted({c.section_title for c in cited_clauses})
        title_query = " ".join(cited_titles)
        title_hits = index.search(title_query, limit=5) if title_query else []
        title_hit_sections = {h.clause_id.rsplit("/", 1)[0] for h in title_hits}
        if cited_sections & title_hit_sections:
            title_reachable_entries += 1
            notes.append(
                f"V3-INFO {label}: cited section reachable by title query only "
                "(index diluted by multi-source content)"
            )
            continue

        failures.append(f"V3 {label}: cited section not in top-5 for query '{query}'")

    # V3 — necessity rules: same standard-query + title-reachability contract, one
    # query per rule, expansions = the rule's own order_terms (its "synonyms").
    for rule in necessity_rules:
        label = f"necessity:{rule.order}"
        query = f"{rule.display_name} criteria indications"
        hits = index.search(query, expansions=rule.order_terms, limit=5)
        hit_sections = {h.clause_id.rsplit("/", 1)[0] for h in hits}
        cited_clauses = list(filter(None, (store.get(cit.clause_id) for cit in rule.citations)))
        cited_sections = {c.clause_id.rsplit("/", 1)[0] for c in cited_clauses}

        if not cited_sections or cited_sections & hit_sections:
            continue  # nothing to check, or the standard query passed

        cited_titles = sorted({c.section_title for c in cited_clauses})
        title_query = " ".join(cited_titles)
        title_hits = (
            index.search(title_query, expansions=rule.order_terms, limit=5) if title_query else []
        )
        title_hit_sections = {h.clause_id.rsplit("/", 1)[0] for h in title_hits}
        if cited_sections & title_hit_sections:
            title_reachable_entries += 1
            notes.append(
                f"V3-INFO {label}: cited section reachable by title query only "
                "(index diluted by multi-source content)"
            )
            continue

        failures.append(f"V3 {label}: cited section not in top-5 for query '{query}'")

    # V5 — coverage
    present = {r.condition for r in requirements}
    for condition in EXPECTED_CONDITIONS:
        if condition not in present:
            failures.append(f"V5 missing requirement entry: {condition}")
    for req in requirements:
        if not any(a.level == "required" for a in req.axes):
            failures.append(f"V5 {req.condition}: no required axis")

    # V5 — doc_requirements coverage: exactly the DOC_TYPES set has a file, and every
    # element carries a citation (schema already enforces min_length=1; checked again
    # here for a layer-symmetric, visible V5 contract).
    doc_types_present = set(doc_requirements)
    if doc_types_present != set(DOC_TYPES):
        failures.append(
            f"V5 doc_requirements: expected doc types {sorted(DOC_TYPES)}, got "
            f"{sorted(doc_types_present)}"
        )
    for doc_type, doc_req in doc_requirements.items():
        for element in doc_req.elements:
            if not element.citations:
                failures.append(f"V5 doc:{doc_type}/{element.name}: no citation")

    # V5 — necessity coverage: exactly 4 rules (LBPMRI excluded), every rule cited.
    if len(necessity_rules) != 4:
        failures.append(f"V5 necessity: expected 4 rules (LBPMRI excluded), got {len(necessity_rules)}")
    for rule in necessity_rules:
        if not rule.citations:
            failures.append(f"V5 necessity:{rule.order}: no citation")

    store.close()
    index.close()
    stats = {
        "clauses": len(clauses),
        "requirements": len(requirements),
        "citations_checked": citations_checked,
        "mandate_anchored_entries": mandate_anchored_entries,
        "title_reachable_entries": title_reachable_entries,
        "mixed_authority_entries": mixed_authority_entries,
        "doc_type_rules": sum(len(dr.elements) for dr in doc_requirements.values()),
        "necessity_rules": len(necessity_rules),
        "sources": len(config.SOURCES),
    }
    for source_id in config.SOURCES:
        stats[f"clauses_{source_id}"] = len(clauses_by_source.get(source_id, []))
    return VerificationReport(
        passed=not failures,
        failures=failures,
        stats=stats,
        notes=notes,
    )
