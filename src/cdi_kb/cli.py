"""Command-line entry points: python -m cdi_kb.cli <command>."""

import argparse
import sys

from cdi_kb import config
from cdi_kb.clauses import ClauseStore, chunk_booklet
from cdi_kb.extract import extract_pages
from cdi_kb.index import SearchIndex
from cdi_kb.normalize import normalize
from cdi_kb.verify import run_verification


def build_kb() -> tuple[int, int]:
    pages = extract_pages(config.BOOKLET_PDF, config.RAW_TEXT_DIR)
    clauses = chunk_booklet(pages)
    store = ClauseStore(config.KB_DB)
    store.rebuild(clauses)
    store.close()
    index = SearchIndex(config.KB_DB)
    index.rebuild(clauses)
    index.close()
    return len(clauses), len(clauses)


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cdi_kb")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build-kb", help="extract, chunk, store, and index the corpus")
    quote = sub.add_parser("quote", help="find clauses containing text (for authoring citations)")
    quote.add_argument("search_text")
    sub.add_parser("verify", help="run V1-V5 KB verification")
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
    return 1


if __name__ == "__main__":
    sys.exit(main())
