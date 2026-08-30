"""KB verification: five checks proving every layer matches the source PDFs.

V1  Extraction fidelity: every stored clause text occurs in the raw page text of
    its OWN source PDF (clauses are grouped by the clause_id's source-id prefix
    and checked against that source only, not the booklet). A clause whose
    prefix does not match a known config.SOURCES id is itself a V1 failure.
V2  Citation integrity: every requirement citation's quote matches its clause
    (find_quote >= threshold) and its clause_id resolves in Layer 1.
V3  Retrieval adequacy (two-tier): for every requirement, searching the condition +
    required-axis name retrieves the cited clause's section in the top 5 (Tier 1).
    Some entries have no condition-specific governing clause in the source and are,
    by reviewed decision, anchored solely to the generic "Documenting for Specificity"
    mandate clause — a clause that structurally never contains the condition's name,
    so Tier 1 cannot fairly test it. For those (and only those) entries, Tier 2 tests
    the retrieval contract they actually have: an axis-level query ("documenting
    specificity" + required axis names, no condition name) must surface that section
    in the top 5. Entries that pass only via Tier 2 are not silently allowlisted: they
    are counted in stats["mandate_anchored_entries"] and named in report.notes as
    "V3-INFO" lines, printed by the CLI. If Tier 2 also fails, that is a V3 failure —
    there is no further fallback.
V4  is enforced structurally at runtime in findings.py (tested in Task 8/9).
V5  Coverage: all EXPECTED_CONDITIONS have an entry with a required axis.
"""

from dataclasses import dataclass, field

from cdi_kb import config
from cdi_kb.clauses import Clause, ClauseStore
from cdi_kb.extract import extract_pages
from cdi_kb.index import SearchIndex
from cdi_kb.normalize import find_quote, normalize
from cdi_kb.requirements_model import EXPECTED_CONDITIONS, load_requirements

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

    # V3 — retrieval finds the cited section (two-tier; see module docstring)
    mandate_anchored_entries = 0
    for req in requirements:
        required_axes = [a.axis for a in req.axes if a.level == "required"]
        query = f"{req.condition} {' '.join(required_axes)}"
        hits = index.search(query, expansions=req.synonyms, limit=5)
        cited_sections = {c.clause_id.rsplit("/", 1)[0] for c in
                          filter(None, (store.get(cit.clause_id) for cit in req.citations))}
        hit_sections = {h.clause_id.rsplit("/", 1)[0] for h in hits}

        if not cited_sections or cited_sections & hit_sections:
            continue  # nothing to check, or Tier 1 passed

        if cited_sections != {MANDATE_SECTION}:
            # Not mandate-anchored: a condition-specific citation should have been
            # findable by a condition-name query. No Tier 2 fallback applies.
            failures.append(f"V3 {req.condition}: cited section not in top-5 for query '{query}'")
            continue

        # Tier 2: every citation for this entry is the generic mandate clause, which
        # never names the condition — test its real retrieval contract instead.
        axis_query = f"documenting specificity {' '.join(required_axes)}"
        axis_hits = index.search(axis_query, limit=5)
        axis_hit_sections = {h.clause_id.rsplit("/", 1)[0] for h in axis_hits}
        if MANDATE_SECTION not in axis_hit_sections:
            failures.append(
                f"V3 {req.condition}: mandate-anchored citation not in top-5 for axis query '{axis_query}'"
            )
            continue

        mandate_anchored_entries += 1
        notes.append(
            f"V3-INFO {req.condition}: generic authority only — no condition-specific clause "
            "exists in source; retrieval verified at axis level"
        )

    # V5 — coverage
    present = {r.condition for r in requirements}
    for condition in EXPECTED_CONDITIONS:
        if condition not in present:
            failures.append(f"V5 missing requirement entry: {condition}")
    for req in requirements:
        if not any(a.level == "required" for a in req.axes):
            failures.append(f"V5 {req.condition}: no required axis")

    store.close()
    index.close()
    stats = {
        "clauses": len(clauses),
        "requirements": len(requirements),
        "citations_checked": citations_checked,
        "mandate_anchored_entries": mandate_anchored_entries,
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
