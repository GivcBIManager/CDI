---
name: project-moh-colon-heading-acceptor
description: Phase 3 (branch moh-protocols-kb-source) is COMPLETE as of 2026-09-01 including the final whole-branch review fixes — 42 sources, 4,655 clauses, full suite green (352 passed, 2 deselected live), cli verify PASSED, dilution guard at title_reachable=7/mandate_anchored=1 (within the <=7/<=1 ceiling); moh_chunker's four heading rules described below
metadata:
  type: project
---

Phase 3 (`docs/superpowers/plans/2026-09-01-moh-protocols-kb-source.md`,
branch `moh-protocols-kb-source`) ingests 31 curated MOH-KSA protocol PDFs as
a third citation authority. **All tasks are done, including the final
whole-branch code-review fixes applied 2026-09-01** (see
`.superpowers/sdd/final-review-fixes-report.md`, gitignored, for the full
writeup). Commits of note: `d62a0e6` (Task 3, config.SOURCES registration),
`3b048dc`/`1097479` (Task 3b, PUA bullet widening + CANDIDATE_LIMIT 16->32),
`e61d830` (authority ordering MOH->CHI->CDI-2021), `075200b` (dilution guard
+ 42-source stats), then the review-fix commits `751a5e1` (colon acceptor
`_COLON_HEADING_MIN_WORDS` 2->1), `5ad5d0f` (webapp XSS guard extended to
`c.authority`), `71bc675` (`cli quote --source` filter), `61af68e` (stale
MOH-era comment/count fixes), `e5e397c` (README-DEMO + design-doc
corrections).

**Current measured state:** `python -m cdi_kb.cli build-kb` produces **4,655**
clauses across 42 sources (11 pre-existing baselines unchanged; 31 MOH
sources, min MOH-SSTI at 12, MOH total 1,638 clauses). `cli verify` prints
`VERIFICATION PASSED`, `stats.sources: 42`, `title_reachable_entries: 7`,
`mandate_anchored_entries: 1` (both at the re-baselined `<=7`/`<=1` ceiling in
`tests/test_kb_verification.py::test_moh_ingestion_does_not_worsen_retrieval_fallbacks`
— that re-baseline is explicitly once-only per the test's own comment; a
future trip is a real finding, not grounds for a second re-baseline). Full
`pytest`: 352 passed, 2 deselected (`@pytest.mark.live`).

`src/cdi_kb/moh_chunker.py`'s `_is_moh_heading` has four rules: three
rejectors (bullet item — full Wingdings/Symbol PUA block U+F000-U+F0FF,
abbreviation-gloss, datestamp — win unconditionally) then, if the CHI
`_is_heading` capitalization gate fails, a narrow `_is_colon_heading`
acceptor (ends with `:`, `<=60` chars, `>=1` alpha-led word — **not 2**; the
original 2-word minimum was measured in a way that structurally couldn't see
the single-word labels it excluded, e.g. "References:"/"Methodology:", and
was corrected to 1 in the final review pass), uppercase first char. The
module's own docstring (rewritten in the review-fix pass) carries the current
measured numbers for every rejector/acceptor's admit/drop counts — read it
directly rather than trusting any older snapshot, including this one, since
these numbers move whenever the corpus or acceptor changes.

`cli.py quote` now takes `--source SRC_ID` to filter matches to one source's
clause_ids (MOH clauses sort last alphabetically in `store.all()` and were
otherwise invisible past `matches[:10]` for common terms) and always prints a
per-source match-count breakdown so truncation is visible.

See [[project_moh_retrieval_dilution_regression]] for the CANDIDATE_LIMIT
history (still resolved, unchanged by this pass) and
[[feedback_no_fabricated_test_literals]] for why the colon acceptor exists at
all.
