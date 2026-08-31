"""Command-line entry points: python -m cdi_kb.cli <command>."""

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from cdi_kb import config
from cdi_kb.audit import run_audit
from cdi_kb.chi_chunker import chunk_chi
from cdi_kb.clauses import Clause, ClauseStore, chunk_booklet
from cdi_kb.extract import extract_pages
from cdi_kb.findings import KB_SUPPORTED, Finding
from cdi_kb.index import SearchIndex
from cdi_kb.normalize import normalize
from cdi_kb.requirements_model import DOC_TYPES
from cdi_kb.verify import run_verification

MIN_SOURCE_CLAUSES = 5
MIN_SOURCE_CHARS = 1000


def build_kb() -> tuple[int, int]:
    all_clauses: list[Clause] = []
    for source in config.SOURCES.values():
        pages = extract_pages(source.path, config.RAW_TEXT_DIR)
        extracted_chars = sum(len(page.text) for page in pages)
        clauses = chunk_booklet(pages) if source.genre == "booklet" else chunk_chi(pages, source)
        if len(clauses) < MIN_SOURCE_CLAUSES or extracted_chars < MIN_SOURCE_CHARS:
            raise ValueError(
                f"{source.source_id}: only {len(clauses)} clause(s) from {extracted_chars} extracted "
                f"char(s) — below the minimum ({MIN_SOURCE_CLAUSES} clauses / {MIN_SOURCE_CHARS} chars); "
                "source PDF may be unreadable or image-based"
            )
        print(f"{source.source_id}: {len(clauses)} clauses")
        all_clauses.extend(clauses)
    store = ClauseStore(config.KB_DB)
    store.rebuild(all_clauses)
    store.close()
    index = SearchIndex(config.KB_DB)
    index.rebuild(all_clauses)
    index.close()
    return len(all_clauses), len(all_clauses)


def _cmd_quote(search_text: str) -> int:
    """Authoring aid: print clauses containing the text, for copy-pasting verbatim quotes."""
    store = ClauseStore(config.KB_DB)
    needle = normalize(search_text)
    matches = [c for c in store.all() if needle in normalize(c.text)]
    store.close()
    for clause in matches[:10]:
        print(f"--- {clause.clause_id} (page {clause.page}) ---")
        print(clause.text)
        print()
    print(f"{len(matches)} clause(s) matched")
    return 0


def format_finding(finding: Finding) -> str:
    """Render one finding for the terminal.

    A finding the documents did not support prints its kb_status instead of a
    source line, so "no reference in the KB" can never be mistaken for a cited
    finding -- and is never silently indistinguishable from one.
    """
    if finding.finding_type == "provider_confirmation":
        # Not a missing axis: the diagnosis exists, it just isn't the treating
        # doctor's. "missing provider_confirmation" reads as the wrong problem.
        headline = (f"[{finding.severity}] {finding.condition} — not confirmed by the treating "
                    f"doctor ({finding.evidence_excerpt})")
    else:
        headline = f"[{finding.severity}] {finding.condition} — missing {finding.axis}"
    lines = [headline, f"  {finding.recommendation}"]
    if finding.kb_status != KB_SUPPORTED:
        lines.append(f"  {finding.kb_status} — evidence: \"{finding.evidence_excerpt[:90]}\"")
    for cite in finding.citations:
        lines.append(f"  source: {cite.clause_id} (p.{cite.page}) — \"{cite.quote[:90]}...\"")
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, llm_stage=None) -> int:
    parser = argparse.ArgumentParser(prog="cdi_kb")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build-kb", help="extract, chunk, store, and index the corpus")
    quote = sub.add_parser("quote", help="find clauses containing text (for authoring citations)")
    quote.add_argument("search_text")
    sub.add_parser("verify", help="run V1-V5 KB verification")
    audit = sub.add_parser("audit", help="audit a note file against the KB")
    audit.add_argument("note_file", type=Path)
    audit.add_argument("--llm", action="store_true", help="enable implicit-condition inference")
    audit.add_argument("--json", action="store_true", dest="as_json")
    audit.add_argument(
        "--doc-type", dest="doc_type", choices=("auto", *DOC_TYPES), default="auto",
        help="override auto-detected doc type ('auto' lets the note's own shape decide)",
    )
    demo = sub.add_parser("demo", help="serve the paste-a-note web demo")
    demo.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if args.command == "build-kb":
        stored, indexed = build_kb()
        print(f"clauses stored: {stored}, indexed: {indexed}")
        return 0
    if args.command == "quote":
        return _cmd_quote(args.search_text)
    if args.command == "verify":
        report = run_verification()
        for failure in report.failures:
            print(f"FAIL  {failure}")
        for note in report.notes:
            print(f"INFO  {note}")
        print(f"stats: {report.stats}")
        print("VERIFICATION PASSED" if report.passed else "VERIFICATION FAILED")
        return 0 if report.passed else 1
    if args.command == "audit":
        doc_type = None if args.doc_type == "auto" else args.doc_type
        result = run_audit(
            args.note_file.read_text(encoding="utf-8"),
            doc_type=doc_type, use_llm=args.llm, llm_stage=llm_stage,
        )
        if args.as_json:
            print(json.dumps(dataclasses.asdict(result), indent=2))
        else:
            print(f"doc type: {result.active_doc_type}")
            for finding in result.findings:
                print(format_finding(finding))
            print(f"{len(result.findings)} finding(s)")
            if result.llm_error is not None:
                print(f"llm stage unavailable ({result.llm_error}) — deterministic findings only")
        return 0
    if args.command == "demo":
        import uvicorn  # inline import: server dependency only needed for demo command
        uvicorn.run("cdi_kb.webapp:app", port=args.port)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
