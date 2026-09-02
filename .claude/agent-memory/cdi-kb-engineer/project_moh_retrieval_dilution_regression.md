---
name: project-moh-retrieval-dilution-regression
description: RESOLVED by Task 3b (commit 3b048dc) — CANDIDATE_LIMIT raised 16->32 restored reach for the 3 axes MOH registration diluted out of BM25 top-K; kept for root-cause history and the reproduction methodology
metadata:
  type: project
---

**Status: resolved, 2026-09-01, Task 3b (branch `moh-protocols-kb-source`,
commit `3b048dc`).** After Phase 3 Task 3 registered the 31 MOH sources
(11 -> 42 sources), `cdi_kb.llm_infer.retrieve_candidates`'s fixed-size
top-K window (`CANDIDATE_LIMIT`, then 16) stopped reaching
`urinary tract infection|site`, `surgical wound infection|onset`, and
`surgical wound infection|agent` — same-condition MOH-UTI/MOH-SSI/MOH-
SEPSIS-MAT/MOH-ABX-PROPH/MOH-IAI content outranked the pre-existing
CDI-2021 citation for those queries. Task 3b's fix was simply to raise
`CANDIDATE_LIMIT` from 16 to 32 (`PER_SOURCE_LIMIT`, still 6, was
deliberately left alone — a prior sweep showed lowering it only hurts
reach further by throttling the source that holds the cited clause).
Re-swept 8/16/24/32/40/48/64 on the post-fix, post-rebuild KB: unreachable
axis count is 17/11/9/8/8/8/8 out of 65 total axes respectively —
reachability plateaus at 57/65 from limit 32 onward, and at 32 the
unreachable set is exactly the pre-existing pinned 8
(`test_retrieval_reach_across_every_requirement_axis` in
`tests/test_llm_kb_validation.py`; the total axis count is 65 now, not the
37 it was before Task 3 registered MOH content — the requirement set itself
didn't change, but the denominator in that test's own bookkeeping did).

**Root cause (unchanged from the original write-up, kept for history):**
`retrieve_candidates` returns a fixed-size top-K BM25 window; MOH-UTI,
MOH-SSI, MOH-SEPSIS-MAT, MOH-ABX-PROPH, MOH-IAI, and MOH-SEPSIS-PED clauses
share infection/agent/site vocabulary with the CDI-2021 booklet's own
`documenting-for-specificity`/`pelvic-collection` clauses, so they now
compete for the same slots. This is the same "index diluted by multi-source
content" mechanism V3's title-reachability fallback tier already tolerates
for CKD, HF, stroke, AKI, diabetes and obesity — widening the window just
buys back headroom rather than eliminating the mechanism, which is why 8
axes (heart failure, obesity, stroke, corneal ulcer — a structurally
different problem, see the test's own docstring) remain unreachable by any
window size.

See [[project_moh_colon_heading_acceptor]] for the rest of Phase 3's status
(Tasks 1-3b done as of this write-up; Tasks 4-6 — junk-title guard beyond
what 3b covered, authority ordering, verification-stats rewrite — still
pending). See [[feedback_shared_var_kb_sqlite_is_unreliable_mid_task]] for
why a live re-measurement of the *original* dilution (at limit 16, before
3b's fix) needed a fresh single-writer `build-kb` run rather than trusting
reads against the working tree's `var/kb.sqlite` directly.
