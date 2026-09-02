---
name: feedback-shared-var-kb-sqlite-is-unreliable-mid-task
description: var/kb.sqlite (and other gitignored var/ build artifacts) can be rebuilt by another concurrent session mid-task — don't trust two reads of it to be consistent; do your own build-kb run before measuring anything from it
metadata:
  type: feedback
---

During Task 3b, running the *identical* read-only Python script against
`var/kb.sqlite` twice in a row (a few seconds apart, no code changes in
between) returned different results — once counting PUA-glyph-prefixed
`section_title`s, once counting dash-led ones, on the same query. `git
status` stayed clean throughout (the DB is gitignored, so a rebuild never
shows there). The only plausible explanation is another concurrent session
on this machine running `build-kb` (or similar) against the same shared
file at the same time — consistent with the standing repo-wide warning
("other sessions edit d:\CDI mid-task").

**Why this matters:** a "measured on the current KB" claim built from two
sequential reads of a shared build artifact can silently mix pre- and
post-rebuild state, or two different concurrent sessions' states, and look
internally consistent while being wrong.

**How to apply:** before trusting any count derived from `var/kb.sqlite`
(or `var/raw_text/*.json`, or any other gitignored `var/` artifact) for a
report or a docstring number, do your own single-writer `python -m
cdi_kb.cli build-kb` run first and measure against *that* run's own output
— don't assume a file sitting in the working tree reflects a stable,
single-session state. If a brief hands you specific "measured" numbers
(e.g. a defect count with example strings), it's fine to trust the numbers
as given (treat them as already-verified evidence, same as any other
briefed fact) rather than re-deriving them from a potentially-contended
shared file — but spot-check any concrete/enumerable examples the brief
gives (e.g. verbatim strings) against something append-only and less
likely to be actively rewritten, like `var/raw_text/*.json` (see
[[project_var_raw_text_corpus_grep]]), or against your own fresh build.
