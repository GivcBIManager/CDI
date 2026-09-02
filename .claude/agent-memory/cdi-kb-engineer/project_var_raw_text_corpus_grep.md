---
name: project-var-raw-text-corpus-grep
description: var/raw_text/*.json is a queryable cache of extracted PDF page text — use it to independently verify a "verbatim corpus line" claim without touching the source PDFs
metadata:
  type: project
---

`var/raw_text/*.json` (gitignored, populated by `cdi_kb.extract.extract_pages`)
holds one JSON file per source PDF, keyed by a content-fingerprint suffix in
the filename (e.g. `Surgical-Site-Infections-Guidelines.a5ffbdc9.json`). Each
file is either a list of page objects or `{"pages": [...]}`, each page having
a `text` field with the raw extracted page text (line-broken on `\n`,
carrying the corpus's expected `�` extraction artifacts).

**Why this matters:** it's the fastest way to independently confirm a string
is a real, verbatim, standalone line from the corpus before trusting it in a
test fixture or a YAML citation quote — see
[[feedback_no_fabricated_test_literals]]. A quick loop reading each JSON,
splitting `text.splitlines()`, and checking `line.strip() == target` (or
membership in a target set) across all files answers "does this string exist
verbatim, and how many times / in which sources" in a few seconds, no PDF
re-extraction needed.

**How to apply:** Before accepting or writing any "verbatim corpus line" test
literal or citation quote, grep it against this cache rather than trusting
the claim at face value. If the file for a given source doesn't exist yet,
call `extract_pages(path, config.RAW_TEXT_DIR)` once to populate it (cheap,
cached thereafter).
